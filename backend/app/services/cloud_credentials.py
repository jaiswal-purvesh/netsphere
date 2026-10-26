"""Vendor-shaped validation + masking for CloudIntegration credentials.
Mirrors app/services/secrets.py's role for FirewallIntegration: this is
where the one JSON blob gets checked against what each cloud actually
needs, and where a safe-to-display summary gets computed. The full dict is
never returned by the API — only `summarize()`'s output is.
"""
from __future__ import annotations

import json

from app.services import secrets as secretsvc

# Required keys per vendor. AWS supports two auth modes so it's handled
# separately below; the others are a single fixed shape.
REQUIRED_KEYS: dict[str, list[str]] = {
    "azure": ["tenant_id", "client_id", "client_secret", "subscription_id"],
    "gcp": ["service_account_json"],
    "oci": ["user_ocid", "tenancy_ocid", "fingerprint", "private_key_pem", "region"],
}


class CredentialValidationError(ValueError):
    pass


def validate(vendor: str, creds: dict) -> None:
    if vendor == "aws":
        mode = creds.get("auth_mode")
        if mode == "access_key":
            missing = [k for k in ("access_key_id", "secret_access_key") if not creds.get(k)]
        elif mode == "role_arn":
            missing = [k for k in ("role_arn",) if not creds.get(k)]
        else:
            raise CredentialValidationError("aws credentials need auth_mode: 'access_key' or 'role_arn'")
        if missing:
            raise CredentialValidationError(f"aws {mode} credentials missing: {', '.join(missing)}")
        return

    required = REQUIRED_KEYS.get(vendor)
    if required is None:
        raise CredentialValidationError(f"unknown vendor: {vendor}")
    missing = [k for k in required if not creds.get(k)]
    if missing:
        raise CredentialValidationError(f"{vendor} credentials missing: {', '.join(missing)}")

    if vendor == "gcp":
        try:
            parsed = json.loads(creds["service_account_json"])
        except (ValueError, TypeError) as e:
            raise CredentialValidationError("gcp service_account_json is not valid JSON") from e
        if "client_email" not in parsed or "private_key" not in parsed:
            raise CredentialValidationError(
                "gcp service_account_json doesn't look like a service account key "
                "(missing client_email/private_key)",
            )


def summarize(vendor: str, creds: dict) -> str:
    """A short, non-secret preview shown in the UI in place of the actual
    credential — analogous to FirewallIntegration.secret_last4."""
    if vendor == "aws":
        if creds.get("auth_mode") == "role_arn":
            return creds["role_arn"]
        key = creds.get("access_key_id", "")
        return f"key ...{key[-4:]}" if key else ""
    if vendor == "azure":
        client_id = creds.get("client_id", "")
        return f"app {client_id[:8]}…" if client_id else ""
    if vendor == "gcp":
        try:
            parsed = json.loads(creds["service_account_json"])
            return parsed.get("client_email", "")
        except (ValueError, TypeError, KeyError):
            return "service account key"
    if vendor == "oci":
        user = creds.get("user_ocid", "")
        return f"user ...{user[-8:]}" if user else ""
    return ""


def encrypt_credentials(creds: dict) -> bytes:
    return secretsvc.encrypt(json.dumps(creds))


def decrypt_credentials(ciphertext: bytes) -> dict:
    return json.loads(secretsvc.decrypt(ciphertext))
