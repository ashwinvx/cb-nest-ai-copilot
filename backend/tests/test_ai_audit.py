"""Sanitizer + structural tests for app/services/ai/audit.py.

Feeds hostile inputs through log_ai_interaction against an in-memory DB
and asserts nothing sensitive survives to the stored row. Run with:
    .venv/bin/python -m tests.test_ai_audit
"""

import asyncio
import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai_audit_log import AIAuditLog, AIAuditStatus
from app.models.employee import Employee
from app.models.enums import Role
from app.services.ai.audit import _redact, log_ai_interaction

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        failures.append(name)


JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIzIiwicm9sZSI6IkFETUlOIn0.abc123DEF-_456"

REDACTION_CASES = [
    ("pasted JWT", f"my token is {JWT}", ["eyJ"]),
    ("bearer header", "use Bearer abc.def.ghi-jkl to auth", ["abc.def"]),
    ("password colon", "my password: hunter2secret please", ["hunter2secret"]),
    ("password equals", "PASSWORD=Sup3rS3cret!", ["Sup3rS3cret"]),
    ("PAN number", "what is Rahul's PAN ABCDE1234F?", ["ABCDE1234F"]),
    ("lowercase pan", "pan is abcde1234f", ["abcde1234f"]),
    ("IFSC code", "transfer via HDFC0001234 branch", ["HDFC0001234"]),
    ("bank account", "account 123456789012 belongs to me", ["123456789012"]),
    ("spaced account", "acct no 1234 5678 9012", ["1234 5678 9012"]),
    ("phone number", "call me at 9876543210", ["9876543210"]),
]


def redact_checks() -> None:
    for name, text, secrets in REDACTION_CASES:
        out = _redact(text)
        leaked = [s for s in secrets if s in out]
        check(f"redact: {name}", not leaked and "REDACTED" in out, out)

    check("redact: None passthrough", _redact(None) is None)
    dates = "apply casual leave from 2026-08-03 to 2026-08-05"
    check("redact: ISO dates survive (8 digits, not 9)", _redact(dates) == dates,
          _redact(dates))
    date_range = "worked between 2026-07-01 and 2026-07-29"
    check("redact: date ranges survive", _redact(date_range) == date_range)
    adjacent = "2026-07-01 - 2026-07-29"
    check("redact: adjacent dashed dates survive", _redact(adjacent) == adjacent,
          _redact(adjacent))
    benign = "How many casual leaves do I have left this year?"
    check("redact: benign message untouched", _redact(benign) == benign)
    small_ids = "approve leave request 42 for employee 7"
    check("redact: short ids survive", _redact(small_ids) == small_ids)
    check("redact: truncates to 4000", len(_redact("x" * 9000)) == 4000)


async def row_checks() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Employee.__table__.create(c))
        await conn.run_sync(lambda c: AIAuditLog.__table__.create(c))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        db.add(Employee(
            id=1, name="u", email="u@t.dev", hashed_password="x",
            role=Role.EMPLOYEE, joining_date=date(2024, 1, 1),
        ))
        await db.commit()

        entry = await log_ai_interaction(
            db,
            user_id=1,
            role=Role.EMPLOYEE,
            endpoint="sql",
            message=f"run this with my password: hunter2 and token {JWT}",
            status=AIAuditStatus.BLOCKED,
            detected_intent="sql_query",
            tool_name="generate_sql",
            generated_sql="SELECT pan_number FROM employees WHERE pan_number = 'ABCDE1234F' AND phone = '9876543210'",
            record_ids=[7, "DROP TABLE", 9, True, {"x": 1}],
            error_code="FORBIDDEN_COLUMN",
        )

        stored = (await db.execute(
            select(AIAuditLog).where(AIAuditLog.id == entry.id)
        )).scalar_one()

        check("row: password scrubbed from message", "hunter2" not in stored.message, stored.message)
        check("row: JWT scrubbed from message", "eyJ" not in stored.message)
        check("row: SQL literal PAN scrubbed", "ABCDE1234F" not in stored.generated_sql, stored.generated_sql)
        check("row: SQL literal phone scrubbed", "9876543210" not in stored.generated_sql)
        check("row: SQL structure preserved",
              "SELECT pan_number FROM employees" in stored.generated_sql)
        check("row: record_ids coerced to ints only", stored.record_ids == [7, 9],
              str(stored.record_ids))
        check("row: status stored", stored.action_status is AIAuditStatus.BLOCKED)
        check("row: no result/response columns exist",
              not any(c in AIAuditLog.__table__.columns
                      for c in ("result", "response", "tool_result", "output")))

    await engine.dispose()


def main() -> None:
    redact_checks()
    asyncio.run(row_checks())
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
