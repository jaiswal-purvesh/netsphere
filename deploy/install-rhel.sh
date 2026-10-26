#!/usr/bin/env bash
# NetSphere installer for RHEL 8/9 (also works on Rocky/Alma). Idempotent: re-running
# keeps existing secrets in deploy/.env.prod.
#
#   deploy/install-rhel.sh [--host FQDN_OR_IP] [--demo] [--https] [--engine podman|docker]
#                          [--offline bundle.tar.gz] [--http-port N] [--https-port N]
#                          [--no-firewall] [--no-systemd] [--admin-email you@corp]
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="$DEPLOY_DIR/.env.prod"

HOST="" DEMO=false HTTPS=false ENGINE_ARG="" OFFLINE="" HTTP_PORT="" HTTPS_PORT=""
FIREWALL=true SYSTEMD=true ADMIN_EMAIL="admin@netsphere.local"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --demo) DEMO=true; shift;;
    --https) HTTPS=true; shift;;
    --engine) ENGINE_ARG="$2"; shift 2;;
    --offline) OFFLINE="$2"; shift 2;;
    --http-port) HTTP_PORT="$2"; shift 2;;
    --https-port) HTTPS_PORT="$2"; shift 2;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2;;
    --no-firewall) FIREWALL=false; shift;;
    --no-systemd) SYSTEMD=false; shift;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done

log()  { echo "==> $*"; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "ERROR: $*" >&2; exit 1; }
rand() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "$1"; }

# ---------- preflight ----------
log "preflight"
[[ -r /etc/os-release ]] && . /etc/os-release || true
echo "  OS: ${PRETTY_NAME:-unknown}  arch: $(uname -m)"
case "${ID:-}" in rhel|rocky|almalinux|centos|fedora) ;; *) warn "not a RHEL-family OS; continuing anyway";; esac
command -v curl >/dev/null || die "curl is required (dnf install curl)"
command -v python3 >/dev/null || die "python3 is required for the smoke test (dnf install python3)"
MEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo); (( MEM_KB >= 3500000 )) || warn "less than ~4 GB RAM; the frontend build may fail"
DISK_GB=$(df -Pk "$ROOT" | awk 'NR==2{print int($4/1048576)}'); (( DISK_GB >= 10 )) || warn "only ${DISK_GB} GB free; need ~10 GB for images"

if [[ -n "$ENGINE_ARG" ]]; then ENGINE="$ENGINE_ARG"
elif command -v podman >/dev/null; then ENGINE=podman
elif command -v docker >/dev/null; then ENGINE=docker
else
  die "no container engine. On RHEL install one first:
    sudo dnf install -y podman podman-compose      # RHEL 8/9 (podman-compose needs EPEL on some releases)
  or Docker CE per docs/DEPLOYMENT_RHEL.md"
fi
export NETSPHERE_ENGINE="$ENGINE"
log "container engine: $ENGINE"
if [[ "$ENGINE" == podman ]]; then
  podman compose version >/dev/null 2>&1 || command -v podman-compose >/dev/null \
    || die "neither 'podman compose' nor podman-compose found (sudo dnf install -y podman-compose, EPEL if needed)"
fi
if command -v getenforce >/dev/null; then echo "  SELinux: $(getenforce) (volume mounts use :Z labels; leave it enforcing)"; fi

ROOTLESS=false; [[ $EUID -ne 0 ]] && ROOTLESS=true
if $ROOTLESS && [[ "$ENGINE" == podman ]]; then
  : "${HTTP_PORT:=8080}" "${HTTPS_PORT:=8443}"
  log "rootless podman cannot bind ports <1024 -> using $HTTP_PORT/$HTTPS_PORT (or run as root / lower net.ipv4.ip_unprivileged_port_start)"
fi
: "${HTTP_PORT:=80}" "${HTTPS_PORT:=443}"

# ---------- env file ----------
if [[ -f "$ENV_FILE" ]]; then
  log "keeping existing $ENV_FILE (secrets unchanged)"
else
  log "generating $ENV_FILE with random secrets"
  [[ -n "$HOST" ]] || { HOST="$(hostname -f 2>/dev/null || hostname)"; warn "--host not given, using '$HOST'"; }
  scheme=http; $HTTPS && scheme=https
  origin="$scheme://$HOST"
  [[ "$scheme" == http && "$HTTP_PORT" != 80 ]] && origin="$origin:$HTTP_PORT"
  [[ "$scheme" == https && "$HTTPS_PORT" != 443 ]] && origin="$origin:$HTTPS_PORT"
  umask 077
  cat > "$ENV_FILE" <<ENVEOF
