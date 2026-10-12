"""TrueLayer Open Banking API service."""
import logging
from typing import Any
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.psu_ip import current_psu_ip
from app.core.security import create_oauth_state
from app.models import User, Account, Transaction, BankConnection
from app.services.categorization import category_from_provider

settings = get_settings()
logger = logging.getLogger(__name__)

# httpx logs each request's full URL at INFO, which names the provider's
# account and card ids and the query (sec, T-08-24): keep it to warnings.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Every TrueLayer call is bounded (T-08-22, sec): a sync runs inside the
# request, under the sync lease and the MCP client's wait.
TRUELAYER_TIMEOUT_SECONDS = 10
TRUELAYER_TIMEOUT = httpx.Timeout(TRUELAYER_TIMEOUT_SECONDS)
# A transactions fetch can be slow (Amex took over 10 s, T-08-27): it alone
# gets longer. The sync budget and start margin are sized for it (banking.py).
TRANSACTIONS_TIMEOUT_SECONDS = 25
TRANSACTIONS_TIMEOUT = httpx.Timeout(TRANSACTIONS_TIMEOUT_SECONDS)
# The fallback window after a 403 on a longer fetch: Monzo serves only the
# last 90 days of its own (UK) date once consent is a few minutes old.
# Counted from the Europe/London date, with two days' margin (sec on #141:
# from the UTC date, 89 days landed on day 90 between 00:00 and 01:00 BST).
FALLBACK_DAYS = 88
BANK_TZ = ZoneInfo("Europe/London")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fallback_from() -> datetime:
    """Midnight, London time, FALLBACK_DAYS before today's London date."""
    bank_today = _utcnow().astimezone(BANK_TZ).date()
    return datetime.combine(bank_today - timedelta(days=FALLBACK_DAYS), time.min, tzinfo=BANK_TZ)


def _data_headers(access_token: str) -> dict[str, str]:
    """Headers for a TrueLayer data call. X-PSU-IP only while the user is
    present (a sync they started in the web app, T-08-22); never logged."""
    headers = {"Authorization": f"Bearer {access_token}"}
    ip = current_psu_ip.get()
    if ip:
        headers["X-PSU-IP"] = ip
    return headers


def _status_and_code(e: httpx.HTTPStatusError) -> str:
    """The HTTP status and TrueLayer's `error` code: never the body, URL or tokens."""
    try:
        code = e.response.json().get("error")
    except Exception:
        code = None
    return f"{e.response.status_code} {code}" if isinstance(code, str) and code.isidentifier() else str(e.response.status_code)


def _describe(e: Exception) -> str:
    """For a log line: the HTTP status and TrueLayer's error code, or the
    exception type. Never its text, a URL, a body or a token."""
    return _status_and_code(e) if isinstance(e, httpx.HTTPStatusError) else type(e).__name__


def _not_offered(e: Exception) -> bool:
    """501: the bank doesn't offer this endpoint via TrueLayer."""
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 501


def _log_skip(e: Exception, account) -> None:
    """One account skipped, by the caller's own internal ids only (sec,
    T-08-24). A 501 is the bank not offering it (Revolut card transactions
    via TrueLayer): expected, so quiet."""
    quiet = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 501
    logger.log(
        logging.INFO if quiet else logging.WARNING,
        "Skipped an account's transactions: account %s, connection %s, %s %s",
        account.id, account.bank_connection_id, account.provider_name, _describe(e),
    )


