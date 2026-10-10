"""The dependency every planning write route uses (T-08-3a).

`PlanningWriter` gives the route a `Caller`: a web session, or an MCP token
that was granted `finance:planning.write` (403 `insufficient_scope`
otherwise, 401 once the grant is revoked or the password changed). The
control lives here, at the API, because the MCP client holds the token and
can call the API directly; the MCP server's own scope check is a second
layer.

It also rate-limits per user id, never per IP: every remote MCP call reaches
the API from the MCP container's address, so an IP key would make all users
share one budget. Applied writes and dry runs have separate budgets, so
previews can't use up the write budget and the looser preview budget can't
be used to write. Counters are in-process, so with two uvicorn workers a
user can get up to twice each limit per hour.
"""
import json
from typing import Annotated

from fastapi import Depends, Request

from app.core.oauth_tokens import SCOPE_PLANNING_WRITE, Caller, scoped_caller
from app.core.rate_limit import user_rate_limiter

WRITE_LIMIT = 30
DRY_RUN_LIMIT = 120
WINDOW_SECONDS = 60 * 60


async def _is_dry_run(request: Request) -> bool:
    """Whether the body asks for a dry run, before the route's model parses it.

    Only a JSON `true` (or no `dry_run` field, which the write routes default
    to true) is a dry run. Anything else counts against the write budget,
    including values the model would coerce to False ("false", 0) and
    bodies that aren't JSON objects.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(body, dict):
        return False
    return body.get("dry_run", True) is True


def planning_writer(
    caller: Annotated[Caller, Depends(scoped_caller(SCOPE_PLANNING_WRITE))],
    dry_run: Annotated[bool, Depends(_is_dry_run)],
) -> Caller:
    if dry_run:
        user_rate_limiter.check_key(f"planning-dry-run:{caller.user.id}", DRY_RUN_LIMIT, WINDOW_SECONDS)
    else:
        user_rate_limiter.check_key(f"planning-write:{caller.user.id}", WRITE_LIMIT, WINDOW_SECONDS)
    return caller


PlanningWriter = Annotated[Caller, Depends(planning_writer)]
