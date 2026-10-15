# Sign-up, login, password and account

Users register with email and password, get a one-time recovery code, log in
to a JWT session, change or reset their password, and can delete their
account. How the password protects their data is in
[data-lifecycle.md](data-lifecycle.md).

## Code

**API** (`api/app/routers/auth.py`, all per-IP rate limited where noted by
`core/rate_limit.py`):

| Route | Auth | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | none | 5/hour. Provisions the user's data key (DEK); returns `recovery_code` once. |
| `POST /api/v1/auth/login` | none (OAuth2 password form) | 10/15 min, counted before the password check. Returns a JWT carrying `dk` (encrypted DEK) and `sv` (session version). Legacy users without a DEK get one here. |
| `GET /api/v1/auth/me` | `CurrentUser` | |
| `POST /api/v1/auth/change-password` | `CurrentUser` | Re-wraps the DEK, bumps `session_version` (logs out other sessions), returns a new token. No rate limit. |
| `POST /api/v1/auth/forgot-password` | none | 5/hour, always 202. Emails a 30-minute `pwd_reset` token link. |
| `POST /api/v1/auth/reset-password` | reset token | 10/15 min. With the recovery code the data survives; without it the key-loss purge runs. Always bumps `session_version`. |
| `POST /api/v1/auth/delete-account` | `CurrentUser` + password | Revokes each bank connection's access and refresh token at TrueLayer (best-effort), deletes bank connections, then the user; everything else goes by DB cascade. No rate limit. |

**Tables**: `users` (`email`, bcrypt `hashed_password`, wrapped DEKs,
`session_version`).

**Core**: `core/security.py` (bcrypt, JWT `typ` claims `access` /
`mcp_access` / `oauth_state` / `pwd_reset`, `get_current_user`,
`set_session_dek`), `core/user_crypto.py`, `core/rate_limit.py`,
`services/email_service.py` (SMTP; with no `SMTP_HOST` it logs the body only
outside live mode).

**UI**: `/login` (`LoginPage`, shows `RecoveryCodeCard`), `/register`
(`RegisterPage`), `/forgot-password` (`ForgotPasswordPage`),
`/reset-password` (`ResetPasswordPage`, warns before a purge),
`ChangePasswordModal` and `DeleteAccountModal` (user menu),
`hooks/useAuth.tsx` (token in `localStorage`, sync after login and on stale
resume).

**Tests**: `api/tests/integration/test_api.py`, `test_auth_rate_limit.py`,
`test_session_invalidation.py`, `test_user_encryption.py`;
`api/tests/unit/test_security.py`, `test_password_reset.py`,
`test_kdf_cost.py`, `test_rate_limit_sweep.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `users`; the root every user-owned table cascades from. |
| 2 Purge | The user row is kept by a purge; its wrapped DEKs are replaced. |
| 3 Deletion | This feature owns `delete-account`. See data-lifecycle.md. |
| 4 Demo mode | `GET /api/v1/auth/me` is served (sample user `you@sample.example`); login and register pass through. |
| 5 Ownership | n/a. |
| 6 Scopes | Web only; an MCP token gets 401 on every auth route (`test_oauth.py`). |
| 7 Claude tools | none, by design. |
| 8 Audit | n/a. |
| 9 Bank sync | `useAuth` syncs banks after login and when a resumed session is over 30 minutes stale. |
| 10 Home | Login lands on `/home`. |
| 11 UI routes | `/login`, `/register`, `/forgot-password`, `/reset-password`. |
| 12 Tests | listed above. |
| 13 Docs | README "Security" section. |

Gaps: rate limits on change-password and delete-account; reset copy omits
budgets. See [known-gaps.md](../known-gaps.md).
