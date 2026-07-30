"""Evasion corpus for sql_guardrails — pure, no DB, no LLM.

Assertions are on structure and effects (blocked / allowed / rewritten),
never on topic words. Run: .venv/bin/python -m tests.test_sql_guardrails
"""

import sys

from app.services.ai.permissions import Role
from app.services.ai.sql_guardrails import MAX_ROWS, validate_sql

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)


ADMIN, MANAGER, EMPLOYEE = Role.ADMIN, Role.MANAGER, Role.EMPLOYEE

# Every one of these must be blocked for an ADMIN (the most permissive
# role) — if admin can't, nobody can.
MUST_BLOCK = [
    ("plain drop", "DROP TABLE employees;"),
    ("select then drop (stacked)", "SELECT id FROM employees; DROP TABLE employees;"),
    ("stacked with comment", "SELECT id FROM employees; -- ok\nDELETE FROM leave_requests;"),
    ("comment-hidden drop", "/* harmless */ DROP TABLE employees"),
    ("inline comment inside keyword position", "DR/**/OP TABLE employees"),
    ("delete", "DELETE FROM leave_requests WHERE id = 1"),
    ("update", "UPDATE employees SET role = 'ADMIN' WHERE id = 3"),
    ("insert", "INSERT INTO leave_requests (employee_id) VALUES (3)"),
    ("create", "CREATE TABLE evil (x INT)"),
    ("alter", "ALTER TABLE employees ADD COLUMN evil TEXT"),
    ("pragma", "PRAGMA table_info(employees)"),
    ("attach", "ATTACH DATABASE '/tmp/x.db' AS x"),
    ("detach", "DETACH DATABASE x"),
    ("cte wrapping delete", "WITH x AS (DELETE FROM leave_requests RETURNING id) SELECT id FROM x"),
    ("forbidden col direct", "SELECT bank_account_number FROM employees"),
    ("forbidden col qualified", "SELECT e.hashed_password FROM employees e"),
    ("forbidden col uppercase", "SELECT BANK_IFSC FROM employees"),
    ("forbidden col in where", "SELECT id FROM employees WHERE pan_number = 'X'"),
    ("forbidden col in subquery",
     "SELECT id FROM employees WHERE id IN (SELECT id FROM employees WHERE current_salary_usd > 1)"),
    ("forbidden col in order by", "SELECT id FROM employees ORDER BY date_of_birth"),
    ("salary aggregate", "SELECT AVG(current_salary_usd) FROM employees"),
    ("payroll table excluded", "SELECT net FROM payroll_records"),
    ("payroll join", "SELECT e.name, p.net FROM employees e JOIN payroll_records p ON p.employee_id = e.id"),
    ("documents table excluded", "SELECT id FROM employee_documents"),
    ("sqlite internals", "SELECT name FROM sqlite_master"),
    ("audit log not exposed", "SELECT message FROM ai_audit_logs"),
    ("non-allowlisted col on allowed table", "SELECT email FROM employees"),
    ("phone is not allowlisted", "SELECT phone FROM employees"),
    ("star", "SELECT * FROM employees"),
    ("qualified star", "SELECT e.* FROM employees e"),
    ("dangerous function", "SELECT load_extension('evil.so')"),
    ("readfile", "SELECT readfile('/etc/passwd')"),
    ("garbage", "this is not sql at all ###"),
    ("empty", "   "),
]

MUST_ALLOW = [
    ("simple count", "SELECT COUNT(*) FROM employees"),
    ("group by join",
     "SELECT d.name, COUNT(e.id) FROM employees e JOIN departments d ON d.id = e.department_id GROUP BY d.name"),
    ("leave aggregate",
     "SELECT leave_type, COUNT(id) FROM leave_requests WHERE status = 'PENDING' GROUP BY leave_type"),
    ("skills search",
     "SELECT e.name, s.name FROM employees e JOIN employee_skills es ON es.employee_id = e.id "
     "JOIN skills s ON s.id = es.skill_id WHERE s.normalized_name = 'python'"),
    ("cte", "WITH t AS (SELECT employee_id, COUNT(id) AS n FROM leave_requests GROUP BY employee_id) "
            "SELECT employee_id, n FROM t WHERE n > 2"),
    ("count star allowed", "SELECT COUNT(*) FROM leave_requests"),
]


def block_checks() -> None:
    for name, sql in MUST_BLOCK:
        r = validate_sql(sql, ADMIN, user_id=1)
        check(f"block[admin]: {name}", not r.ok, r.error_code or "ALLOWED!")
        # And blocked for manager too (defense in depth, different path).
        rm = validate_sql(sql, MANAGER, user_id=2)
        if rm.ok:
            check(f"block[manager]: {name}", False, "ALLOWED!")


def allow_checks() -> None:
    for name, sql in MUST_ALLOW:
        r = validate_sql(sql, ADMIN, user_id=1)
        check(f"allow[admin]: {name}", r.ok, r.error_code or "")
        if r.ok:
            check(f"limit injected: {name}", "LIMIT" in r.sql.upper(), r.sql[-40:])


def limit_checks() -> None:
    r = validate_sql("SELECT id FROM employees LIMIT 5000", ADMIN, user_id=1)
    check("oversized LIMIT capped", r.ok and f"LIMIT {MAX_ROWS}" in r.sql.upper(), (r.sql or "")[-30:])
    r = validate_sql("SELECT id FROM employees LIMIT 10", ADMIN, user_id=1)
    check("small LIMIT preserved", r.ok and "LIMIT 10" in r.sql.upper(), (r.sql or "")[-30:])


def role_checks() -> None:
    r = validate_sql("SELECT COUNT(*) FROM employees", EMPLOYEE, user_id=3)
    check("employee refused with routing code",
          not r.ok and r.error_code == "ROLE_NOT_ALLOWED", str(r.error_code))

    # Manager scoping is a rewrite, not a prompt instruction.
    r = validate_sql("SELECT name FROM employees", MANAGER, user_id=2)
    scoped = r.ok and "manager_id = 2" in r.sql and "employees" in r.sql
    check("manager: employees rewritten to team-scoped subquery", scoped, (r.sql or "")[:110])

    r = validate_sql(
        "SELECT e.name, COUNT(l.id) FROM employees e JOIN leave_requests l "
        "ON l.employee_id = e.id GROUP BY e.name", MANAGER, user_id=2)
    check("manager: scope survives joins + alias",
          r.ok and "manager_id = 2" in r.sql, (r.sql or "")[:130])

    r = validate_sql("SELECT name FROM employees", ADMIN, user_id=1)
    check("admin: no scoping injected", r.ok and "manager_id" not in r.sql, (r.sql or "")[:80])

    # A manager cannot escape scope by re-stating a WHERE clause.
    r = validate_sql("SELECT name FROM employees WHERE manager_id != 2", MANAGER, user_id=2)
    check("manager: hostile WHERE still wrapped in scope subquery",
          r.ok and r.sql.count("manager_id") >= 2, (r.sql or "")[:140])


def main() -> None:
    block_checks()
    allow_checks()
    limit_checks()
    role_checks()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
