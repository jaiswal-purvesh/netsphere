from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://netsphere:netsphere@localhost:5432/netsphere_test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - registers models on Base.metadata
from app.config import settings
from app.db import Base, get_db
from app.core.rbac_seed import ALL_PERMISSION_CODES, ROLE_GRANTS
from app.main import app
from app.models.user import ALL_ROLES, Permission, Role, User
from app.security import create_access_token, hash_password

engine = create_engine(settings.database_url, future=True)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_rbac(db):
    perms = {}
    for code in ALL_PERMISSION_CODES:
        p = Permission(code=code)
        db.add(p)
        perms[code] = p
    db.commit()

    roles = {}
    for name in ALL_ROLES:
        r = Role(name=name)
        db.add(r)
        roles[name] = r
    db.commit()

    for role_name, codes in ROLE_GRANTS.items():
        for code in codes:
            roles[role_name].permissions.append(perms[code])
    db.commit()
    return roles


@pytest.fixture()
def auth_headers_factory(db_session):
    roles = _seed_rbac(db_session)

    def _make(role_name: str, email: str | None = None):
        email = email or f"{role_name.lower()}@test.local"
        user = User(email=email, full_name=role_name, hashed_password=hash_password("x"), is_active=True)
        if role_name in roles:
            user.roles.append(roles[role_name])
        db_session.add(user)
        db_session.commit()
        token = create_access_token(user.email)
        return {"Authorization": f"Bearer {token}"}, user

    return _make


@pytest.fixture()
def admin_headers(auth_headers_factory):
    headers, _ = auth_headers_factory("SUPER_ADMIN")
    return headers
