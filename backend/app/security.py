from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# Bcrypt directly rather than passlib's CryptContext: passlib 1.7.x's
# bcrypt backend probes `bcrypt.__about__`, which was removed in bcrypt 4.x,
# and misbehaves under that combination. bcrypt's own API is small enough
# not to need the wrapper.
_BCRYPT_MAX_BYTES = 72  # bcrypt's own input limit


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("utf-8"))


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None
