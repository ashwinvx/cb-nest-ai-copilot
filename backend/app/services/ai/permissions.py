"""AI-layer RBAC: the AI Permissions Matrix from CLAUDE.md as code.

This module answers exactly two kinds of question:
  1. Which tools may this role use at all?  (TOOL_PERMISSIONS,
     available_tools, is_tool_allowed — role-level gating)
  2. May this manager act on this specific employee?
     (is_direct_report_of — the team-membership check that the
     underlying leave endpoints do NOT perform)

Scope qualifiers in the matrix ("Limited", "Team only", "Own only",
"Optional") cannot be expressed as a role set alone; where a row carries
one, the entry's comment names it and the enforcement lives with the
capability (e.g. team scope via is_direct_report_of, SQL scoping in
sql_guardrails). A role appearing in a set below means "may invoke the
tool at all", never "may see everything the tool could return".

Fail-closed rules:
  - A tool name not present in TOOL_PERMISSIONS is denied for every role.
  - is_direct_report_of returns False for a missing employee, so callers
    naturally produce the same refusal for "not yours" and "not found" —
    never confirming whether a record exists (see refusal_message).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee

# Re-exported so AI-layer code has one import point for role checks.
# Imported (not redefined) so it can never drift from the Employee model.
from app.models.enums import Role

_ALL = frozenset({Role.EMPLOYEE, Role.MANAGER, Role.ADMIN})
_MGR_UP = frozenset({Role.MANAGER, Role.ADMIN})
_ADMIN = frozenset({Role.ADMIN})
_NOBODY: frozenset[Role] = frozenset()

# Transcribed row-by-row from "AI Permissions Matrix" in CLAUDE.md.
# Comment = the matrix row (Employee | Manager | Admin) it encodes.
TOOL_PERMISSIONS: dict[str, frozenset[Role]] = {
    "ask_policy_question":         _ALL,     # Ask HR policy questions: Yes | Yes | Yes
    "get_my_leave_balance":        _ALL,     # Ask own leave balance: Yes | Yes | Yes
    "get_my_leave_requests":       _ALL,     # (own-leave companion read; same row as own leave balance)
    "get_employee_leave_balance":  _MGR_UP,  # Ask another employee's leave balance: No | Team only | Yes
    "get_my_project_assignments":  _ALL,     # View own project assignments: Yes | Yes | Yes
    "get_all_project_assignments": _MGR_UP,  # View all project assignments: No | Limited | Yes
    "search_employees_by_skill":   _ALL,     # Search employees by skill: Limited | Yes | Yes
    "generate_sql":                _ALL,     # Generate SQL over HR data: Limited | Limited | Yes
    "view_raw_sql":                _MGR_UP,  # View raw SQL: No | Optional | Optional
    "create_leave_request":        _ALL,     # Create own leave request: Yes | Yes | Yes
    "approve_leave":               _MGR_UP,  # Approve/reject leave: No | Yes(team) | Yes
    "reject_leave":                _MGR_UP,  # Approve/reject leave: No | Yes(team) | Yes
    "create_ticket":               _ALL,     # Create ticket: Yes | Yes | Yes
    "assign_ticket":               _MGR_UP,  # Assign/update ticket: No | Yes | Yes
    "update_ticket":               _MGR_UP,  # Assign/update ticket: No | Yes | Yes
    "create_announcement":         _MGR_UP,  # Create announcement: No | Yes | Yes
    "assign_employee_to_project":  _MGR_UP,  # Assign employee to project: No | Yes | Yes
    "get_payroll_data":            _ADMIN,   # Access payroll data: Own only or blocked | Restricted | Admin only
    "access_bank_pan_password":    _NOBODY,  # Access bank/PAN/password fields: No | No | No
}


def available_tools(role: Role) -> frozenset[str]:
    """Tool names this role may invoke. Anything unlisted is denied."""
    return frozenset(name for name, roles in TOOL_PERMISSIONS.items() if role in roles)


def is_tool_allowed(tool_name: str, role: Role) -> bool:
    """Fail closed: unknown tool names are denied for every role."""
    return role in TOOL_PERMISSIONS.get(tool_name, _NOBODY)


async def is_direct_report_of(
    manager_id: int, target_employee_id: int, db: AsyncSession
) -> bool:
    """True iff target_employee_id is a direct report of manager_id.

    Role-neutral team-membership check backing every "Team only" matrix
    qualifier: the read side (get_employee_leave_balance) and the manage
    side (approve_leave / reject_leave, whose underlying endpoints check
    role only). Fails closed: unknown employee -> False, same as "not
    your report", so refusals never reveal whether the employee exists.
    Intentionally False for self (you are not your own report) and for
    indirect reports (matrix says team, not subtree).
    """
    row = await db.execute(
        select(Employee.manager_id).where(Employee.id == target_employee_id)
    )
    target_manager_id = row.scalar_one_or_none()
    return target_manager_id is not None and target_manager_id == manager_id


def refusal_message(capability: str) -> str:
    """Uniform refusal that never confirms a record exists.

    Matches the CLAUDE.md "Good" example: state the missing permission
    only — never "I found it but can't show you".
    """
    return f"You do not have permission to {capability}."
