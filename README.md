<img width="2866" height="1274" alt="image" src="https://github.com/user-attachments/assets/4b4defd5-663f-45d1-b9e3-f9adbcfabbae" />

# CB Nest

**CB Nest** is a full-stack HR Management System built for hands-on learning. It covers real-world business workflows — employee lifecycle, attendance, leave approvals, payroll, ticketing, and more — using a modern stack (FastAPI + Next.js + Docker). Use it to understand how production-grade HRMS platforms work, and extend it with your own AI features.

> 📖 **New here?** Start with the [Learner Guide](docs/Learner_Guide.md) for a complete walkthrough of the project architecture, database, and how to explore the code.

## Overview

This project provides a working HRMS platform with authentication, employee operations, attendance, leave management, communication features, finance data views, and ticketing workflows.

It is designed as a practical base for AI feature integration (RAG, assistants, agent workflows) without rebuilding core HR modules from scratch.


## Tech Stack

- Frontend: Next.js 15, React 19, Tailwind CSS
- Backend: FastAPI, SQLAlchemy (async), Pydantic v2
- Database: SQLite
- Migrations: Alembic
- Orchestration: Docker Compose

## Features

- JWT auth with role-aware access (ADMIN, MANAGER, EMPLOYEE)
- Employee directory with search, filters, and pagination
- Attendance clock in/clock out with status and mode tracking
- Leave balances and leave request workflow
- Announcements and polls
- Team calendar (leaves, WFH, holidays, birthdays)
- My Profile edits, profile photo upload, job history, documents
- Finance views (salary, statutory, payroll history)
- Tickets with assignment, status updates, onboarding tasks
- HR policy upload/download library
- Admin/Manager employee document upload flow (APPOINTMENT, TAX, PAYSLIP, OTHER)
- My Documents with search, view, and download; delete is allowed only for `OTHER` document type
- Password-protected PDF payslips (DOB in `DD-MM-YY`) for generated and uploaded payslips
- Notification bell for announcements, polls, ticket assignment, ticket status, leave decision, and employee-document uploads by others (not self-uploads)
- AI contract stubs (`/api/v1/chat/*`) returning `501` for future implementation

## Repository Structure

```text
.
|-- backend/
|   |-- alembic/
|   |   |-- versions/
|   |   `-- env.py
|   |-- app/
|   |   |-- api/v1/endpoints/
|   |   |-- core/
|   |   |-- db/
|   |   |-- models/
|   |   |-- schemas/
|   |   `-- services/
|   |-- scripts/
|   |   `-- seed.py
|   |-- storage/
|   |   |-- hr-policies/
|   |   `-- profile-photos/
|   |-- .env.example
|   |-- alembic.ini
|   |-- Dockerfile
|   `-- requirements.txt
|-- frontend/
|   |-- app/
|   |   |-- announcements/
|   |   |-- attendance/
|   |   |-- dashboard/
|   |   |-- employees/
|   |   |-- finance/
|   |   |-- hr-policies/
|   |   |-- leaves/
|   |   |-- login/
|   |   |-- me/
|   |   |-- organization/
|   |   |-- polls/
|   |   |-- team-calendar/
|   |   `-- tickets/
|   |-- components/
|   |   |-- layout/
|   |   `-- ui/
|   |-- lib/
|   |   `-- api.ts
|   |-- Dockerfile
|   |-- middleware.ts
|   `-- package.json
|-- docs/
|   |-- api/
|   |-- Learner_Guide.md
|   |-- PRD.md
|   `-- db_tables_samples.md
|-- docker-compose.yml
`-- README.md
```

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2)
  - On Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure the **WSL 2 backend** is enabled
- **Git**


## Quick Start

First-time setup:

```bash
git clone <repo-url>
cd HRMS
cp backend/.env.example backend/.env
```


For PowerShell on Windows:

```powershell
Copy-Item backend/.env.example backend/.env
```

Then run from repository root:

```bash
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

Open:

- App: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API redoc: `http://localhost:8000/redoc`

Verify everything is working:

```bash
docker-compose ps
```

## Default Credentials

- Admin: `admin@mock-hrms.dev` / `password123`
- Manager: `manager@mock-hrms.dev` / `password123`
- Employee: `employee@mock-hrms.dev` / `password123`

## Configuration

Backend environment file: `backend/.env`

Use `backend/.env.example` as reference. Current key settings:

- `DATABASE_URL=sqlite+aiosqlite:///./storage/hrms.db`
- `APP_TIMEZONE=Asia/Kolkata`
- JWT settings (`JWT_SECRET_KEY`, expiry values)

## Common Commands

Start services:

```bash
docker-compose up -d
```

Restart API + Web after code changes:

```bash
docker compose restart api web
```

Stop services:

```bash
docker-compose down
```

Run migrations:

```bash
docker-compose exec api alembic -c alembic.ini upgrade head
```

Reseed data:

```bash
docker-compose exec api python scripts/seed.py
```

Optional one-time migration (legacy payslip files to DOB-password-protected PDFs):

```bash
docker compose exec api python scripts/migrate_payslips_to_encrypted_pdf.py
```

Check containers:

```bash
docker-compose ps
```

## Reset Database

On macOS/Linux:

```bash
docker-compose down
rm -f backend/storage/hrms.db
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

On PowerShell:

```powershell
docker-compose down
Remove-Item backend\storage\hrms.db -Force -ErrorAction SilentlyContinue
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

## API Notes

- API base path: `/api/v1`
- Health checks:
  - `/health`
  - `/api/v1/health`
- Standard response envelope:
  - Success: `{ "success": true, "data": ..., "error": null }`
  - Error: `{ "success": false, "data": null, "error": { "code": "...", "message": "..." } }`
