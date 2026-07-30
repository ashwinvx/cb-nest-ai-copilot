# AI Permissions Matrix — implementation

The matrix below is verbatim from the assignment brief. Our interpretation and
enforcement points are documented separately beneath it, so the spec and our
reading of it stay distinguishable.

## The matrix (spec)

| AI Capability | Employee | Manager | Admin |
|---|---|---|---|
| Ask HR policy questions | Yes | Yes | Yes |
| Ask own leave balance | Yes | Yes | Yes |
| Ask another employee's leave balance | No | Team only | Yes |
| View own project assignments | Yes | Yes | Yes |
| View all project assignments | No | Limited | Yes |
| Search employees by skill | Limited | Yes | Yes |
| Generate SQL over HR data | Limited | Limited | Yes |
| View raw SQL | No | Optional | Optional |
| Create own leave request | Yes | Yes | Yes |
| Approve/reject leave | No | Yes | Yes |
| Create ticket | Yes | Yes | Yes |
| Assign/update ticket | No | Yes | Yes |
| Create announcement | No | Yes | Yes |
| Assign employee to project | No | Yes | Yes |
| Access payroll data | Own only or blocked | Restricted | Admin only |
| Access bank/PAN/password fields | No | No | No |

> This table is byte-guarded. `tests/test_ai_permissions.py` hashes its lines
> (`MATRIX_GUARD_SHA256`) and fails if the table in CLAUDE.md changes, forcing a
> human to re-verify both code transcriptions before the change lands.

## Where enforcement lives

| Matrix row | Tool name in code | Enforcement point(s) |
|---|---|---|
| Ask HR policy questions | `ask_policy_question` | All roles; `/chat/policy` has no role gate (policies are company-wide) |
| Ask own leave balance | `get_my_leave_balance` | `permissions.TOOL_PERMISSIONS` → `api_tools` → `GET /leaves/balances/me` (self-scoped by JWT) |
| Ask another employee's leave balance | `get_employee_leave_balance` | Role set (manager/admin) + `is_direct_report_of` for team scope |
| View own project assignments | `get_my_project_assignments` | All roles; self-scoped by JWT |
| View all project assignments | `get_all_project_assignments` | Role set (manager/admin) |
| Search employees by skill | `search_employees_by_skill` | All roles; result breadth limited by the underlying endpoint |
| Generate SQL over HR data | `generate_sql` | `sql_agent` role gate + `sql_guardrails` allowlist + AST scoping |
| View raw SQL | `view_raw_sql` | `sql_agent` omits `sql` from the response for employees |
| Create own leave request | `create_leave_request` | Tool exposure + **confirmation gate** + `POST /leaves/requests` (identity from JWT) |
| Approve/reject leave | `approve_leave` / `reject_leave` | Tool exposure + `is_direct_report_of` + confirmation gate + endpoint RBAC |
| Create ticket | `create_ticket` | Matrix encoded; tool wrapper not yet implemented |
| Assign/update ticket | `assign_ticket` / `update_ticket` | Matrix encoded; tool wrapper not yet implemented |
| Create announcement | `create_announcement` | Matrix encoded; tool wrapper not yet implemented |
| Assign employee to project | `assign_employee_to_project` | Matrix encoded; tool wrapper not yet implemented |
| Access payroll data | `get_payroll_data` | Admin-only in the matrix code; **additionally, `payroll_records` is excluded from the SQL allowlist at every role including admin** |
| Access bank/PAN/password fields | `access_bank_pan_password` | Empty role set (nobody) + `FORBIDDEN_COLUMNS` denylist + allowlist omission |

Rows marked "not yet implemented" have their permissions encoded in
`permissions.TOOL_PERMISSIONS` and covered by the matrix-walking test, so adding
the tool wrapper later inherits the correct gating. The leave-related tools are
the ones wired end to end.

## How the qualitative cells are implemented

**"Limited" for employee SQL generation → refused, with routing.**
An employee asking a SQL question gets:

> SQL queries over HR data aren't available for your role. I can still help with
> your own information — for example, I can show your leave balance or your leave
> requests, or answer questions about HR policies.

We rejected silent self-scoping (rewriting the query to the employee's own rows).
It yields confidently wrong aggregates: "how many people are in Engineering?"
would answer `1`, with nothing signalling the result was narrowed. In a system
whose value is trustworthy HR answers, a wrong number is worse than a refusal —
and the employee's real needs are served better by the action agent's tools.

**"Limited" for manager SQL generation → allowed, AST-scoped.**
Managers are not refused. `sql_guardrails` rewrites every `employees` reference
into `(SELECT ... FROM employees WHERE manager_id = :me OR id = :me)`. Because
the rewrite happens on the parsed tree after generation, it propagates through
joins and aggregates and cannot be escaped by phrasing — a manager writing
`WHERE manager_id != 2` still has their query wrapped in the scope subquery.

**"Team only" → direct reports, enforced in the AI layer.**
`permissions.is_direct_report_of` compares `manager_id`. It is deliberately false
for self (you are not your own report) and for indirect reports (the matrix says
team, not subtree). This is **stricter than the REST API**: `POST
/leaves/requests/{id}/approve` checks role but not team membership, so any
manager could approve anyone's leave through the normal app. The AI layer closes
that gap for AI-initiated actions. Refusals for "not your report", "no such
request", and "not pending" are identical, so a manager cannot learn whether a
request exists outside their team.

**"Optional" for viewing raw SQL → shown to manager and admin.**
The API omits `sql` for employees (moot, since they are refused) and returns it
for manager/admin; `sql-result-table.tsx` renders the disclosure only when `sql`
is non-null, so the UI cannot leak what the API withheld.

**"Own only or blocked" / "Restricted" / "Admin only" for payroll → blocked
everywhere in SQL.** `payroll_records` and `employee_documents` are absent from
the SQL allowlist at every role including admin. Payroll access belongs in a
purpose-built endpoint with its own audit trail, not free-text SQL. Changing this
requires an explicit decision, not a quiet allowlist edit.

## Fail-closed properties

- A tool name absent from `TOOL_PERMISSIONS` is denied for every role.
- A table or column absent from the SQL allowlist is refused — so a future
  migration adding a sensitive column leaks nothing by default.
- An unparseable query is refused.
- A missing employee in the team check returns the same `False` as "not your
  report", so refusals never confirm existence.
- The 12 forbidden columns are checked independently of the allowlist, so both
  mechanisms would have to fail simultaneously.

## Verification

`tests/test_ai_permissions.py` walks every matrix cell (16 capabilities × 3
roles) against an **independent transcription** of the table, so a typo in either
`TOOL_PERMISSIONS` or the test fails the suite rather than mirroring the error.
It also asserts unknown tools are denied, `available_tools()` agrees with
`is_tool_allowed()`, and the team check behaves correctly for self, indirect
reports, and missing employees. Current: 75 checks, all passing.
