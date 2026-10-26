# NetSphere — Security architecture and known gaps (Phase 1)

This lists what's actually implemented and, just as importantly, what
isn't — per the project rule against pretending an integration or control
is production-ready when it's a Phase 1 stand-in.

## Implemented

- **Auth:** OAuth2 password flow + JWT (HS256), `python-jose`. Password
  hashing via `bcrypt` directly (see `app/security.py` for why not
  `passlib` — a real compatibility bug hit during this build, not a
  style preference).
- **RBAC:** role → permission checks (`app/deps.py::require_permission`),
  enforced as a FastAPI dependency on every mutating IPAM/org endpoint.
  Seeded roles and grants in `app/core/rbac_seed.py`. `SUPER_ADMIN` bypasses
  all checks; every other role's grants are explicit, not inherited.
- **Audit logging:** every mutating request that goes through
  `app/services/audit.py::record` writes a row (actor, action, resource,
  before/after, request_id, result). Currently wired into network create
  and subnet allocate; not yet on every mutating endpoint (org hierarchy
  CRUD isn't audited yet — small, mechanical follow-up).
- **Structured logs + request IDs:** every HTTP request gets a
  `request_id` (client-supplied `X-Request-ID` or generated), present on
  every log line for that request and echoed back in the response header.
- **Health/readiness:** `/health` (liveness only) and `/ready` (checks
  Postgres + Redis) are real, not stubs — `/ready` will actually report
  `degraded` if either dependency is unreachable.
- **No secrets in source or the database:** `cloud_accounts.credential_ref`
  is a plain pointer string; nothing in this delivery reads it.

## Explicitly NOT implemented (do not assume otherwise)

- **No OIDC/SSO/Entra ID.** Local JWT only. Building refresh-token rotation
  now would be throwaway work once OIDC replaces this model in Phase 10 —
  deliberately not done.
- **No MFA.** Not designed against yet beyond "the architecture doesn't
  preclude it."
- **No tamper-evident audit log.** The `audit_logs` table is a normal,
  editable-by-a-DBA table — not hash-chained like fwauto's `audit_event`
  design. See `firewall-policy-automation-design.md` §3.10 for the
  reference design if/when this needs upgrading.
- **No resource-scoped RBAC.** Any user with `ipam:view` sees every
  network across every business unit. The `user_roles.scope_business_unit_id`
  column exists for this (see ERD.md) but nothing reads it yet.
- **No rate limiting, no CSRF protection.** JSON API with bearer tokens
  has no CSRF surface today, but rate limiting is a real gap for a
  publicly reachable deployment — not addressed in Phase 1.
- **No secrets manager integration.** `credential_ref` is inert.
- **Frontend token storage is `localStorage`,** not an httpOnly cookie —
  a deliberate simplification for a local-dev SPA talking to a
  same-origin-proxied API. This is the first thing to change (to an
  httpOnly, SameSite cookie issued by the backend) before any deployment
  reachable by untrusted script — tracked as a Phase 10 item alongside
  OIDC, since both change the auth model at once.
- **Dependency advisory:** `next@14.2.35` still carries open Next.js
  advisories that were only fully resolved in the Next.js 16 line (a
  breaking major-version change not undertaken in this delivery — see
  `npm audit` output at build time). None of the advisories' attack
  surfaces (Image Optimizer, Server Actions, i18n middleware) are used by
  this app today, but this is noted here rather than left to be
  discovered later.

## Dependency compatibility fixes (real bugs hit and fixed, not style choices)

- **`prometheus-fastapi-instrumentator` pinned to `8.1.0`, not `7.0.0`.**
  `7.0.0` crashes on *every* request (`AttributeError: '_IncludedRouter'
  object has no attribute 'path'`) against `fastapi==0.141.1`'s router
  internals — including `/health`, which made the backend container
  report unhealthy and made every API call (login included) 500. Root
  cause and fix reproduced and verified locally before pinning `8.1.0`
  in `requirements.txt`. If `fastapi` is ever bumped again, re-check this
  pin rather than assuming the instrumentator still matches.
- **`passlib[bcrypt]` removed in favor of calling `bcrypt` directly** — see
  `app/security.py` and the note above under Implemented.
- **No `pytest-asyncio`** — it pins `pytest<9`, conflicting with this
  repo's `pytest==9.1.1`; removed since no test in the suite is async.
- **Frontend `Dockerfile` bakes `BACKEND_URL` in as a build `ARG`, not just
  a compose-time `environment:` value.** `next.config.js`'s `rewrites()`
  runs once at `next build` and freezes its resolved destination into
  `.next/routes-manifest.json`; `next start` only reads that static file
  and never re-invokes `rewrites()` against the container's runtime env.
  Without the build-time `ARG`/`ENV`, every proxied `/api/*` call 500s
  with `ECONNREFUSED 127.0.0.1:8000` (the fallback default) no matter what
  `BACKEND_URL` is set to at `docker compose up` time — this broke login
  end-to-end and was reproduced and confirmed fixed locally before this
  note was written. If the frontend is ever pointed at a different backend
  URL/topology, rebuild with `--build-arg BACKEND_URL=...`; changing only
  `docker-compose.yml`'s `environment:` block does nothing for this proxy.

## Destructive-operation gating

There is currently nothing destructive to gate — Phase 1/2 only creates
IPAM records. The approval-workflow design for when that changes (Terraform
apply, firewall rule pushes) already exists in
`firewall-policy-automation-design.md` and should be reused wholesale in
Phase 7, not redesigned.
