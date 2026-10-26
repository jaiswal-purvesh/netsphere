"""Central settings object. Everything configurable comes from the
environment (see .env.example at the repo root) — nothing here is a secret,
and nothing in the app reads os.environ directly outside this module.
"""
from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NetSphere"
    app_subtitle: str = "Enterprise Hybrid Multi-Cloud Network Management & Automation Platform"
    environment: str = "local"  # local | ci | staging | production
    debug: bool = True

    database_url: str = "postgresql+psycopg://netsphere:netsphere@localhost:5432/netsphere"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Encrypts firewall/Panorama/FortiGate integration secrets at rest
    # (app/services/secrets.py). Any string works — it is SHA-256'd into a
    # valid Fernet key rather than needing to be pre-formatted — but it MUST
    # be overridden to a long random value outside local dev, and must not
    # change afterwards or every stored secret becomes undecryptable.
    integrations_encryption_key: str = "dev-only-integrations-key-change-me"

    cors_origins: list[str] = ["http://localhost:3000"]

    # First user seeded on `alembic upgrade` + `python -m app.seed` if the
    # users table is empty. Dev convenience only — never used in the
    # production seed path (there is none yet; see ROADMAP Phase 10).
    seed_admin_email: str = "admin@netsphere.local"
    seed_admin_password: str = "ChangeMe123!"

    # When false, `python -m app.seed` still creates permissions, roles and
    # the admin user, but skips the demo org + mock cloud accounts + mock
    # discovery. Production installs default this to false.
    seed_demo_data: bool = True

    # In production the seed step must never echo the admin password to logs.
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> "Settings":
        if self.environment.lower() == "production":
            problems = []
            if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be a random value of 32+ characters")
            if self.integrations_encryption_key.startswith("dev-only") or len(self.integrations_encryption_key) < 32:
                problems.append("INTEGRATIONS_ENCRYPTION_KEY must be a random value of 32+ characters")
            if self.seed_admin_password == "ChangeMe123!":
                problems.append("SEED_ADMIN_PASSWORD must not be the default")
            if self.debug:
                problems.append("DEBUG must be false")
            if problems:
                raise ValueError("Refusing to start with insecure production settings: " + "; ".join(problems))
        return self


settings = Settings()
