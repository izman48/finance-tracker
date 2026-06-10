"""Categorization rules and shareable rule packs."""
import logging
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import Account, CategoryRule, RulePack, Transaction
from app.schemas import (
    RuleCreate,
    RuleImportRequest,
    RulePackCreate,
    RulePackResponse,
    RulePackUpdate,
    RulePreviewRequest,
    RuleResponse,
    RuleUpdate,
)
from app.services import categorization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["rules"])


def _own_rule(db: Session, user_id, rule_id: str) -> CategoryRule:
    rule = (
        db.query(CategoryRule)
        .filter(CategoryRule.id == rule_id, CategoryRule.user_id == user_id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


def _own_pack(db: Session, user_id, pack_id: str) -> RulePack:
    pack = (
        db.query(RulePack)
        .filter(RulePack.id == pack_id, RulePack.user_id == user_id)
        .first()
    )
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack not found")
    return pack


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
@router.get("", response_model=dict)
def list_rules(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> dict:
    """All packs (with their rules) plus pack-less personal rules."""
    packs = (
        db.query(RulePack)
        .options(joinedload(RulePack.rules))
        .filter(RulePack.user_id == current_user.id)
        .order_by(RulePack.created_at)
        .all()
    )
    loose = (
        db.query(CategoryRule)
        .filter(CategoryRule.user_id == current_user.id, CategoryRule.pack_id.is_(None))
        .order_by(CategoryRule.created_at.desc())
        .all()
    )
    return {
        "packs": [RulePackResponse.model_validate(p).model_dump(mode="json") for p in packs],
        "personal": [RuleResponse.model_validate(r).model_dump(mode="json") for r in loose],
    }


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CategoryRule:
    error = categorization.validate_pattern(body.pattern, body.match_type)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    if body.pack_id:
        _own_pack(db, current_user.id, str(body.pack_id))

    rule = CategoryRule(
        user_id=current_user.id,
        pack_id=body.pack_id,
        pattern=body.pattern.strip(),
        match_type=body.match_type,
        match_field=body.match_field,
        category=body.category.strip(),
        source="manual",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
def update_rule(
    rule_id: str,
    body: RuleUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CategoryRule:
    rule = _own_rule(db, current_user.id, rule_id)
    if body.pattern is not None or body.match_type is not None:
        pattern = body.pattern if body.pattern is not None else rule.pattern
        match_type = body.match_type if body.match_type is not None else rule.match_type
        error = categorization.validate_pattern(pattern, match_type)
        if error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    for field in ("pattern", "match_type", "match_field", "category", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(rule, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    db.delete(_own_rule(db, current_user.id, rule_id))
    db.commit()
    return {"message": "Rule deleted"}


@router.post("/preview")
def preview_rule(
    body: RulePreviewRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Dry-run: how many of my transactions would this rule match?"""
    error = categorization.validate_pattern(body.pattern, body.match_type)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    probe = CategoryRule(
        user_id=current_user.id,
        pattern=body.pattern.strip(),
        match_type=body.match_type,
        match_field=body.match_field,
        category="",
        source="manual",
    )
    transactions = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == current_user.id)
        .all()
    )
    matches = [tx for tx in transactions if categorization._rule_matches(probe, tx)]
    return {
        "match_count": len(matches),
        "total_transactions": len(transactions),
        "samples": [
            {
                "merchant_name": tx.merchant_name,
                "description": tx.description,
                "category": tx.category,
            }
            for tx in matches[:5]
        ],
    }


@router.post("/apply")
def apply_rules_now(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Re-run all enabled rules over unlocked transactions."""
    changed = categorization.apply_rules_to_all(db, current_user.id)
    db.commit()
    return {"message": f"Recategorized {changed} transactions", "changed": changed}


# --------------------------------------------------------------------------- #
# Packs
# --------------------------------------------------------------------------- #
@router.post("/packs", response_model=RulePackResponse, status_code=status.HTTP_201_CREATED)
def create_pack(
    body: RulePackCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RulePack:
    pack = RulePack(user_id=current_user.id, name=body.name.strip(), description=body.description)
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


@router.patch("/packs/{pack_id}", response_model=RulePackResponse)
def update_pack(
    pack_id: str,
    body: RulePackUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RulePack:
    pack = _own_pack(db, current_user.id, pack_id)
    if body.name is not None:
        pack.name = body.name.strip()
    if body.description is not None:
        pack.description = body.description
    if body.enabled is not None:
        pack.enabled = body.enabled
    db.commit()
    db.refresh(pack)
    return pack


@router.delete("/packs/{pack_id}")
def delete_pack(
    pack_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    db.delete(_own_pack(db, current_user.id, pack_id))
    db.commit()
    return {"message": "Pack and its rules deleted"}


@router.post("/packs/{pack_id}/share")
def share_pack(
    pack_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Generate (or return) the pack's share code and import URL."""
    pack = _own_pack(db, current_user.id, pack_id)
    if not pack.share_code:
        pack.share_code = secrets.token_urlsafe(6)
        db.commit()
    return {
        "share_code": pack.share_code,
        "share_url": f"{get_settings().frontend_url}/r/{pack.share_code}",
    }


@router.delete("/packs/{pack_id}/share")
def unshare_pack(
    pack_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Revoke the share code — existing imports keep their copies."""
    pack = _own_pack(db, current_user.id, pack_id)
    pack.share_code = None
    db.commit()
    return {"message": "Sharing disabled"}


@router.get("/shared/{share_code}")
def preview_shared_pack(
    share_code: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """What a share link contains, before importing."""
    pack = (
        db.query(RulePack)
        .options(joinedload(RulePack.rules))
        .filter(RulePack.share_code == share_code)
        .first()
    )
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found or revoked")
    return {
        "name": pack.name,
        "description": pack.description,
        "rule_count": len(pack.rules),
        "rules": [
            {"pattern": r.pattern, "match_type": r.match_type, "category": r.category}
            for r in pack.rules
        ],
        "already_owned": pack.user_id == current_user.id,
    }


@router.post("/import", response_model=RulePackResponse, status_code=status.HTTP_201_CREATED)
def import_pack(
    body: RuleImportRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RulePack:
    """Copy a shared pack into my account (a snapshot I own and can edit)."""
    source = (
        db.query(RulePack)
        .options(joinedload(RulePack.rules))
        .filter(RulePack.share_code == body.share_code)
        .first()
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found or revoked")
    if source.user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This is already your pack")

    copy = RulePack(
        user_id=current_user.id,
        name=source.name,
        description=source.description,
        imported_from=source.name,
    )
    db.add(copy)
    db.flush()
    for r in source.rules:
        db.add(
            CategoryRule(
                user_id=current_user.id,
                pack_id=copy.id,
                pattern=r.pattern,
                match_type=r.match_type,
                match_field=r.match_field,
                category=r.category,
                source="imported",
                enabled=r.enabled,
            )
        )
    db.commit()
    db.refresh(copy)
    logger.info(f"User {current_user.id} imported pack {source.id} ({len(source.rules)} rules)")
    return copy
