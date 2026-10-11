"""Shapes the API's clients rely on, pinned across the FastAPI/Starlette bump
(T-08-19): the 401 and 422 bodies, the OAuth token endpoint's form errors,
and Starlette's urlencoded form limits now actually applying (PYSEC-2026-249).
"""
from urllib.parse import urlencode

API = "/api/v1"


def test_a_wrong_password_is_a_plain_401(client):
    client.post(f"{API}/auth/register", json={"email": "c@example.com", "password": "securepassword123"})
    r = client.post(f"{API}/auth/login", data={"username": "c@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    assert set(r.json()) == {"detail"} and isinstance(r.json()["detail"], str)
    assert r.headers["www-authenticate"] == "Bearer"


def test_a_validation_error_is_the_usual_422_list(client):
    r = client.post(f"{API}/auth/register", json={"email": "not-an-email", "password": "short"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail
    for item in detail:
        assert {"loc", "msg", "type"} <= set(item)
    assert {tuple(i["loc"]) for i in detail} >= {("body", "email"), ("body", "password")}


def test_an_unauthenticated_request_is_401_with_bearer(client):
    r = client.get(f"{API}/analytics/summary")
    assert r.status_code == 401
    assert set(r.json()) == {"detail"}


def test_the_token_endpoint_answers_oauth_errors_for_a_bad_form(client):
    r = client.post(f"{API}/oauth/token", data={"grant_type": "authorization_code"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_too_many_form_fields_are_refused_before_the_handler(client):
    """Starlette >=1.3.1 enforces max_fields on urlencoded bodies; before, a
    login form with thousands of fields was parsed in full."""
    body = urlencode([("username", "x@example.com"), ("password", "x")] + [(f"f{i}", "1") for i in range(2000)])
    r = client.post(f"{API}/auth/login", content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 400
