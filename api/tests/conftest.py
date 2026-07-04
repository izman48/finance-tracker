import os

# Populate required settings before importing the app (config is read at import
# time). Sandbox + non-production keeps the live-mode secret guard disabled, so a
# throwaway key is fine here. os.environ takes precedence over any .env file.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "oGRxJNK_WkqVxoVJyfsMqY9qSjZQMZd_xJ706DSh62o=")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TRUELAYER_SANDBOX", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import user_crypto
from app.core.database import Base, get_db
from app.main import app


# In-memory SQLite for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _test_dek():
    """Give direct-DB test code a session DEK for user-encrypted columns.

    Only affects the test's own thread: TestClient requests run in a separate
    thread, where the DEK comes from the bearer token via set_session_dek —
    the same path as production.
    """
    token = user_crypto.current_dek.set(user_crypto.generate_dek())
    yield
    user_crypto.current_dek.reset(token)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database override."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    """Sample user data for tests."""
    return {
        "email": "test@example.com",
        "password": "securepassword123",
    }


@pytest.fixture
def authenticated_client(client, test_user_data):
    """Client with authenticated user."""
    # Register user
    client.post("/api/v1/auth/register", json=test_user_data)

    # Login to get token
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": test_user_data["email"],
            "password": test_user_data["password"],
        },
    )
    token = response.json()["access_token"]

    # Return client with auth header
    client.headers["Authorization"] = f"Bearer {token}"
    return client
