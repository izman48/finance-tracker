"""Integration tests for API endpoints."""


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Health endpoint should return healthy status."""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "healthy"


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_root_returns_message(self, client):
        """Root endpoint should return API info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "Finance Tracker API" in data["message"]


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_register_new_user(self, client, test_user_data):
        """Should register a new user successfully."""
        response = client.post("/api/v1/auth/register", json=test_user_data)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == test_user_data["email"]
        assert "id" in data
        assert "password" not in data  # Password should not be returned

    def test_register_short_password_rejected(self, client):
        """Should reject registration with a password shorter than 8 chars."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "shortpw@example.com", "password": "short"},
        )

        assert response.status_code == 422

    def test_register_duplicate_email(self, client, test_user_data):
        """Should reject duplicate email registration."""
        # First registration
        client.post("/api/v1/auth/register", json=test_user_data)

        # Second registration with same email
        response = client.post("/api/v1/auth/register", json=test_user_data)

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_login_valid_credentials(self, client, test_user_data):
        """Should login with valid credentials."""
        # Register first
        client.post("/api/v1/auth/register", json=test_user_data)

        # Login
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_password(self, client, test_user_data):
        """Should reject invalid password."""
        # Register first
        client.post("/api/v1/auth/register", json=test_user_data)

        # Login with wrong password
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": test_user_data["email"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        assert "Incorrect" in response.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """Should reject login for nonexistent user."""
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "somepassword",
            },
        )

        assert response.status_code == 401

    def test_get_current_user(self, authenticated_client):
        """Should return current user info when authenticated."""
        response = authenticated_client.get("/api/v1/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"

    def test_get_current_user_unauthenticated(self, client):
        """Should reject unauthenticated requests."""
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401
