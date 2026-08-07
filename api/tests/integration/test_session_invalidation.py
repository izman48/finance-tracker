"""Credentials changes must immediately invalidate already-issued sessions."""
from app.core.security import create_password_reset_token
from app.models import User


def test_change_password_revokes_other_sessions(client, test_user_data):
    client.post("/api/v1/auth/register", json=test_user_data)
    first = client.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": test_user_data["password"]},
    ).json()["access_token"]
    second = client.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": test_user_data["password"]},
    ).json()["access_token"]

    client.headers["Authorization"] = f"Bearer {first}"
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": test_user_data["password"], "new_password": "another-secure-password"},
    )
    assert changed.status_code == 200
    replacement = changed.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {second}"
    assert client.get("/api/v1/auth/me").status_code == 401

    client.headers["Authorization"] = f"Bearer {replacement}"
    assert client.get("/api/v1/auth/me").status_code == 200


def test_password_reset_revokes_existing_sessions(client, db_session, test_user_data):
    """The theft case reset exists for: the attacker's stolen bearer token must
    stop working the moment the owner resets, without waiting for it to expire."""
    client.post("/api/v1/auth/register", json=test_user_data)
    stolen = client.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": test_user_data["password"]},
    ).json()["access_token"]

    client.headers["Authorization"] = f"Bearer {stolen}"
    assert client.get("/api/v1/auth/me").status_code == 200

    user = db_session.query(User).filter(User.email == test_user_data["email"]).first()
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"token": create_password_reset_token(user), "new_password": "a-brand-new-password"},
    )
    assert reset.status_code == 200

    assert client.get("/api/v1/auth/me").status_code == 401