- Document uploads:
  - Employee self-upload: `POST /api/v1/employees/me/documents`
  - Employee self-delete: `DELETE /api/v1/employees/me/documents/{document_id}` (`OTHER` type only)
  - Admin/Manager upload for any employee: `POST /api/v1/employees/{employee_id}/documents`
  - Admin/Manager payslip upload: `POST /api/v1/employees/{employee_id}/documents/payslip`

## AI Copilot

Three agents sit on top of the existing HR modules. None of them writes to
the database directly: actions go through the existing REST endpoints with
the caller's own JWT, and the SQL agent is read-only.

| Endpoint | Agent | Notes |
|---|---|---|
| `POST /api/v1/chat/policy` | Policy RAG | Answers HR policy questions with citations. No tools. |
| `POST /api/v1/chat/sql` | SQL agent | Read-only SELECT over an allowlisted schema. |
| `POST /api/v1/chat/actions` | HR actions | Leave balance/requests, apply, approve/reject. |
| `POST /api/v1/chat/actions/confirm` | — | Executes a pending action after user confirmation. |

Setup: copy `backend/.env.example` to `backend/.env` and set
`ANTHROPIC_API_KEY`, then build the policy index (re-run after changing
any file in `backend/storage/hr-policies/`):

```bash
cd backend && python -m scripts.ingest_policies
```

### Confirmation gate for state-changing actions

The action agent never executes a create/approve/reject directly. It
returns a signed, user-bound, expiring `pending_action` describing the
exact call; the client must POST that token to `/chat/actions/confirm`
before anything happens. The gate is server-side interception, not a
prompt instruction, so a prompt-injected model cannot talk its way past
it.

Action tokens are **single-use**, enforced by a UNIQUE constraint on
`ai_action_claims.jti`: consuming a token means inserting its id, so a
replay is rejected by the database rather than by a check-then-act
race. Declining consumes the token too — a cancelled action can never
be replayed as an approval. A consumed token is indistinguishable from
an invalid one in the response.

### Deliberate design decisions

These are intentional calls, not unimplemented features:

- **Employees are refused SQL generation** (the permissions matrix grades
  employee SQL as "Limited"). The alternative — silently rewriting an
  employee's query to their own rows — produces confidently wrong
  answers: "how many people are in Engineering?" would return `1` with no
  indication the result was narrowed. In a system whose value is
  trustworthy HR answers, a wrong number is worse than a refusal. The
  refusal therefore routes the user to what does work: their leave
  balance and leave requests (via the action agent) and HR policy
  questions (via the policy agent). Managers are not refused — every
  `employees` reference in their query is rewritten by AST into a
  team-scoped subquery, which propagates through joins and aggregates.
  Seed data supports this demo: `manager@mock-hrms.dev` has 17 direct
  reports across several departments, while a second seeded manager
  (`ops.manager@mock-hrms.dev`) absorbs the remaining ~983 generated
  employees. Asking "how many employees are in each department?" returns
  Engineering 402 / Finance 201 / … as admin, and Engineering 8 /
  Finance 5 / … as the demo manager — same question, same generated SQL,
  scoped result.
- **`payroll_records` and `employee_documents` are excluded from the SQL
  allowlist at every role, including admin.** Payroll access belongs in a
  purpose-built endpoint with its own audit trail, not free-text SQL.
- **Allowlist over denylist.** CLAUDE.md's 12 forbidden columns are
  enforced explicitly, but they are not sufficient for this schema
  (`payroll_records.net`, `employees.bank_name`, `email`, `phone` are all
  sensitive and absent from that list), so only explicitly allowed
  tables/columns pass. New columns added by future migrations fail closed
  rather than leaking by default.
- **Four independent layers stop a dangerous query**: the model's schema
  omits forbidden columns entirely; sqlglot AST validation rejects
  non-SELECT, multi-statement, and out-of-allowlist queries; the database
  connection is opened read-only (`mode=ro`) so writes fail even if
  parsing were bypassed; and every result set is row-capped.

### Audit trail

Every AI interaction writes an `ai_audit_logs` row: user, role, endpoint,
sanitized message, intent, tool, status (`SUCCESS` / `REFUSED` /
`BLOCKED` / `ERROR`), record IDs, and — for SQL turns — the sanitized
generated query. Blocked queries are logged *with* their SQL text, since
an attempted `SELECT bank_account_number ...` is the most valuable row in
the table. Secrets, tokens, PAN, and account numbers are redacted before
insert; tool results and payroll values are never stored.

## Troubleshooting

- If frontend shows stale build/runtime issues:
  - `docker-compose restart web`
- If API changes are not reflected:
  - `docker-compose restart api`
- If migration or seed fails:
  - reset DB using the commands above, then migrate and seed again

## Documentation

- Learner guide: [`Learner_Guide.md`](docs/Learner_Guide.md) — full project walkthrough, architecture, database schema, learning path
- Product requirements: [`PRD.md`](docs/PRD.md)
- Database schema reference: [`db_tables_samples.md`](docs/db_tables_samples.md)
- AI chat endpoint contracts: `docs/api/`
- AI architecture: [`ai_architecture.md`](docs/ai_architecture.md) — components, request flow, security layering
- AI permissions: [`ai_permissions_matrix.md`](docs/ai_permissions_matrix.md) — matrix and where each row is enforced
- AI evaluation results: [`ai_eval_results.md`](docs/ai_eval_results.md) — measured test output, security prompts, known limitations
- Demo script: [`demo_script.md`](docs/demo_script.md) — timed 5–8 minute run order


Copyright (c) Codebasics. All rights reserved.