POSTGRES_PASSWORD=$(rand 32)
JWT_SECRET=$(rand 64)
INTEGRATIONS_ENCRYPTION_KEY=$(rand 64)
SEED_ADMIN_EMAIL=$ADMIN_EMAIL
SEED_ADMIN_PASSWORD=$(rand 20)
SEED_DEMO_DATA=$DEMO
CORS_ORIGINS=["$origin"]
HTTP_PORT=$HTTP_PORT
HTTPS_PORT=$HTTPS_PORT
NGINX_CONF=$($HTTPS && echo https.conf || echo http.conf)
NETSPHERE_VERSION=latest
ENVEOF
  chmod 600 "$ENV_FILE"
fi

if grep -q '^NGINX_CONF=https.conf' "$ENV_FILE"; then
  [[ -s "$DEPLOY_DIR/certs/tls.crt" && -s "$DEPLOY_DIR/certs/tls.key" ]] || die "HTTPS selected but deploy/certs/tls.crt and tls.key are missing.
  Place your CA-issued cert/key there (or for a quick self-signed test:
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 -keyout deploy/certs/tls.key -out deploy/certs/tls.crt -subj '/CN=$HOST')"
fi

# ---------- images ----------
if [[ -n "$OFFLINE" ]]; then
  log "offline mode: loading images from $OFFLINE"
  "$DEPLOY_DIR/netsphere" load "$OFFLINE"
else
  log "building images (several minutes the first time)"
  "$DEPLOY_DIR/netsphere" config
  "$DEPLOY_DIR/netsphere" build
fi

# ---------- firewall ----------
P_HTTP=$(grep '^HTTP_PORT=' "$ENV_FILE" | cut -d= -f2); P_HTTPS=$(grep '^HTTPS_PORT=' "$ENV_FILE" | cut -d= -f2)
if $FIREWALL && command -v firewall-cmd >/dev/null && systemctl is-active --quiet firewalld 2>/dev/null; then
  if [[ $EUID -eq 0 ]]; then
    log "opening firewalld ports $P_HTTP/tcp and $P_HTTPS/tcp"
    firewall-cmd --permanent --add-port="$P_HTTP/tcp" --add-port="$P_HTTPS/tcp" >/dev/null && firewall-cmd --reload >/dev/null
  else
    warn "not root: run  sudo firewall-cmd --permanent --add-port=$P_HTTP/tcp --add-port=$P_HTTPS/tcp && sudo firewall-cmd --reload"
  fi
fi

# ---------- start ----------
log "starting the stack"
"$DEPLOY_DIR/netsphere" up
"$DEPLOY_DIR/netsphere" smoke

# ---------- systemd ----------
if $SYSTEMD && command -v systemctl >/dev/null; then
  engine_unit=""; [[ "$ENGINE" == docker ]] && engine_unit="docker.service"
  render() { sed -e "s#@ROOT@#$ROOT#g" -e "s#@ENGINE@#$ENGINE#g" -e "s#@ENGINE_UNIT@#$engine_unit#g" -e "s#@WANTED_BY@#$1#g" "$2"; }
  if [[ $EUID -eq 0 ]]; then
    log "installing systemd units (start on boot + nightly backup)"
    render multi-user.target "$DEPLOY_DIR/systemd/netsphere.service.tpl" > /etc/systemd/system/netsphere.service
    render timers.target "$DEPLOY_DIR/systemd/netsphere-backup.service.tpl" > /etc/systemd/system/netsphere-backup.service
    cp "$DEPLOY_DIR/systemd/netsphere-backup.timer" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable netsphere.service netsphere-backup.timer >/dev/null 2>&1
    systemctl start netsphere-backup.timer
  else
    log "installing systemd --user units (needs linger to survive logout/reboot)"
    ud="$HOME/.config/systemd/user"; mkdir -p "$ud"
    render default.target "$DEPLOY_DIR/systemd/netsphere.service.tpl" > "$ud/netsphere.service"
    render default.target "$DEPLOY_DIR/systemd/netsphere-backup.service.tpl" > "$ud/netsphere-backup.service"
    cp "$DEPLOY_DIR/systemd/netsphere-backup.timer" "$ud/"
    systemctl --user daemon-reload
    systemctl --user enable netsphere.service netsphere-backup.timer >/dev/null 2>&1 || true
    loginctl enable-linger "$USER" 2>/dev/null || warn "run: sudo loginctl enable-linger $USER"
  fi
fi

SCHEME=http; P=$P_HTTP; grep -q '^NGINX_CONF=https.conf' "$ENV_FILE" && { SCHEME=https; P=$P_HTTPS; }
echo
log "NetSphere is up:  $SCHEME://${HOST:-<this-host>}:$P"
echo "    admin login : $(grep '^SEED_ADMIN_EMAIL=' "$ENV_FILE" | cut -d= -f2)"
echo "    password    : stored in $ENV_FILE (SEED_ADMIN_PASSWORD) - read it there, change it after first login"
echo "    back up     : INTEGRATIONS_ENCRYPTION_KEY in that file; losing it makes stored integration secrets unreadable"
