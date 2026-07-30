"""Signed confirmation tokens for AI-proposed state-changing actions.

The structural confirm-before-execute gate: when the model calls a
mutating tool, the agent does NOT execute it — it returns a signed
pending-action token describing the exact call. Execution happens only
when the client sends the token back to /chat/actions/confirm. The
model cannot be talked around this: interception is server-side, and
the token is HMAC-signed (same secret/algorithm as auth JWTs), bound
to the proposing user, single-purpose, and expiring — so it can't be
forged, edited to different arguments, or replayed by another user.
Replay by the same user within the TTL is bounded by endpoint business
rules (duplicate create -> LEAVE_OVERLAP, re-approve -> LEAVE_NOT_PENDING).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_action_claim import AIActionClaim

_PURPOSE = "ai_pending_action"
TTL_MINUTES = 10


def create_action_token(user_id: int, tool: str, arguments: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "purpose": _PURPOSE,
        "sub": str(user_id),
        "tool": tool,
        "args": arguments,
        "iat": now,
        "exp": now + timedelta(minutes=TTL_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_action_token(token: str, user_id: int) -> dict[str, Any] | None:
    """{"tool", "arguments", "jti"} if the token is valid for this user,
    else None. Fails closed on tamper, expiry, wrong purpose, wrong
    user. Validity is not consumption — call claim_action to consume."""
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if claims.get("purpose") != _PURPOSE or claims.get("sub") != str(user_id):
        return None
    tool, args, jti = claims.get("tool"), claims.get("args"), claims.get("jti")
    if not isinstance(tool, str) or not isinstance(args, dict) or not isinstance(jti, str):
        return None
    return {"tool": tool, "arguments": args, "jti": jti}


async def claim_action(
    db: AsyncSession, *, jti: str, user_id: int, tool: str, decision: str
) -> bool:
    """Atomically consume a token. Returns False if it was already used.

    The claim is the INSERT itself: `jti` is UNIQUE, so a duplicate is
    rejected by the database rather than by a check-then-act race. Both
    approval and decline consume the token — a declined action must not
    be replayable as an approval.
    """
    db.add(AIActionClaim(jti=jti, user_id=user_id, tool=tool, decision=decision))
    try:
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        return False


def summarize_action(tool: str, args: dict[str, Any]) -> str:
    """Human-readable one-liner shown in the confirmation UI."""
    if tool == "create_leave_request":
        start, end = args.get("start_date", "?"), args.get("end_date", "?")
        span = start if start == end else f"{start} to {end}"
        half = " (half day)" if args.get("is_half_day") else ""
        return f"File a {args.get('leave_type', '?')} leave request for {span}{half} — reason: {args.get('reason', '')}"
    if tool == "approve_leave":
        return f"Approve leave request #{args.get('request_id', '?')}"
    if tool == "reject_leave":
        return f"Reject leave request #{args.get('request_id', '?')}"
    return f"Execute {tool}"
