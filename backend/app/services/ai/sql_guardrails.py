"""Read-only SQL guardrails: allowlist + AST validation + role scoping.

Pure functions, no I/O — everything here is unit-testable without a DB
or an LLM.

Design (approved 2026-07-30):

* Allowlist first. CLAUDE.md's 12 forbidden columns are enforced, but a
  denylist alone under-protects this schema: payroll_records carries
  gross/net/deductions/pan/pf_uan/esi_no and employees carries
  bank_name/email/phone/address — none on that list. So only explicitly
  allowed tables and columns pass, and new sensitive columns added by
  future migrations fail closed. FORBIDDEN_COLUMNS is kept as a second,
  independent check.
* payroll_records and employee_documents are excluded at EVERY role,
  including admin. Do not add an admin exception without asking.
* Validation is AST-based (sqlglot), never string matching: comments,
  stacked statements, CTE-wrapped DML, and creative spellings are
  handled structurally.
* Row scoping: employees are refused SQL entirely (see README —
  silent self-scoping yields confidently wrong aggregates); managers
  get every `employees` reference rewritten to a team-scoped subquery,
  which propagates through joins; admins run unscoped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.models.enums import (
    AttendanceStatus,
    EmployeeStatus,
    HalfDayPeriod,
    LeaveRequestStatus,
    LeaveType,
    ProjectStatus,
    SkillLevel,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from app.services.ai.permissions import Role

MAX_ROWS = 200

# Never selectable, at any role (CLAUDE.md). Enforced independently of
# the allowlist so the brief's list stays explicit in the code.
FORBIDDEN_COLUMNS = frozenset({
    "hashed_password",
    "bank_account_number",
    "bank_account_name",
    "bank_branch",
    "bank_ifsc",
    "pan_number",
    "pan_name",
    "pan_dob",
    "date_of_birth",
    "current_salary_usd",
    "profile_photo_path",
    "profile_photo_mime",
})

# The only tables/columns the SQL agent may touch. payroll_records and
# employee_documents are deliberately absent at every role.
ALLOWED: dict[str, frozenset[str]] = {
    "employees": frozenset({
        "id", "name", "department_id", "manager_id", "role", "status",
        "joining_date", "occupancy", "blood_type",
    }),
    "departments": frozenset({"id", "name", "location"}),
    "leave_requests": frozenset({
        "id", "employee_id", "leave_type", "start_date", "end_date", "reason",
        "status", "approver_id", "is_half_day", "half_day_period",
    }),
    "leave_balances": frozenset({"id", "employee_id", "leave_type", "total", "used", "remaining"}),
    "attendance_logs": frozenset({
        "id", "employee_id", "date", "clock_in", "clock_out", "status",
        "work_mode", "punctuality",
    }),
    "projects": frozenset({"id", "name", "description", "status"}),
    "employee_projects": frozenset({"id", "employee_id", "project_id", "role_on_project"}),
    "skills": frozenset({"id", "name", "normalized_name"}),
    "employee_skills": frozenset({"id", "employee_id", "skill_id", "level"}),
    "tickets": frozenset({
        "id", "employee_id", "assignee_id", "title", "category", "priority",
        "status", "created_at",
    }),
    "job_history": frozenset({
        "id", "employee_id", "designation", "department", "start_date",
        "end_date", "is_current",
    }),
}

# Allowed values for enum-backed columns, derived from the model layer
# so they cannot drift from what is actually stored. work_mode and
# punctuality are plain strings in the schema; their values come from
# what the app writes.
ENUM_VALUES: dict[str, list[str]] = {
    "employees.role": [m.value for m in Role],
    "employees.status": [m.value for m in EmployeeStatus],
    "leave_requests.leave_type": [m.value for m in LeaveType],
    "leave_requests.status": [m.value for m in LeaveRequestStatus],
    "leave_requests.half_day_period": [m.value for m in HalfDayPeriod],
    "leave_balances.leave_type": [m.value for m in LeaveType],
    "attendance_logs.status": [m.value for m in AttendanceStatus],
    "attendance_logs.punctuality": ["ON_TIME", "LATE"],
    "attendance_logs.work_mode": ["PRESENT", "WFH"],
    "projects.status": [m.value for m in ProjectStatus],
    "employee_skills.level": [m.value for m in SkillLevel],
    "tickets.category": [m.value for m in TicketCategory],
    "tickets.priority": [m.value for m in TicketPriority],
    "tickets.status": [m.value for m in TicketStatus],
}

# Scalar/aggregate functions the agent may call. Anything else (
# load_extension, readfile, writefile, ...) is refused.
ALLOWED_FUNCTIONS = frozenset({
    "count", "sum", "avg", "min", "max", "round", "abs", "coalesce", "ifnull",
    "nullif", "length", "lower", "upper", "trim", "substr", "date", "datetime",
    "strftime", "julianday", "cast", "distinct", "group_concat", "printf",
})


@dataclass
class GuardResult:
    ok: bool
    sql: str | None = None            # validated (and scoped) SQL to execute
    error_code: str | None = None
    message: str | None = None
    tables: list[str] = field(default_factory=list)


def _fail(code: str, message: str) -> GuardResult:
    return GuardResult(ok=False, error_code=code, message=message)


def schema_prompt(role: Role) -> str:
    """Schema description for the model — allowlisted tables/columns
    only, so forbidden columns are absent from the model's world."""
    lines = ["Tables you may query (SQLite). No other tables or columns exist for you:"]
    for table in sorted(ALLOWED):
        lines.append(f"  {table}({', '.join(sorted(ALLOWED[table]))})")

    # Enum values are stored UPPERCASE and SQLite's = is case-sensitive,
    # so a query written as status = 'pending' silently matches nothing
    # and yields a confidently wrong answer. Spell the values out.
    lines.append(
        "\nEnum columns store these exact UPPERCASE values — compare against them "
        "verbatim (SQLite string comparison is case-sensitive):"
    )
    for column, values in sorted(ENUM_VALUES.items()):
        lines.append(f"  {column}: {', '.join(values)}")

    if role is Role.MANAGER:
        lines.append(
            "\nNote: results are automatically restricted to the manager's own "
            "direct reports; write queries normally without adding that filter."
        )
    return "\n".join(lines)


