"""Public auth endpoints must throttle repeated attempts from one client.

Login runs an expensive Argon2 unwrap and forgot-password sends mail, so both
are worth abusing. The limiter is a single-process backstop (see
core/rate_limit.py); these tests pin the behaviour it is responsible for.
"""


def test_login_throttles_repeated_failures(client, test_user_data):
    client.post("/api/v1/auth/register", json=test_user_data)
    attempt = {"username": test_user_data["email"], "password": "wrong-password"}

    for _ in range(10):
        assert client.post("/api/v1/auth/login", data=attempt).status_code == 401

    blocked = client.post("/api/v1/auth/login", data=attempt)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]

    # The correct password is refused too — the limit is on the caller, so a
    # guessed credential can't be used the moment it is found.
    correct = client.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": test_user_data["password"]},
    )
    assert correct.status_code == 429


def test_forgot_password_is_throttled(client, test_user_data):
    client.post("/api/v1/auth/register", json=test_user_data)
    body = {"email": test_user_data["email"]}

    for _ in range(5):
        assert client.post("/api/v1/auth/forgot-password", json=body).status_code == 202

    assert client.post("/api/v1/auth/forgot-password", json=body).status_code == 429


def test_registration_is_throttled(client):
    for i in range(5):
        created = client.post(
            "/api/v1/auth/register",
            json={"email": f"user{i}@example.com", "password": "a-secure-password"},
        )
        assert created.status_code == 201

    blocked = client.post(
        "/api/v1/auth/register",
        json={"email": "user99@example.com", "password": "a-secure-password"},
    )
    assert blocked.status_code == 429
