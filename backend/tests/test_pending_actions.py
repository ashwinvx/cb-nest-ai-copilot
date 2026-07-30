"""Offline tests for the pending-action confirmation gate (no LLM).

Token integrity + the executor's fail-closed paths. The end-to-end
propose -> confirm flow through the real model and endpoints lives in
tests/smoke_action_agent.py. Run: .venv/bin/python -m tests.test_pending_actions
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ai_action_claim import AIActionClaim
from app.models.enums import Role
from app.services.ai.action_agent import execute_pending_action
from app.services.ai.pending_actions import (
    create_action_token,
    summarize_action,
    verify_action_token,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)


ARGS = {"leave_type": "CASUAL", "start_date": "2026-09-15", "end_date": "2026-09-15", "reason": "family function"}


def token_checks() -> None:
    tok = create_action_token(3, "create_leave_request", ARGS)
    good = verify_action_token(tok, 3)
    check("round-trip: tool + args + jti intact",
          good is not None
          and good["tool"] == "create_leave_request"
          and good["arguments"] == ARGS
          and isinstance(good.get("jti"), str) and len(good["jti"]) >= 16,
          str(good)[:110])

    # Distinct jti per token: the claim table's uniqueness depends on it.
    other = verify_action_token(create_action_token(3, "create_leave_request", ARGS), 3)
    check("each token gets a unique jti",
          other is not None and other["jti"] != good["jti"])

    check("wrong user -> None", verify_action_token(tok, 2) is None)
    check("tampered -> None", verify_action_token(tok[:-4] + "AAAA", 3) is None)
    check("garbage -> None", verify_action_token("not-a-token", 3) is None)

    # Expired: hand-craft with exp in the past, same secret.
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"purpose": "ai_pending_action", "sub": "3", "tool": "x", "args": {},
         "iat": now - timedelta(minutes=20), "exp": now - timedelta(minutes=10)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    check("expired -> None", verify_action_token(expired, 3) is None)

    # Wrong purpose (e.g. a real auth JWT replayed as an action token).
    auth_like = jwt.encode(
        {"sub": "3", "role": "EMPLOYEE", "exp": now + timedelta(minutes=10)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    check("auth JWT replayed as action token -> None",
          verify_action_token(auth_like, 3) is None)

    s = summarize_action("create_leave_request", ARGS)
    check("summary names type + date + reason",
          "CASUAL" in s and "2026-09-15" in s and "family function" in s, s)


async def executor_checks() -> None:
    async with SessionLocal() as db:
        # Invalid token: fail closed, indistinguishable message.
        r = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token="bogus", approve=True)
        check("executor: invalid token -> not executed",
              r["executed"] is False and r["tool"] is None, r["message"])

        # Foreign token (user 2 confirming user 3's action): same answer.
        tok = create_action_token(3, "create_leave_request", ARGS)
        r = await execute_pending_action(
            db, user_id=2, role=Role.MANAGER, token="irrelevant",
            action_token=tok, approve=True)
        check("executor: foreign token -> not executed",
              r["executed"] is False and r["tool"] is None, r["message"])

        # Decline: no dispatch, polite message, tool named for the UI.
        r = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token=tok, approve=False)
        check("executor: decline -> not executed, no dispatch",
              r["executed"] is False and r["tool"] == "create_leave_request", r["message"])

        # Single-use: the declined token must not be replayable as an
        # approval. Before the claim table existed, this executed.
        r = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token=tok, approve=True)
        check("executor: declined token replayed as approve -> rejected",
              r["executed"] is False and r["tool"] is None
              and "no longer valid" in r["message"], r["message"])

        # Single-use also covers approve -> approve.
        tok2 = create_action_token(3, "create_leave_request", ARGS)
        first = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token=tok2, approve=True)
        second = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token=tok2, approve=True)
        check("executor: approved token cannot be replayed",
              second["executed"] is False and "no longer valid" in second["message"],
              f"first_dispatched={first['tool']} second={second['message'][:40]}")

        # A replay is indistinguishable from an invalid token.
        bogus = await execute_pending_action(
            db, user_id=3, role=Role.EMPLOYEE, token="irrelevant",
            action_token="bogus", approve=True)
        check("executor: replay and invalid give identical answers",
              bogus["message"] == second["message"] and bogus["tool"] == second["tool"])

        # A claim row exists per consumed token, recording the decision.
        rows = (await db.execute(
            select(AIActionClaim).order_by(AIActionClaim.id.desc()).limit(4)
        )).scalars().all()
        decisions = {r.decision for r in rows}
        check("claims recorded with decisions", decisions <= {"APPROVED", "DECLINED"} and rows,
              str(sorted(decisions)))


def main() -> None:
    token_checks()
    asyncio.run(executor_checks())
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
