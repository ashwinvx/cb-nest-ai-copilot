"""SQL agent paths that a well-behaved model never reaches.

The live suite shows the model refuses hostile prompts at generation,
so the guardrail-blocked branch needs a stubbed model to exercise. This
verifies the contract Ashwin asked to confirm: a blocked query is
audited with status BLOCKED, the offending SQL text, and a specific
error code — with secrets sanitized out of the stored SQL.
Run: .venv/bin/python -m tests.test_sql_agent
"""

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select

import app.services.ai.sql_agent as agent
from app.db.session import SessionLocal
from app.models.ai_audit_log import AIAuditLog, AIAuditStatus
from app.models.enums import Role

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Response:
    content: list
    stop_reason: str = "end_turn"


class _StubMessages:
    def __init__(self, sql: str) -> None:
        self._sql = sql
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        # First call = generation; later calls = summarization.
        text = self._sql if self.calls == 1 else "Summary of results."
        return _Response(content=[_Block(text=text)])


class _StubClient:
    def __init__(self, sql: str) -> None:
        self.messages = _StubMessages(sql)


async def run_with_sql(db, sql: str, role=Role.ADMIN, user_id: int = 1):
    original = agent._client
    agent._client = lambda: _StubClient(sql)  # type: ignore[assignment]
    try:
        return await agent.run_sql_agent(db, user_id=user_id, role=role, message="test question")
    finally:
        agent._client = original  # type: ignore[assignment]


async def latest_sql_audit(db) -> AIAuditLog | None:
    rows = (await db.execute(
        select(AIAuditLog).where(AIAuditLog.endpoint == "sql")
        .order_by(AIAuditLog.id.desc()).limit(1)
    )).scalars().all()
    return rows[0] if rows else None


CASES = [
    ("destructive statement", "DROP TABLE employees", "NON_SELECT"),
    ("stacked statements", "SELECT id FROM employees; DELETE FROM leave_requests", "MULTI_STATEMENT"),
    ("forbidden column", "SELECT bank_account_number FROM employees", "FORBIDDEN_COLUMN"),
    ("excluded table", "SELECT net FROM payroll_records", "TABLE_NOT_ALLOWED"),
    ("star", "SELECT * FROM employees", "STAR_NOT_ALLOWED"),
]


async def blocked_paths() -> None:
    async with SessionLocal() as db:
        for name, sql, expected_code in CASES:
            result = await run_with_sql(db, sql)
            check(f"blocked[{name}]: no rows, no sql returned",
                  result["row_count"] == 0 and result["sql"] is None and not result["rows"],
                  result["answer"][:60])

            row = await latest_sql_audit(db)
            check(f"blocked[{name}]: audited BLOCKED with code {expected_code}",
                  row is not None
                  and row.action_status is AIAuditStatus.BLOCKED
                  and row.error_code == expected_code,
                  f"{row.action_status if row else None}/{row.error_code if row else None}")
            check(f"blocked[{name}]: offending SQL stored",
                  row is not None and row.generated_sql and sql.split()[0].lower() in row.generated_sql.lower(),
                  (row.generated_sql or "")[:60] if row else "")

        # Sanitization applies to stored SQL: a PAN literal the model
        # copied from the user's question must not persist verbatim.
        await run_with_sql(db, "SELECT id FROM employees WHERE pan_number = 'ABCDE1234F'")
        row = await latest_sql_audit(db)
        stored = (row.generated_sql or "") if row else ""
        check("blocked: PAN literal redacted in stored SQL",
              "ABCDE1234F" not in stored and "REDACTED" in stored, stored[:80])

        # Good SQL still executes and audits SUCCESS with the final SQL.
        result = await run_with_sql(db, "SELECT COUNT(id) AS n FROM employees")
        row = await latest_sql_audit(db)
        check("allowed: executed, audited SUCCESS, LIMIT applied",
              result["row_count"] > 0
              and row is not None and row.action_status is AIAuditStatus.SUCCESS
              and "LIMIT" in (row.generated_sql or "").upper(),
              (row.generated_sql or "")[:70] if row else "")

        # Manager scoping is applied to the executed + audited SQL.
        result = await run_with_sql(db, "SELECT name FROM employees", role=Role.MANAGER, user_id=2)
        row = await latest_sql_audit(db)
        check("manager: stored SQL carries the scope predicate",
              row is not None and "manager_id = 2" in (row.generated_sql or ""),
              (row.generated_sql or "")[:90] if row else "")


def main() -> None:
    asyncio.run(blocked_paths())
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
