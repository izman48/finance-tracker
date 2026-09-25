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


# Production: Caddy at a pinned address, uvicorn --forwarded-allow-ips=<it>
# (docker-compose.prod.yml). Build the same stack in-process: uvicorn's proxy
# middleware in front of the app, and TestClient's `client` as the TCP peer.
PROXY_IP = "172.30.250.10"


def _peer(app, host):
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts=PROXY_IP), client=(host, 40000))


def _exhaust_login(http, email, headers=None):
    attempt = {"username": email, "password": "wrong-password"}
    for _ in range(10):
        assert http.post("/api/v1/auth/login", data=attempt, headers=headers).status_code == 401
    assert http.post("/api/v1/auth/login", data=attempt, headers=headers).status_code == 429


def test_clients_behind_the_proxy_get_independent_budgets(client, test_user_data):
    client.post("/api/v1/auth/register", json=test_user_data)
    proxy = _peer(client.app, PROXY_IP)

    _exhaust_login(proxy, test_user_data["email"], headers={"X-Forwarded-For": "203.0.113.7"})

    # A different caller arriving through the same proxy is unaffected.
    other = proxy.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": test_user_data["password"]},
        headers={"X-Forwarded-For": "198.51.100.23"},
    )
    assert other.status_code == 200


def test_direct_callers_cannot_choose_their_identity(client, test_user_data):
    client.post("/api/v1/auth/register", json=test_user_data)
    attacker = _peer(client.app, "192.0.2.50")

    _exhaust_login(attacker, test_user_data["email"], headers={"X-Forwarded-For": "203.0.113.1"})

    # Not the trusted proxy, so a fresh forwarded address buys nothing.
    retry = attacker.post(
        "/api/v1/auth/login",
        data={"username": test_user_data["email"], "password": "wrong-password"},
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    assert retry.status_code == 429
