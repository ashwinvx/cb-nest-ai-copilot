"""Offline tests for the action agent (no LLM call, no API key).

Covers role-based tool exposure, dispatch wiring, and audit status
mapping. The live security-prompt suite is tests/smoke_action_agent.py.
Run with: .venv/bin/python -m tests.test_action_agent
"""

import asyncio
import sys

from app.models.ai_audit_log import AIAuditStatus
from app.services.ai.action_agent import (
    TOOL_SCHEMAS,
    Role,
    _audit_status,
    _dispatch,
    _record_ids,
    tools_for_role,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)


def tool_exposure() -> None:
    names = lambda role: {t["name"] for t in tools_for_role(role)}  # noqa: E731
    check("employee: no approve/reject offered",
          names(Role.EMPLOYEE) == {"create_leave_request", "get_my_leave_balance", "get_my_leave_requests"},
          str(sorted(names(Role.EMPLOYEE))))
    check("manager: approve/reject offered",
          {"approve_leave", "reject_leave"} <= names(Role.MANAGER))
    check("admin: same action set as manager", names(Role.ADMIN) == names(Role.MANAGER))
    check("every schema hides token/db/employee_id",
          all(not ({"token", "db", "employee_id"} & set(s["input_schema"].get("properties", {})))
              for s in TOOL_SCHEMAS.values()))


async def dispatch_checks() -> None:
    # Unknown tool fails closed without touching anything.
    r = await _dispatch("delete_all_leave_requests", {}, "tok", None)
    check("unknown tool -> UNKNOWN_TOOL, fail closed",
          not r["success"] and r["error"]["code"] == "UNKNOWN_TOOL")

    # Known tool with a garbage token flows through the API layer and
    # comes back as a clean envelope, never an exception.
    r = await _dispatch("get_my_leave_balance", {}, "garbage", None)
    check("bad token via dispatch -> clean envelope",
          not r["success"] and "error" in r, str(r)[:100])


def status_mapping() -> None:
    ok = {"success": True, "data": {"id": 7}, "error": None}
    check("success -> SUCCESS", _audit_status(ok) is AIAuditStatus.SUCCESS)
    check("success record id extracted", _record_ids(ok) == [7])
    forb = {"success": False, "data": None, "error": {"code": "FORBIDDEN", "message": "x"}}
    check("FORBIDDEN -> REFUSED", _audit_status(forb) is AIAuditStatus.REFUSED)
    bad = {"success": False, "data": None, "error": {"code": "LEAVE_OVERLAP", "message": "x"}}
    check("business error -> ERROR", _audit_status(bad) is AIAuditStatus.ERROR)
    check("list data has no record ids", _record_ids({"success": True, "data": [1, 2]}) is None)


def main() -> None:
    tool_exposure()
    asyncio.run(dispatch_checks())
    status_mapping()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
