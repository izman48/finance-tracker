"""Claude's edits to existing categorisation rules over MCP.

Every route takes `RulesEditor` (the finance:rules.edit scope, and the
per-user write limits shared with every other Claude write) and goes through
the planning-write framework: dry_run by default, idempotency, an encrypted
audit row (`target_kind: "rule"`), web-only undo. Only the matching fields
in `TARGETS["rule"]` change. A rule is addressed by its id, never by its
pattern (untrusted text). Switching a rule off is `enabled: false`, never a
delete, so the change can be undone. An applied edit re-runs the rules over
the user's history in the same transaction (a dry run counts it in its
savepoint), and the audit row records the categories it changed, so undo
puts them back.
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
from app.services.planning_writes import TARGETS, WriteRequest, replay_if_applied, run_write

router = APIRouter(prefix="/planning/rules", tags=["planning"])

_EDITABLE = TARGETS["rule"].names
# The most transactions one of Claude's edits may recategorise (T-16-3, sec):
# each is a record in the encrypted undo record, so this bounds its size
# (about 1.3 MB of JSON at most). Never raise it without sec. The web Rules
# page keeps no undo record and is not capped.
RECATEGORISE_CAP = 5000
# Fixed text: never echoes the pattern or category.
OVER_CAP = "This change would recategorise more than 5,000 transactions. Make it on the Rules page."


@router.post("/{rule_id}/update")
def update_rule(rule_id: uuid.UUID, body: ClaudeRuleUpdateRequest, caller: RulesEditor,
                db: Annotated[Session, Depends(get_db)]) -> dict:
    """Change one of the user's rules. Fields left out are unchanged. The
    pattern is checked with the match type it will run under (the new one,
    or the stored one), so no edit can store a pattern the engine can't run.
    Another user's rule, or an unknown id: 404."""
    sent = {f: getattr(body, f) for f in _EDITABLE if f in body.model_fields_set}

    def apply(db: Session, rule: CategoryRule) -> CategoryRule:
        for field, value in sent.items():
            setattr(rule, field, value)
        return rule

    def backfill(db: Session) -> list[dict]:
        changed = categorization.recategorize_all(db, caller.user.id)
        if len(changed) > RECATEGORISE_CAP and not body.dry_run:
            # Raised inside run_write's transaction, so nothing is kept: not
            # the rule, the categories, the audit row or the idempotency key.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OVER_CAP)
        return changed

    req = WriteRequest(tool="update_rule", target_kind="rule", target_id=rule_id, apply=apply, side_effect=backfill)
    replay = replay_if_applied(db, caller, req, body)
    if replay is not None:
        return _with_recategorized(replay)

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

    return _with_recategorized(run_write(db, caller, req, body))


def _with_recategorized(result: dict) -> dict:
    """The framework's `side_effects` count, by its name here: how many
    transactions the edit recategorises (a dry run's real count too), and
    whether that is over the cap, so a preview can say apply will be refused."""
    result = dict(result)
    count = result.pop("side_effects", 0)
    return {**result, "transactions_recategorized": count, "over_cap": count > RECATEGORISE_CAP}
