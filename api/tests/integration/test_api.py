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


class TestCommitmentsEndpoint:
    """The GET that re-keys stale match_keys. It's a mutating read that writes a
    DEK-encrypted column, so it needs exercising over real HTTP with the token's
    own session key — a service-level call wouldn't catch a DEK failure here.
    """

    def _seed_loan_payments(self, client, db_session):
        """Register + login, then seed a regular loan DD whose reference changes
        every month, under the token's DEK (as production writes would be)."""
        import uuid as _uuid
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal

        from jose import jwt

        from app.core import user_crypto
        from app.core.config import get_settings
        from app.models import Account, BankConnection, Transaction, User

        email = "commitments@example.com"
        password = "securepassword123"
        client.post("/api/v1/auth/register", json={"email": email, "password": password})
        token = client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        dek = user_crypto.unwrap_session_dek(payload["dk"])
        user = db_session.query(User).filter(User.email == email).first()

        ctx = user_crypto.current_dek.set(dek)
        try:
            conn = BankConnection(
                user_id=user.id, provider_id="ob-loan", provider_name="Test Bank",
                access_token="t", refresh_token="r",
            )
            db_session.add(conn)
            db_session.flush()
            acc = Account(
                user_id=user.id, bank_connection_id=conn.id,
                external_id=f"ext-{_uuid.uuid4()}", provider_name="Test Bank",
                account_type="TRANSACTION", display_name="Current",
                current_balance=Decimal("1000"),
            )
            db_session.add(acc)
            db_session.commit()
            db_session.refresh(acc)

            today = datetime.now(timezone.utc)
            for i in range(4):
                db_session.add(Transaction(
                    account_id=acc.id, external_id=f"ext-loanpay-{i}",
                    transaction_type="debit", amount=Decimal("250.00"), currency="GBP",
                    description=f"LOAN PAYMENT REF {4471 + i}", merchant_name=None,
                    transaction_date=today - timedelta(days=30 * (3 - i)),
                ))
            db_session.commit()
        finally:
            user_crypto.current_dek.reset(ctx)

    def test_loan_payment_is_suggested_over_http(self, client, db_session):
        """The headline fix, end to end: a loan DD with a per-payment reference
        used to land in groups of one and never be suggested."""
        self._seed_loan_payments(client, db_session)

        response = client.get("/api/v1/analytics/commitments")

        assert response.status_code == 200
        labels = [c["label"].upper() for c in response.json()]
        assert any("LOAN PAYMENT" in label for label in labels), labels

    def test_repeat_call_does_not_duplicate(self, client, db_session):
        """sync_suggestions runs on every GET — re-keying must not make it
        re-suggest something it already stored."""
        self._seed_loan_payments(client, db_session)

        first = client.get("/api/v1/analytics/commitments").json()
        second = client.get("/api/v1/analytics/commitments").json()

        loans_first = [c for c in first if "LOAN PAYMENT" in c["label"].upper()]
        loans_second = [c for c in second if "LOAN PAYMENT" in c["label"].upper()]
        assert len(loans_first) == 1
        assert len(loans_second) == 1
        assert loans_first[0]["id"] == loans_second[0]["id"]
