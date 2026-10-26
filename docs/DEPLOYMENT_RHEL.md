# Deploying NetSphere on a Red Hat Linux VM

Single-VM deployment: Postgres, Redis, API, Celery worker, UI and an nginx
front door, all in containers (Podman or Docker) driven by
`docker-compose.prod.yml` and the `deploy/netsphere` CLI.

## 0. What the infra team must provide

| Item | Notes |
|---|---|
| RHEL 8 or 9 (Rocky/Alma fine), x86_64 | 4 vCPU, 8 GB RAM, 40 GB disk recommended (min 4 GB RAM / 10 GB free) |
| sudo / root for initial setup | after that it can run rootless |
| Container engine | Podman (ships with RHEL) **or** Docker CE |
| Compose | `podman-compose` (EPEL) / `podman compose`, or the Docker compose plugin |
| Outbound internet to registries **or** the offline bundle (section 3) | docker.io, pypi.org, registry.npmjs.org, deb.debian.org |
| Inbound TCP 80/443 (or 8080/8443 rootless) from users | the installer opens firewalld |
| DNS name + TLS cert/key (optional but recommended) | |
| Later, for real discovery: egress to cloud APIs, Panorama/FortiGate, TCPWave, SNMP | not needed for the demo |

```bash
# Podman route (RHEL 9 shown; RHEL 8 is the same)
sudo dnf install -y podman curl python3 git
sudo dnf install -y epel-release && sudo dnf install -y podman-compose   # or: pip3 install --user podman-compose
```
```bash
# Docker CE route
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

## 1. Get the code onto the VM

`git clone` or copy/untar the repo, e.g. to `/opt/netsphere`.

## 2. Online install

```bash
cd /opt/netsphere
deploy/install-rhel.sh --host netsphere.corp.example           # HTTP
deploy/install-rhel.sh --host netsphere.corp.example --https   # needs deploy/certs/tls.crt + tls.key first
deploy/install-rhel.sh --host 10.1.2.3 --demo                  # also load the demo dataset
```

The installer: checks OS/RAM/disk/engine, generates `deploy/.env.prod` with
random secrets (kept on re-run), builds images, opens firewalld, starts the
stack, waits for health, runs the smoke test and installs systemd units
(start on boot + nightly DB backup at 02:15). The admin password is in
`deploy/.env.prod` (`SEED_ADMIN_PASSWORD`); it is never printed to logs.
Options: `--engine`, `--http-port`, `--https-port`, `--admin-email`,
`--no-firewall`, `--no-systemd`, `--offline`.

Rootless Podman can't bind ports below 1024, so the installer picks
8080/8443 (or run as root, or `sysctl net.ipv4.ip_unprivileged_port_start=80`).

## 3. Air-gapped install

On any machine with internet and Docker/Podman (an Apple-silicon Mac is
fine - images are cross-built for amd64):

```bash
deploy/netsphere bundle amd64          # -> netsphere-bundle-amd64.tar.gz (~1.5 GB)
```

Copy the bundle and the repo to the VM, then:

```bash
deploy/install-rhel.sh --host netsphere.corp.example --offline netsphere-bundle-amd64.tar.gz
```

(Note: `bundle` expects a `deploy/.env.prod` only for `NETSPHERE_VERSION`; it
defaults to `latest` when absent. Cross-arch builds on a Mac need Docker
Desktop or `podman machine`.)

## 4. Day-2 operations

```bash
deploy/netsphere status | logs [svc] | restart [svc] | up | down
deploy/netsphere smoke              # login + API checks through nginx
deploy/netsphere backup             # gzip pg_dump -> backups/ (keeps 14)
deploy/netsphere restore backups/netsphere-YYYYmmdd-HHMMSS.sql.gz
deploy/netsphere update             # backup, rebuild, restart (runs migrations), smoke
deploy/netsphere demo               # load demo extras (needs SEED_DEMO_DATA=true on first start)
```

To update: replace the repo contents (keep `deploy/.env.prod`, `deploy/certs`,
`backups`) and run `deploy/netsphere update`.

## 5. Things to know

- **INTEGRATIONS_ENCRYPTION_KEY** encrypts stored firewall/IPAM secrets.
  Back it up with the DB dump and never change it.
- The backend **refuses to start** in production with default/short secrets
  or `DEBUG=true`.
- SELinux stays enforcing; bind mounts carry `:Z`. If you see `Permission denied`
  on the nginx config or certs, check `ls -Z deploy/` and `ausearch -m avc -ts recent`.
- Only nginx publishes ports. Postgres/Redis/API are not reachable off-box.
- Default is no demo data. Real data comes from the discovery/integration
  pages once the VM can reach the clouds and devices. Use `--demo` for a demo box.
- Healthcheck in the Dockerfile needs `podman build --format docker` if you
  build manually; compose in this repo defines its own healthchecks.
- Logout/reboot survival for rootless: `loginctl enable-linger $USER` (installer tries).

## 6. Troubleshooting

| Symptom | Check |
|---|---|
| Installer says no compose | `dnf install podman-compose` (EPEL) or Docker compose plugin |
| `short-name resolution` errors | images are fully qualified here; check `/etc/containers/registries.conf` for blocked registries |
| Backend restarts with "Refusing to start" | fix `deploy/.env.prod` (see message) |
| UI loads, API 502 | `deploy/netsphere logs backend` (migration failure?) |
| Can't reach from other hosts | `sudo firewall-cmd --list-ports`; cloud/VLAN security group |
| Frontend build OOM | give the VM >= 4 GB RAM or build elsewhere and use `--offline` |
