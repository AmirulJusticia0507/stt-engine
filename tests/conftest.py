"""Pytest configuration and fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite:///./data/test_stt.db"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32chars"
os.environ["STT_MODEL"] = "tiny"
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASS"] = "admin"


@pytest.fixture(scope="session")
def test_db_path():
    """Provide test database path."""
    db_path = Path("./data/test_stt.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    yield db_path
    # Cleanup after tests
    if db_path.exists():
        db_path.unlink()


@pytest.fixture(scope="function")
def client(test_db_path):
    """Create test client with fresh database."""
    # Reset engine to use test database
    from app.auth import reset_engine
    reset_engine()

    from app.main import app
    with TestClient(app) as c:
        yield c

    # Cleanup
    reset_engine()


@pytest.fixture(scope="function")
def auth_token(client):
    """Get auth token for admin user."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture(scope="function")
def auth_headers(auth_token):
    """Auth headers with Bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}