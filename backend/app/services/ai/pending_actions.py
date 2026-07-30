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

from app.core.config import settings

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
    """{"tool", "arguments"} if the token is valid for this user, else
    None. Fails closed on tamper, expiry, wrong purpose, wrong user."""
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if claims.get("purpose") != _PURPOSE or claims.get("sub") != str(user_id):
        return None
    tool, args = claims.get("tool"), claims.get("args")
    if not isinstance(tool, str) or not isinstance(args, dict):
        return None
    return {"tool": tool, "arguments": args}


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
