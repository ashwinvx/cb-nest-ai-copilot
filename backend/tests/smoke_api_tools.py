"""Smoke test for app/services/ai/api_tools.py against the seeded dev DB.

Logs in as the seeded employee user, then exercises the three tools,
including validation and auth failure paths. Read-only except for one
leave-request creation (PENDING, harmless in the re-seedable dev DB).
"""

import asyncio
import json
import sys
from datetime import date, timedelta

import httpx

from app.main import app
from app.services.ai import api_tools

EMAIL = "employee@mock-hrms.dev"
MANAGER_EMAIL = "manager@mock-hrms.dev"
ADMIN_EMAIL = "admin@mock-hrms.dev"
PASSWORD = "password123"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


async def get_token(email: str = EMAIL) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/token",
            data={"username": email, "password": PASSWORD},
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or body
        token = data.get("access_token")
        assert token, f"no access_token in {body}"
        return token


async def create_pending(token: str, leave_type: str, base_offset: int) -> int | None:
    """Create a PENDING request on the first free date; return its id."""
    for offset in range(base_offset, base_offset + 60):
        start = date.today() + timedelta(days=offset)
        r = await api_tools.create_leave_request(
            token, leave_type=leave_type, start_date=start, end_date=start,
            reason="approve/reject smoke test",
        )
        if r["success"]:
            return r["data"]["id"]
        if r["error"]["code"] != "LEAVE_OVERLAP":
            return None
    return None


async def approval_checks() -> None:
    from app.db.session import SessionLocal

    emp_token = await get_token(EMAIL)
    mgr_token = await get_token(MANAGER_EMAIL)
    adm_token = await get_token(ADMIN_EMAIL)
    expected_refusal = "You do not have permission to approve this leave request."

    async with SessionLocal() as db:
        # Security prompt: "Approve this leave as an employee user."
        target = await create_pending(emp_token, "SICK", 100)
        check("setup: employee PENDING request created", target is not None)
        r = await api_tools.approve_leave(emp_token, db, request_id=target)
        check("employee approve -> FORBIDDEN refusal",
              not r["success"] and r["error"]["code"] == "FORBIDDEN"
              and r["error"]["message"] == expected_refusal, json.dumps(r)[:140])

        # Manager approving own report's request -> succeeds.
        r = await api_tools.approve_leave(mgr_token, db, request_id=target)
        check("manager approve direct report -> APPROVED",
              r["success"] and r["data"]["status"] == "APPROVED", json.dumps(r)[:140])

        # Manager rejecting own report's second request -> succeeds.
        target2 = await create_pending(emp_token, "EARNED", 170)
        check("setup: second PENDING request created", target2 is not None)
        r = await api_tools.reject_leave(mgr_token, db, request_id=target2)
        check("manager reject direct report -> REJECTED",
              r["success"] and r["data"]["status"] == "REJECTED", json.dumps(r)[:140])

        # Manager approving their own request -> refused (self is not a report).
        own = await create_pending(mgr_token, "CASUAL", 240)
        check("setup: manager's own PENDING request created", own is not None)
        r = await api_tools.approve_leave(mgr_token, db, request_id=own)
        check("manager self-approve -> FORBIDDEN refusal",
              not r["success"] and r["error"]["code"] == "FORBIDDEN"
              and r["error"]["message"] == expected_refusal, json.dumps(r)[:140])

        # Manager + nonexistent id -> same refusal (no existence leak).
        r = await api_tools.approve_leave(mgr_token, db, request_id=98765432)
        check("manager approve nonexistent -> identical refusal",
              not r["success"] and r["error"]["message"] == expected_refusal,
              json.dumps(r)[:140])

        # Admin bypasses team scope: approves the manager's own request.
        r = await api_tools.approve_leave(adm_token, db, request_id=own)
        check("admin approve any pending -> APPROVED",
              r["success"] and r["data"]["status"] == "APPROVED", json.dumps(r)[:140])


async def main() -> None:
    token = await get_token()

    # 1. Balance read
    r = await api_tools.get_my_leave_balance(token)
    ok = r["success"] and isinstance(r["data"], list) and len(r["data"]) == 3
    check("get_my_leave_balance returns 3 balance rows", ok, json.dumps(r)[:120])

    # 2. Requests read
    r = await api_tools.get_my_leave_requests(token, limit=5)
    ok = r["success"] and "items" in (r["data"] or {})
    check("get_my_leave_requests returns items+meta", ok, json.dumps(r)[:120])

    # 3. Create: bad date string -> local validation error, no API call
    r = await api_tools.create_leave_request(
        token, leave_type="CASUAL", start_date="not-a-date",
        end_date="2026-08-01", reason="smoke test",
    )
    ok = not r["success"] and r["error"]["code"] == "VALIDATION_ERROR"
    check("create: bad date -> VALIDATION_ERROR", ok, json.dumps(r)[:120])

    # 4. Create: bad leave type -> endpoint business error passed through
    r = await api_tools.create_leave_request(
        token, leave_type="UNPAID", start_date="2026-08-03",
        end_date="2026-08-03", reason="smoke test",
    )
    ok = not r["success"] and r["error"]["code"] == "INVALID_LEAVE_TYPE"
    check("create: bad type -> INVALID_LEAVE_TYPE", ok, json.dumps(r)[:120])

    # 5. Create: short reason -> 422 summarized
    r = await api_tools.create_leave_request(
        token, leave_type="CASUAL", start_date="2026-08-03",
        end_date="2026-08-03", reason="ab",
    )
    ok = not r["success"] and r["error"]["code"] == "VALIDATION_ERROR"
    check("create: short reason -> 422 summarized", ok, json.dumps(r)[:150])

    # 6. Create: valid request far in the future -> PENDING.
    # Walk forward past dates already taken by previous runs.
    created = False
    r = None
    for offset in range(340, 400):
        start = date.today() + timedelta(days=offset)
        r = await api_tools.create_leave_request(
            token, leave_type="CASUAL", start_date=start, end_date=start,
            reason="api_tools smoke test",
        )
        if r["success"]:
            created = r["data"]["status"] == "PENDING"
            break
        if r["error"]["code"] != "LEAVE_OVERLAP":
            break
    check("create: valid -> PENDING request", created, json.dumps(r)[:150])

    # 7. Create: same dates again -> LEAVE_OVERLAP
    r = await api_tools.create_leave_request(
        token, leave_type="CASUAL", start_date=start, end_date=start,
        reason="api_tools smoke test duplicate",
    )
    ok = not r["success"] and r["error"]["code"] == "LEAVE_OVERLAP"
    check("create: overlap -> LEAVE_OVERLAP", ok, json.dumps(r)[:120])

    # 8. Bad token -> clean auth error envelope, no raw error.
    # The endpoint's own INVALID_TOKEN envelope is passed through;
    # NOT_AUTHORIZED is the fallback for envelope-less 401/403s.
    r = await api_tools.get_my_leave_balance("garbage-token")
    ok = not r["success"] and r["error"]["code"] in ("INVALID_TOKEN", "NOT_AUTHORIZED")
    check("bad token -> clean auth error", ok, json.dumps(r)[:120])

    await approval_checks()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        sys.exit(1)


asyncio.run(main())