class TrueLayerError(Exception):
    """A TrueLayer call failed. The message names TrueLayer's error code only;
    it never carries tokens, secrets, or response bodies. `status` and `code`
    (TrueLayer's `error`) are safe to log (T-08-27)."""

    def __init__(self, message: str = "", status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status, self.code = status, code


class ReauthRequired(TrueLayerError):
    """The connection's consent has lapsed or been revoked, so its refresh
    token can never work again. Only the user reconnecting the bank fixes it."""


class TrueLayerService:
    """Service for interacting with TrueLayer Open Banking API."""

    def __init__(self):
        self.client_id = settings.truelayer_client_id
        self.client_secret = settings.truelayer_client_secret
        self.redirect_uri = settings.truelayer_redirect_uri
        self.auth_url = settings.truelayer_auth_url
        self.api_url = settings.truelayer_api_url

    def get_auth_link(self, user_id: str, dek: bytes, provider_id: str | None = None) -> str:
        """
        Generate TrueLayer OAuth authorization URL.

        Args:
            user_id: The user ID to include in state parameter
            dek: The session data-encryption key, carried (server-encrypted)
                 in the state token so the callback can encrypt what it stores
            provider_id: Pre-select this bank, skipping TrueLayer's bank picker
                 (used to reconnect an existing connection)

        Returns:
            Authorization URL for the user to visit
        """
        # Permissions we're requesting (matching TrueLayer auth link builder)
        scopes = [
            "accounts",
            "balance",
            "cards",
            "direct_debits",
            "info",
            "offline_access",  # For refresh tokens
            "standing_orders",
            "transactions",
        ]

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": " ".join(scopes),
            "redirect_uri": self.redirect_uri,
            # Signed, short-lived state token (CSRF protection + hides user_id)
            "state": create_oauth_state(user_id, dek),
            "providers": "uk-ob-all uk-oauth-all",  # Live mode: removed uk-cs-mock
        }
        if provider_id and provider_id != "unknown":
            params["provider_id"] = provider_id

        query_string = urlencode(params)
        return f"{self.auth_url}?{query_string}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback

        Returns:
            Token response with access_token, refresh_token, expires_in
        """
        return await self._token_request({
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code": code,
        })

    async def refresh_access_token(self, refresh_token: str | None) -> dict[str, Any]:
        """
        Refresh an expired access token.

        Args:
            refresh_token: The refresh token

        Returns:
            New token response

        Raises:
            ReauthRequired: there is no refresh token, or TrueLayer rejected it
                (consent expired or revoked) — the user must reconnect.
            TrueLayerError: any other token endpoint failure.
        """
        if not refresh_token:
            raise ReauthRequired("No refresh token; the bank must be reconnected")
        return await self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    async def _token_request(self, grant: dict[str, str]) -> dict[str, Any]:
        """POST a grant to the token endpoint, translating OAuth errors.

        TrueLayer answers a refresh token it will never accept again (consent
        lapsed after 90 days, or revoked at the bank) with 400 invalid_grant.
        """
        async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
            response = await client.post(
                f"{self.auth_url}/connect/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    **grant,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.is_success:
            return response.json()

        try:
            error_code = str(response.json().get("error", "unknown_error"))
        except ValueError:
            error_code = "unknown_error"
        logger.warning(
            f"TrueLayer token request ({grant['grant_type']}) failed: "
            f"{response.status_code} {error_code}"
        )
        if error_code == "invalid_grant" and grant["grant_type"] == "refresh_token":
            raise ReauthRequired("Bank consent has expired or was revoked")
        raise TrueLayerError(
            f"TrueLayer token request failed ({response.status_code} {error_code})",
            status=response.status_code, code=error_code if error_code.isidentifier() else None,
        )

    async def _ensure_fresh_token(self, bank_connection: BankConnection, db: Session) -> None:
        """Refresh the connection's access token if it has expired.

        On ReauthRequired the dead refresh token is dropped (it can never work
        again, so keeping it only risks a leak) and the error re-raised; the
        connection then reports as needing reconnection and later syncs fail
        fast without calling TrueLayer.
        """
        if not bank_connection.access_token_expired:
            return

        logger.info(f"Refreshing expired token for bank connection {bank_connection.id}")
        tried = bank_connection.refresh_token
        try:
            token_data = await self.refresh_access_token(tried)
        except ReauthRequired:
            # Drop only the token TrueLayer rejected: if another sync rotated
            # it meanwhile, the new one is good (T-08-22, sec).
            db.refresh(bank_connection)
            if bank_connection.refresh_token is not None and bank_connection.refresh_token == tried:
                bank_connection.refresh_token = None
                db.commit()
            raise

        bank_connection.access_token = token_data["access_token"]
        bank_connection.refresh_token = token_data.get("refresh_token")
        bank_connection.token_expires_at = datetime.now(
            timezone.utc
        ) + timedelta(seconds=token_data["expires_in"])
        db.commit()

    async def get_provider_info(self, access_token: str) -> dict[str, Any]:
        """
        Get provider information from the access token.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            Provider information including provider_id and display_name
        """
        unknown = {"provider_id": "unknown", "display_name": "Unknown Bank"}

        async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
            # Try accounts first (most banks), then cards (AMEX/credit cards).
            for endpoint in ("accounts", "cards"):
                try:
                    response = await client.get(
                        f"{self.api_url}/data/v1/{endpoint}",
                        headers=_data_headers(access_token),
                    )
                    response.raise_for_status()
                    results = response.json().get("results", [])
                    if results:
                        provider = results[0].get("provider", {})
                        provider_id = provider.get("provider_id", "unknown")
                        if provider_id != "unknown":
                            logger.info(f"Resolved provider from {endpoint}: {provider_id}")
                            return {
                                "provider_id": provider_id,
                                "display_name": provider.get("display_name", "Unknown Bank"),
                            }
                except Exception as e:
                    logger.warning(f"Provider lookup via {endpoint} failed: {type(e).__name__}")

            logger.info("Could not resolve provider info; using defaults")
            return unknown

    async def revoke_token(self, token: str) -> None:
        """Revoke an access/refresh token at TrueLayer (best-effort).

        Called on disconnect so a deleted connection's token can no longer be
        used to reach the user's bank data. Failures are logged, not raised.
        """
        try:
            async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
                response = await client.post(
                    f"{self.auth_url}/connect/token/revoke",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "token": token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                logger.info("Revoked TrueLayer token on disconnect")
        except Exception as e:
            logger.warning(f"Token revocation failed (continuing): {type(e).__name__}")

    async def get_accounts(self, access_token: str) -> list[dict[str, Any]]:
        """
        Fetch all accounts from TrueLayer.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            List of account data
        """
        async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
            logger.info(f"Fetching accounts from {self.api_url}/data/v1/accounts")
            response = await client.get(
                f"{self.api_url}/data/v1/accounts",
                headers=_data_headers(access_token),
            )
            logger.info(f"Accounts response status: {response.status_code}")
            # Never the body (sec, T-08-24): it can carry provider detail.
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    async def get_cards(self, access_token: str) -> list[dict[str, Any]]:
        """
        Fetch all cards from TrueLayer.

        Args:
            access_token: Valid TrueLayer access token

        Returns:
            List of card data (formatted to look like accounts)
        """
        async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
            logger.info(f"Fetching cards from {self.api_url}/data/v1/cards")
            response = await client.get(
                f"{self.api_url}/data/v1/cards",
                headers=_data_headers(access_token),
            )
            logger.info(f"Cards response status: {response.status_code}")
            # Never the body (sec, T-08-24): it can carry provider detail.
            response.raise_for_status()
            data = response.json()
            # Format cards to look like accounts for compatibility
            cards = data.get("results", [])
            formatted_cards = []
            for card in cards:
                # Map card_type to account_type
                card_type = card.get("card_type", "CREDIT")
                if card_type == "CREDIT":
                    account_type = "CREDIT_CARD"
                elif card_type == "DEBIT":
                    account_type = "TRANSACTION"  # Debit cards are like transaction accounts
                else:
                    account_type = "OTHER"

                formatted_cards.append({
                    "account_id": card["account_id"],
                    "display_name": card.get("display_name", "Unknown Card"),
                    "account_type": account_type,
                    "currency": card.get("currency", "GBP"),
                    "card_network": card.get("card_network"),  # AMEX, VISA, etc.
                    "partial_card_number": card.get("partial_card_number"),
                })
            return formatted_cards

    async def get_account_balance(
        self, access_token: str, account_id: str
    ) -> dict[str, Any]:
        """
        Fetch balance for a specific account or card.

        Args:
            access_token: Valid TrueLayer access token
            account_id: TrueLayer account/card ID

        Returns:
            Balance data
        """
        async with httpx.AsyncClient(timeout=TRUELAYER_TIMEOUT) as client:
            # Try account balance first
            try:
                response = await client.get(
                    f"{self.api_url}/data/v1/accounts/{account_id}/balance",
                    headers=_data_headers(access_token),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [{}])[0]
            except Exception as e:
                logger.info("Account balance failed (%s), trying card balance", type(e).__name__)
                # Try card balance as fallback
                response = await client.get(
                    f"{self.api_url}/data/v1/cards/{account_id}/balance",
                    headers=_data_headers(access_token),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [{}])[0]

    async def get_transactions(
        self,
        access_token: str,
        account_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch transactions for an account or card.

        Args:
            access_token: Valid TrueLayer access token
            account_id: TrueLayer account/card ID
            from_date: Start date for transactions (default: 90 days ago)
            to_date: End date for transactions (default: now)

        Returns:
            List of transaction data
        """
        if from_date is None:
            from_date = datetime.now(timezone.utc) - timedelta(days=90)
        if to_date is None:
            to_date = datetime.now(timezone.utc)

        params = {
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
        }

        async with httpx.AsyncClient(timeout=TRANSACTIONS_TIMEOUT) as client:
            # Try account transactions first
            try:
                response = await client.get(
                    f"{self.api_url}/data/v1/accounts/{account_id}/transactions",
                    headers=_data_headers(access_token),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
            except Exception as e:
                logger.info("Account transactions failed (%s), trying card transactions", type(e).__name__)
                # Try card transactions as fallback
                response = await client.get(
                    f"{self.api_url}/data/v1/cards/{account_id}/transactions",
                    headers=_data_headers(access_token),
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])

    async def sync_accounts(self, bank_connection: BankConnection, db: Session, skip_token_refresh: bool = False) -> list[Account]:
        """
        Sync accounts from TrueLayer to database.

        Args:
            bank_connection: BankConnection object with TrueLayer tokens
            db: Database session
            skip_token_refresh: If True, skip automatic token refresh (for initial historical sync)

        Returns:
            List of synced Account objects
        """
        if not bank_connection.access_token:
            raise ValueError("Bank connection has no access token")

        # Check if token is expired and refresh if needed
        # IMPORTANT: Skip refresh during initial historical data sync (SCA requirement)
        if not skip_token_refresh:
            await self._ensure_fresh_token(bank_connection, db)

        # Fetch accounts from TrueLayer (try both accounts and cards endpoints)
        tl_accounts = []

        # Try to fetch regular accounts
        try:
            tl_accounts = await self.get_accounts(bank_connection.access_token)
            logger.info(f"Fetched {len(tl_accounts)} accounts")
        except Exception as e:
            logger.warning("Failed to fetch accounts for connection %s: %s", bank_connection.id, _describe(e))

        # Try to fetch cards (for AMEX, etc.)
        try:
            tl_cards = await self.get_cards(bank_connection.access_token)
            logger.info(f"Fetched {len(tl_cards)} cards")
            tl_accounts.extend(tl_cards)  # Add cards to the accounts list
        except Exception as e:
            logger.warning("Failed to fetch cards for connection %s: %s", bank_connection.id, _describe(e))

        if not tl_accounts:
            raise ValueError("No accounts or cards found for this connection")

        synced_accounts = []
        for tl_account in tl_accounts:
            # Try to get balance (may not work for cards)
            balance_data = None
            try:
                balance_data = await self.get_account_balance(
                    bank_connection.access_token, tl_account["account_id"]
                )
            except Exception as e:
                logger.warning("Could not fetch a balance for connection %s: %s", bank_connection.id, _describe(e))

            # Check if account already exists. Scoped to this user: another
            # user's row can't be decrypted with (or re-encrypted under) this
            # session's key.
            account = (
                db.query(Account)
                .filter(
                    Account.external_id == tl_account["account_id"],
                    Account.user_id == bank_connection.user_id,
                )
                .first()
            )

            if account:
                # Update existing account
                account.display_name = tl_account.get("display_name", "Unknown")
                account.account_type = tl_account.get("account_type", "TRANSACTION")
                account.currency = tl_account.get("currency", "GBP")
                # Fail safe (sec, T-08-24): a balance the bank didn't give
                # keeps the last one and stays stale; never zeroed or dropped,
                # which would understate a card's debt.
                if balance_data is not None:
                    account.current_balance = balance_data.get("current")
                    account.available_balance = balance_data.get("available")
                    account.balance_updated_at = datetime.now(timezone.utc)
            else:
                # Create new account
                account = Account(
                    user_id=bank_connection.user_id,
                    bank_connection_id=bank_connection.id,
                    external_id=tl_account["account_id"],
                    provider_name=bank_connection.provider_name,
                    account_type=tl_account.get("account_type", "TRANSACTION"),
                    display_name=tl_account.get("display_name", "Unknown"),
                    currency=tl_account.get("currency", "GBP"),
                    current_balance=(balance_data or {}).get("current"),
                    available_balance=(balance_data or {}).get("available"),
                    balance_updated_at=datetime.now(timezone.utc) if balance_data is not None else None,
                )
                db.add(account)

            synced_accounts.append(account)

        db.commit()
        return synced_accounts

    async def sync_transactions(
        self, bank_connection: BankConnection, db: Session, days: int = 90, skip_token_refresh: bool = False,
        report: dict | None = None,
    ) -> int:
        """
        Sync transactions from TrueLayer to database.

        Args:
            bank_connection: BankConnection object with TrueLayer tokens
            db: Database session
            days: Number of days to fetch (default: 90)
            skip_token_refresh: If True, skip automatic token refresh (for initial historical sync)
            report: if given, gets "accounts_skipped": accounts whose
                transactions couldn't be fetched (T-08-24)

        Each account is fetched on its own: one that fails is skipped and the
        rest still sync. Raises TrueLayerError only if every account failed.

        Returns:
            Number of new transactions synced
        """
        if not bank_connection.access_token:
            raise ValueError("Bank connection has no access token")

        # IMPORTANT: Skip refresh during initial historical data sync (SCA requirement)
        if not skip_token_refresh:
            await self._ensure_fresh_token(bank_connection, db)

        # Get all accounts for this bank connection
        accounts = db.query(Account).filter(Account.bank_connection_id == bank_connection.id).all()

        if not accounts:
            logger.warning(f"No accounts found for bank connection {bank_connection.id}")
            return 0

        from_date = datetime.now(timezone.utc) - timedelta(days=days)
        to_date = datetime.now(timezone.utc)
        new_count = 0
        new_transactions: list[Transaction] = []

        logger.info(f"Syncing transactions from {from_date.date()} to {to_date.date()} ({days} days)")

        skipped = 0
        failures: list[Exception] = []
        for account in accounts:
            # One account's endpoint failing (Monzo cards 403, Revolut cards
            # 501, a timeout) must not stop the others (T-08-24).
            try:
                tl_transactions = await self._account_transactions(bank_connection, account, days, from_date)
            except Exception as e:
                skipped += 1
                _log_skip(e, account)
                if not _not_offered(e):
                    failures.append(e)
                continue

            for tl_tx in tl_transactions:
                # Dedupe on external_id. Select only the id: loading the full
                # row would decrypt its user-encrypted columns, which fails if
                # the id collides with a row owned by another user.
                existing = (
                    db.query(Transaction.id)
                    .filter(Transaction.external_id == tl_tx["transaction_id"])
                    .first()
                )

                if existing:
                    continue  # Skip existing transactions

                # Create new transaction
                # Convert TrueLayer's uppercase transaction_type to our lowercase enum
                tx_type = tl_tx.get("transaction_type", "DEBIT").lower()

                transaction = Transaction(
                    account_id=account.id,
                    external_id=tl_tx["transaction_id"],
                    transaction_type=tx_type,
                    amount=abs(float(tl_tx["amount"])),
                    currency=tl_tx.get("currency", "GBP"),
                    description=tl_tx.get("description", ""),
                    merchant_name=tl_tx.get("merchant_name"),
                    category=category_from_provider(tl_tx.get("transaction_category"), tx_type),
                    transaction_date=datetime.fromisoformat(
                        tl_tx["timestamp"].replace("Z", "+00:00")
                    ),
                )
                db.add(transaction)
                new_transactions.append(transaction)
                new_count += 1
            # Committed per account (sec, T-08-24): a later account's failure
            # can't roll back one that synced.
            db.commit()

        # User-defined rules beat TrueLayer's generic categories.
        if new_transactions:
            from app.services import categorization

            categorization.apply_rules(db, bank_connection.user_id, new_transactions)

        # Every account failed: the connection failed. An account the bank
        # doesn't offer transactions for (501, Revolut) isn't a failure, so a
        # bank that offers none still syncs (T-08-27).
        if skipped == len(accounts) and failures:
            db.rollback()
            first = failures[0]
            if isinstance(first, httpx.HTTPStatusError):
                status, code = first.response.status_code, _status_and_code(first).partition(" ")[2] or None
            else:
                status, code = None, type(first).__name__
            raise TrueLayerError("transactions failed for every account", status=status, code=code)
        bank_connection.last_synced_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Synced {new_count} new transactions for bank connection {bank_connection.id}")
        if report is not None:
            report["accounts_skipped"] = skipped
        return new_count

    async def _account_transactions(self, bank_connection: BankConnection, account, days: int, from_date) -> list:
        """One account's transactions. The requested window first; only after
        a 403 (Monzo's "outside the last 90 days"), FALLBACK_DAYS from the
        London date (T-08-24). Any other failure isn't retried: a shorter
        window can't fix it, and each try spends the bank's quota (sec)."""
        token, ext = bank_connection.access_token, account.external_id
        if days <= FALLBACK_DAYS:
            return await self.get_transactions(token, ext, from_date=from_date)
        try:
            return await self.get_transactions(token, ext, from_date=from_date)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 403:
                raise
            logger.warning("Failed to fetch %s days (%s), trying %s", days, _status_and_code(e), FALLBACK_DAYS)
        return await self.get_transactions(token, ext, from_date=_fallback_from())


# Singleton instance
truelayer_service = TrueLayerService()