def _scoped_employees(user_id: int) -> exp.Subquery:
    """`employees` -> (SELECT <allowed cols> FROM employees
    WHERE manager_id = :me OR id = :me) AS employees."""
    cols = ", ".join(sorted(ALLOWED["employees"]))
    sub = sqlglot.parse_one(
        f"(SELECT {cols} FROM employees "
        f"WHERE manager_id = {int(user_id)} OR id = {int(user_id)})",
        read="sqlite",
    )
    return sub.as_("employees")


def validate_sql(sql: str, role: Role, user_id: int) -> GuardResult:
    """Parse, validate, scope, and cap a model-generated query."""
    if role is Role.EMPLOYEE:
        return _fail("ROLE_NOT_ALLOWED", "SQL queries are not available for your role.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except Exception:
        return _fail("PARSE_ERROR", "That query could not be parsed.")

    if len(statements) != 1:
        return _fail("MULTI_STATEMENT", "Only one statement per request is allowed.")

    tree = statements[0]

    # Root must be a plain SELECT (a WITH wrapper is fine if its body is
    # a SELECT). This alone rejects INSERT/UPDATE/DELETE/DROP/ALTER/
    # CREATE/REPLACE/TRUNCATE/PRAGMA/ATTACH/DETACH however they are
    # spelled, commented, or cased — the parser normalizes all of that.
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        return _fail("NON_SELECT", "Only read-only SELECT queries are allowed.")

    # No destructive or side-effecting node anywhere in the tree,
    # including inside CTEs and subqueries.
    banned_nodes = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
        exp.Command, exp.Pragma, exp.Set, exp.Use, exp.Transaction,
        exp.Commit, exp.Rollback,
    )
    for node in tree.walk():
        if isinstance(node, banned_nodes):
            return _fail("NON_SELECT", "Only read-only SELECT queries are allowed.")
        if isinstance(node, exp.Anonymous):
            name = (node.name or "").lower()
            if name not in ALLOWED_FUNCTIONS:
                return _fail("FUNCTION_NOT_ALLOWED", "That query uses an unsupported function.")

    # Tables: allowlist only. CTE aliases are legal names, not tables.
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    used_tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if name in cte_names:
            continue
        if name not in ALLOWED:
            return _fail("TABLE_NOT_ALLOWED", "That query references data you can't access.")
        used_tables.add(name)

    # Columns: forbidden list first (explicit), then allowlist.
    alias_map = {
        (t.alias or t.name).lower(): t.name.lower()
        for t in tree.find_all(exp.Table)
        if t.name and t.name.lower() in ALLOWED
    }
    allowed_any = set().union(*ALLOWED.values()) if ALLOWED else set()
    # Names the query itself defines (CTE output columns, SELECT aliases)
    # are identifiers, not base-table columns — they were validated at
    # the point they were computed.
    defined_aliases = {
        (a.alias or "").lower() for a in tree.find_all(exp.Alias) if a.alias
    }
    allowed_any |= defined_aliases
    for column in tree.find_all(exp.Column):
        col = (column.name or "").lower()
        if col == "*":
            continue
        if col in FORBIDDEN_COLUMNS:
            return _fail("FORBIDDEN_COLUMN", "That query references data you can't access.")
        qualifier = (column.table or "").lower()
        if qualifier and qualifier in alias_map:
            if col not in ALLOWED[alias_map[qualifier]]:
                return _fail("FORBIDDEN_COLUMN", "That query references data you can't access.")
        elif qualifier and qualifier in cte_names:
            continue  # CTE output column; its source was validated already
        elif col not in allowed_any:
            return _fail("FORBIDDEN_COLUMN", "That query references data you can't access.")

    # SELECT * would expose non-allowlisted columns of a real table.
    for star in tree.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Count):
            continue  # COUNT(*) touches no column values
        return _fail("STAR_NOT_ALLOWED", "Please select specific columns rather than *.")

    # Manager row scoping: every `employees` reference becomes a
    # team-scoped subquery, so joins and aggregates inherit the scope.
    if role is Role.MANAGER:
        def scope(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Table) and (node.name or "").lower() == "employees":
                sub = _scoped_employees(user_id)
                if node.alias:
                    sub = sub.as_(node.alias)
                return sub
            return node

        tree = tree.transform(scope)

    # Mandatory row cap.
    limit = tree.args.get("limit") if isinstance(tree, exp.Select) else None
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        try:
            requested = int(limit.expression.name)
            if requested > MAX_ROWS:
                tree = tree.limit(MAX_ROWS)
        except (AttributeError, ValueError):
            tree = tree.limit(MAX_ROWS)

    return GuardResult(ok=True, sql=tree.sql(dialect="sqlite"), tables=sorted(used_tables))
