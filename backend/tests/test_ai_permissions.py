"""Matrix-walking test for app/services/ai/permissions.py.

EXPECTED below is an independent transcription of the AI Permissions
Matrix in CLAUDE.md — deliberately not imported from the module under
test, so a transcription error there fails here instead of mirroring.

Dependency-free on purpose (no pytest yet): run with
    .venv/bin/python -m tests.test_ai_permissions
Exit code 0 = all checks passed.
"""

import asyncio
import hashlib
import sys
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.employee import Employee
from app.services.ai.permissions import (
    Role,
    TOOL_PERMISSIONS,
    available_tools,
    is_direct_report_of,
    is_tool_allowed,
    refusal_message,
)

E, M, A = Role.EMPLOYEE, Role.MANAGER, Role.ADMIN

# tool -> (employee_allowed, manager_allowed, admin_allowed),
# one line per AI Permissions Matrix row in CLAUDE.md.
EXPECTED: dict[str, tuple[bool, bool, bool]] = {
    "ask_policy_question":         (True,  True,  True),   # Ask HR policy questions
    "get_my_leave_balance":        (True,  True,  True),   # Ask own leave balance
    "get_my_leave_requests":       (True,  True,  True),   # own-leave companion read
    "get_employee_leave_balance":  (False, True,  True),   # Another employee's balance: No | Team only | Yes
    "get_my_project_assignments":  (True,  True,  True),   # View own project assignments
    "get_all_project_assignments": (False, True,  True),   # View all: No | Limited | Yes
    "search_employees_by_skill":   (True,  True,  True),   # Limited | Yes | Yes
    "generate_sql":                (True,  True,  True),   # Limited | Limited | Yes
    "view_raw_sql":                (False, True,  True),   # No | Optional | Optional
    "create_leave_request":        (True,  True,  True),   # Create own leave request
    "approve_leave":               (False, True,  True),   # No | Yes(team) | Yes
    "reject_leave":                (False, True,  True),   # No | Yes(team) | Yes
    "create_ticket":               (True,  True,  True),   # Create ticket
    "assign_ticket":               (False, True,  True),   # Assign/update ticket: No | Yes | Yes
    "update_ticket":               (False, True,  True),   # Assign/update ticket: No | Yes | Yes
    "create_announcement":         (False, True,  True),   # No | Yes | Yes
    "assign_employee_to_project":  (False, True,  True),   # No | Yes | Yes
    "get_payroll_data":            (False, False, True),   # Own only or blocked | Restricted | Admin only
    "access_bank_pan_password":    (False, False, False),  # No | No | No
}

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)


def walk_matrix() -> None:
    check("module and test cover the same tool names",
          set(EXPECTED) == set(TOOL_PERMISSIONS))
    for tool, (emp, mgr, adm) in EXPECTED.items():
        for role, expected in ((E, emp), (M, mgr), (A, adm)):
            got = is_tool_allowed(tool, role)
            check(f"{tool} x {role.value}: expect {expected}", got == expected)

    # Fail-closed: unknown tools denied for every role.
    for role in (E, M, A):
        check(f"unknown tool denied for {role.value}",
              not is_tool_allowed("delete_all_leave_requests", role))

    # available_tools must agree with is_tool_allowed exactly.
    for role in (E, M, A):
        expected_set = {t for t, flags in EXPECTED.items()
                        for r, f in ((E, flags[0]), (M, flags[1]), (A, flags[2]))
                        if r is role and f}
        check(f"available_tools({role.value}) matches matrix",
              available_tools(role) == expected_set)

    check("nobody can access bank/PAN/password fields",
          all("access_bank_pan_password" not in available_tools(r) for r in (E, M, A)))


async def team_checks() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Employee.__table__.create(sync_conn)
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def emp(id_, name, manager_id=None, role=Role.EMPLOYEE):
        return Employee(
            id=id_, name=name, email=f"{name}@t.dev", hashed_password="x",
            manager_id=manager_id, role=role, joining_date=date(2024, 1, 1),
        )

    async with sessions() as db:
        db.add_all([
            emp(1, "mgr", manager_id=None, role=Role.MANAGER),
            emp(2, "direct-report", manager_id=1),
            emp(3, "other-team", manager_id=99),
            emp(4, "skip-level-mgr", manager_id=1, role=Role.MANAGER),
            emp(5, "indirect-report", manager_id=4),
        ])
        await db.commit()

        check("direct report -> True", await is_direct_report_of(1, 2, db))
        check("other team -> False", not await is_direct_report_of(1, 3, db))
        check("self -> False", not await is_direct_report_of(1, 1, db))
        check("indirect report -> False (team, not subtree)",
              not await is_direct_report_of(1, 5, db))
        check("nonexistent employee -> False (fail closed, no existence leak)",
              not await is_direct_report_of(1, 424242, db))

    await engine.dispose()


# sha256 of the matrix table lines in CLAUDE.md. Neither this test's
# EXPECTED dict nor the module's TOOL_PERMISSIONS reads CLAUDE.md, so an
# edit to the matrix would otherwise leave both transcriptions green
# while drifting from the documented policy. If this check fails:
# re-verify EXPECTED and TOOL_PERMISSIONS against the new matrix, then
# update the hash.
MATRIX_GUARD_SHA256 = "541ae9f2a73b40db22d8ca5d29404d6b3190cd71994a06bc7ae9d35ea8812615"


def matrix_guard_check() -> None:
    claude_md = Path(__file__).resolve().parents[2] / "CLAUDE.md"
    section = claude_md.read_text().split("## AI Permissions Matrix", 1)[1]
    table = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")]
    digest = hashlib.sha256("\n".join(table).encode()).hexdigest()
    check(
        "CLAUDE.md matrix unchanged (else re-verify both transcriptions + update hash)",
        digest == MATRIX_GUARD_SHA256,
    )


def refusal_checks() -> None:
    msg = refusal_message("view another employee's payroll information")
    check("refusal matches CLAUDE.md 'Good' wording",
          msg == "You do not have permission to view another employee's payroll information.")
    for banned in ("found", "exists", "record"):
        check(f"refusal never says '{banned}'", banned not in msg.lower())


def main() -> None:
    matrix_guard_check()
    walk_matrix()
    asyncio.run(team_checks())
    refusal_checks()
    print(f"\n{sum(1 for _ in failures)} failures / "
          f"{len(failures) and 'FAILED' or 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
