"""Claude's edits to existing categorisation rules over MCP.

Every route takes `RulesEditor` (the finance:rules.edit scope, and the
per-user write limits shared with every other Claude write) and goes through
the planning-write framework: dry_run by default, idempotency, an encrypted
audit row (`target_kind: "rule"`), web-only undo. Only the matching fields
in `TARGETS["rule"]` change. A rule is addressed by its id, never by its
pattern (untrusted text). Switching a rule off is `enabled: false`, never a
delete, so the change can be undone. An applied edit re-runs the rules over
the user's history, as an undo does.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.planning_write import RulesEditor
from app.models import CategoryRule
from app.schemas import ClaudeRuleUpdateRequest
from app.services import categorization
from app.services.planning_writes import WriteRequest, replay_if_applied, run_write

router = APIRouter(prefix="/planning/rules", tags=["planning"])

_EDITABLE = ("pattern", "match_type", "match_field", "category", "counts_as", "enabled")


@router.post("/{rule_id}/update")
def update_rule(rule_id: uuid.UUID, body: ClaudeRuleUpdateRequest, caller: RulesEditor,
                db: Annotated[Session, Depends(get_db)]) -> dict:
    """Change one of the user's rules. Fields left out are unchanged. The
    pattern is checked with the match type it will run under (the new one,
    or the stored one), so no edit can store a pattern the engine can't run.
    Another user's rule, or an unknown id: 404."""
    sent = {f: getattr(body, f) for f in _EDITABLE if f in body.model_fields_set}
    if "category" in sent:
        sent["category"] = sent["category"].strip()
    if "pattern" in sent:
        sent["pattern"] = sent["pattern"].strip()

    def apply(db: Session, rule: CategoryRule) -> CategoryRule:
        for field, value in sent.items():
            setattr(rule, field, value)
        return rule

    req = WriteRequest(tool="update_rule", target_kind="rule", target_id=rule_id, apply=apply)
    replay = replay_if_applied(db, caller, req, body)
    if replay is not None:
        # A retry of an edit that already applied: its backfill already ran.
        return {**replay, "transactions_recategorized": 0}

    rule = (
        db.query(CategoryRule)
        .filter(CategoryRule.id == rule_id, CategoryRule.user_id == caller.user.id)
        .first()
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    if "pattern" in sent or "match_type" in sent:
        error = categorization.validate_pattern(sent.get("pattern", rule.pattern), sent.get("match_type", rule.match_type))
        if error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    result = run_write(db, caller, req, body)
    recategorized = 0
    if not result["dry_run"] and not result["unchanged"]:
        recategorized = categorization.apply_rules_to_all(db, caller.user.id)
        db.commit()
    return {**result, "transactions_recategorized": recategorized}
