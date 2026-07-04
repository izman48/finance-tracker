import logging
from typing import Annotated
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_password_reset_token,
    CurrentUser,
)
from app.core import user_crypto
from app.models import BankConnection, User
from app.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    RegisterResponse,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.email_service import send_email
from app.services.truelayer import truelayer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _provision_dek(user: User, password: str) -> str:
    """Create the user's DEK, wrapped under the password and a recovery code.

    Returns the recovery code — the only time it exists in plaintext.
    """
    dek = user_crypto.generate_dek()
    recovery_code = user_crypto.generate_recovery_code()
    user.dek_salt = user_crypto.generate_salt()
    user.recovery_salt = user_crypto.generate_salt()
    user.wrapped_dek = user_crypto.wrap_dek(dek, password, user.dek_salt)
    user.recovery_wrapped_dek = user_crypto.wrap_dek(
        dek, user_crypto.normalize_recovery_code(recovery_code), user.recovery_salt
    )
    return recovery_code


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> RegisterResponse:
    """
    Register a new user.

    Creates the account plus its data-encryption key, and returns the one-time
    recovery code. The code is shown exactly once: losing it and the password
    means the encrypted data cannot be recovered.
    """
    # Check if email already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
    )
    recovery_code = _provision_dek(user, user_data.password)
    db.add(user)
    db.commit()
    db.refresh(user)

    return RegisterResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
        recovery_code=recovery_code,
    )


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    """
    Login to get access token.

    Uses OAuth2 password flow - send username (email) and password. Unwraps
    the user's data-encryption key with the password-derived KEK and carries
    it in the token (`dk` claim) — the only window where the server holds it.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    recovery_code: str | None = None
    if user.wrapped_dek is None:
        # Account predates per-user encryption: provision its DEK now, while
        # the password is in hand, and hand back the one-time recovery code.
        recovery_code = _provision_dek(user, form_data.password)
        db.commit()
        logger.info(f"Provisioned data-encryption key for existing user {user.id}")

    try:
        dek = user_crypto.unwrap_dek(user.wrapped_dek, form_data.password, user.dek_salt)
    except InvalidToken:
        # Password verified but can't unwrap: key material is corrupt/desynced.
        logger.error(f"DEK unwrap failed for user {user.id} despite valid password")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not unlock your encrypted data. Contact support.",
        )

    access_token = create_access_token(data={"sub": str(user.id)}, dek=dek)
    return Token(access_token=access_token, recovery_code=recovery_code)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Change password while authenticated.

    The DEK is unwrapped with the old password and rewrapped with the new one,
    so encrypted data (and the recovery code) survive unchanged.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect current password",
        )

    if current_user.wrapped_dek is None:
        # Session predates per-user encryption; a fresh login provisions the key.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in again before changing your password.",
        )

    try:
        dek = user_crypto.unwrap_dek(
            current_user.wrapped_dek, body.current_password, current_user.dek_salt
        )
    except InvalidToken:
        logger.error(f"DEK unwrap failed for user {current_user.id} on password change")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not unlock your encrypted data. Contact support.",
        )

    current_user.hashed_password = get_password_hash(body.new_password)
    current_user.dek_salt = user_crypto.generate_salt()
    current_user.wrapped_dek = user_crypto.wrap_dek(
        dek, body.new_password, current_user.dek_salt
    )
    db.commit()
    logger.info(f"Password changed (DEK rewrapped) for user {current_user.id}")
    return {"message": "Password updated."}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: CurrentUser) -> User:
    """
    Get current user information.

    Requires authentication.
    """
    return current_user


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Email a password reset link.

    Always returns 202 so the endpoint can't be used to probe which emails
    have accounts.
    """
    user = db.query(User).filter(User.email == body.email).first()
    if user:
        token = create_password_reset_token(user)
        reset_url = f"{get_settings().frontend_url}/reset-password?token={token}"
        send_email(
            to=user.email,
            subject="Reset your nilu. password",
            body=(
                "Someone (hopefully you) requested a password reset.\n\n"
                f"Reset it here (link valid for 30 minutes):\n{reset_url}\n\n"
                "If this wasn't you, ignore this email — your password is unchanged."
            ),
        )
    return {"message": "If that email has an account, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Set a new password using a token from the reset email.

    With the recovery code, the data-encryption key is rewrapped and all data
    survives. Without it the key is unrecoverable by design: a fresh DEK (and
    recovery code) is issued and the now-unreadable bank data is purged — the
    user rebuilds it by reconnecting/re-syncing their banks.
    """
    try:
        user = verify_password_reset_token(body.token, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    new_recovery_code: str | None = None
    if user.wrapped_dek is not None and body.recovery_code:
        try:
            dek = user_crypto.unwrap_dek(
                user.recovery_wrapped_dek,
                user_crypto.normalize_recovery_code(body.recovery_code),
                user.recovery_salt,
            )
        except InvalidToken:
            # Don't consume the reset token on a typo'd recovery code.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recovery code is incorrect.",
            )
        user.dek_salt = user_crypto.generate_salt()
        user.wrapped_dek = user_crypto.wrap_dek(dek, body.new_password, user.dek_salt)
    else:
        # No recovery code: the old DEK is gone. Purge the encrypted bank data
        # (bulk deletes — DB-level cascades remove accounts and transactions
        # without loading the undecryptable rows) and start a fresh key.
        db.query(BankConnection).filter(BankConnection.user_id == user.id).delete(
            synchronize_session=False
        )
        new_recovery_code = _provision_dek(user, body.new_password)
        logger.info(f"Password reset without recovery code for user {user.id}: bank data purged, new DEK issued")

    user.hashed_password = get_password_hash(body.new_password)
    db.commit()
    logger.info(f"Password reset completed for user {user.id}")
    if new_recovery_code:
        return {
            "message": "Password updated. Your bank data was cleared — reconnect your bank to rebuild it.",
            "recovery_code": new_recovery_code,
        }
    return {"message": "Password updated. You can now log in."}


@router.post("/delete-account")
def delete_account(
    body: DeleteAccountRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Permanently delete the account and all its data.

    Requires the current password as confirmation. Accounts, transactions,
    bank connections (tokens), commitments and planned items all cascade.
    """
    if not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password",
        )

    logger.info(f"Deleting account and all data for user {current_user.id}")
    # Bulk-delete bank connections first (DB cascades remove accounts and
    # transactions) so the ORM cascade never loads encrypted rows — deletion
    # must work even without a session DEK.
    db.query(BankConnection).filter(BankConnection.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.delete(current_user)
    db.commit()
    return {"message": "Account and all associated data deleted."}
