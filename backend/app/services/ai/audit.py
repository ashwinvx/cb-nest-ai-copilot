"""Write-side of the AI audit trail (model: app.models.ai_audit_log).

Enforcement of "never log secrets, JWTs, passwords, bank/PAN numbers,
or payroll details" (CLAUDE.md) is two-layered:

  1. Structural: log_ai_interaction's signature has no parameter that
     could carry a tool result, agent response, or result set, and
     record_ids is coerced to a list of ints. What can't be passed
     can't be logged.
  2. Sanitization: the two free-text fields (message, generated_sql)
     are scrubbed by _redact before insert — the user may have typed a
     credential into their own message, or the LLM may have copied one
     into a SQL literal.

This module writes to the DB directly. That is intentional and allowed:
the audit table is AI-layer infrastructure owned by this package, not
HR data — agents themselves still never touch a session.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_audit_log import AIAuditLog, AIAuditStatus
from app.models.enums import Role

# Order matters: token/credential patterns run before the digit-run
# catch-all so they get the more specific label.
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # JWTs (three dot-separated base64url segments, header starts eyJ)
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[REDACTED_TOKEN]"),
    # Bearer <anything token-like>
    (re.compile(r"(?i)bearer\s+[\w.~+/-]+=*"), "[REDACTED_TOKEN]"),
    # password/passwd/pwd followed by separator and a value
    (re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]?\s*\S+"), "[REDACTED_CREDENTIAL]"),
    # Indian PAN: 5 letters, 4 digits, 1 letter
    (re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b"), "[REDACTED_PAN]"),
    # IFSC: 4 letters, 0, 6 alphanumerics
    (re.compile(r"\b[A-Za-z]{4}0[A-Za-z0-9]{6}\b"), "[REDACTED_IFSC]"),
    # Runs of >=9 digits (account numbers, phone numbers), allowing one
    # space/dash between digits. Digit count, not length: ISO dates have
    # 8 digits and must survive — audit messages are full of them.
    (re.compile(r"\b(?:\d[ \-]?){8,}\d\b"), "[REDACTED_NUMBER]"),
]

_MAX_TEXT_LEN = 4000


def _redact(text: str | None) -> str | None:
    if text is None:
        return None
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:_MAX_TEXT_LEN]


def _coerce_record_ids(record_ids: object) -> list[int] | None:
    """Keep only ints — anything else is silently dropped, so sensitive
    values can never ride along in the record-id list."""
    if not isinstance(record_ids, (list, tuple, set)):
        return None
    ints = [i for i in record_ids if isinstance(i, int) and not isinstance(i, bool)]
    return ints or None


async def log_ai_interaction(
    db: AsyncSession,
    *,
    user_id: int,
    role: Role,
    endpoint: str,
    message: str,
    status: AIAuditStatus,
    detected_intent: str | None = None,
    tool_name: str | None = None,
    generated_sql: str | None = None,
    record_ids: list[int] | None = None,
    error_code: str | None = None,
) -> AIAuditLog:
    """Persist one audit row. Never raises into the caller's request
    flow is the caller's concern; this function commits its own row."""
    entry = AIAuditLog(
        user_id=user_id,
        role=role,
        endpoint=endpoint[:40],
        message=_redact(message) or "",
        detected_intent=detected_intent[:80] if detected_intent else None,
        tool_name=tool_name[:80] if tool_name else None,
        action_status=status,
        generated_sql=_redact(generated_sql),
        record_ids=_coerce_record_ids(record_ids),
        error_code=error_code[:40] if error_code else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry
