import logging
from typing import Annotated
from datetime import datetime, timedelta, timezone

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
from app.models import User
from app.schemas import (
    DeleteAccountRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.email_service import send_email
from app.services.truelayer import truelayer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Register a new user.
    
    Creates a new user account with email and password.
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
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    """
    Login to get access token.
    
    Uses OAuth2 password flow - send username (email) and password.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


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
            subject="Reset your Finance Tracker password",
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
    """Set a new password using a token from the reset email."""
    try:
        user = verify_password_reset_token(body.token, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user.hashed_password = get_password_hash(body.new_password)
    db.commit()
    logger.info(f"Password reset completed for user {user.id}")
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
    db.delete(current_user)
    db.commit()
    return {"message": "Account and all associated data deleted."}
