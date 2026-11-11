"""Bodies of Claude's paid-back write routes (T-03-3 P5)."""
from app.schemas import PlanningWriteRequest


class ClaudeUnmarkRequest(PlanningWriteRequest):
    """POST /planning/repayments/{mark_id}/unmark: `dry_run` and the
    idempotency key only (a body, so a dry run is charged as one)."""
