# AI Copilot — Architecture

Three agents sit on top of the existing CB Nest HRMS. The governing rule is that
**agents never write to the database directly**: every state change goes through
an existing REST endpoint carrying the logged-in user's JWT, so the app's
validation, RBAC, and business rules remain the source of truth.

## Components

```
backend/app/services/ai/
  policy_rag.py        Policy Q&A over the document corpus (no tools)
  embeddings.py        Local sentence-transformers, swappable interface
  vector_store.py      Brute-force cosine store, JSON persistence
  sql_agent.py         NL -> validated SELECT -> answer
  sql_guardrails.py    Allowlist + AST validation + role scoping (pure)
  action_agent.py      NL -> proposed HR action -> confirmed execution
  api_tools.py         HTTP wrappers over existing REST endpoints
  pending_actions.py   Signed single-use confirmation tokens
  permissions.py       The AI Permissions Matrix as code
  audit.py             Sanitizing audit writer
```

## Request flow

```mermaid
flowchart TD
    U[User in AI Copilot UI] -->|JWT| API[FastAPI /api/v1/chat/*]

    API --> P[/chat/policy]
    API --> S[/chat/sql]
    API --> A[/chat/actions]
    API --> C[/chat/actions/confirm]

    P --> PR[policy_rag]
    PR --> VS[vector_store<br/>cosine search]
    VS -->|below threshold| NOANS[No LLM call:<br/>'not in the policies']
    VS -->|hits| WRAP[Wrap chunks in<br/>policy_document tags]
    WRAP --> LLM1[Claude: answer + cite]

    S --> SA[sql_agent]
    SA --> GEN[Claude: NL -> SELECT<br/>sees allowlisted schema only]
    GEN --> GR[sql_guardrails<br/>AST validate + scope + LIMIT]
    GR -->|blocked| BLK[Refusal, audited BLOCKED]
    GR -->|ok| RO[(SQLite mode=ro<br/>read-only connection)]
    RO --> LLM2[Claude: summarize rows]

    A --> AA[action_agent]
    AA --> TOOLS[Claude with role-filtered tools]
    TOOLS -->|read tool| RT[api_tools -> REST endpoint]
    TOOLS -->|mutating tool| INT[Intercepted: NOT executed]
    INT --> TOK[Signed pending_action token]
    TOK --> U

    C --> CLAIM{claim jti<br/>UNIQUE insert}
    CLAIM -->|already used| REJ[Rejected as invalid]
    CLAIM -->|first use| DISP[api_tools -> REST endpoint -> DB]

    PR -.-> AUD[(ai_audit_logs)]
    SA -.-> AUD
    AA -.-> AUD
    C -.-> AUD
```

### Policy RAG — `POST /chat/policy`

1. Embed the question locally (`all-MiniLM-L6-v2`).
2. Cosine search the index; **below the score threshold the model is never
   called** — the endpoint answers "I don't find that in the company policies."
3. Retrieved chunks are wrapped in `<policy_document>` tags **inside the user
   turn**, with tag-breakout sequences neutralized so a document cannot close
   the envelope and impersonate the prompt.
4. Claude answers with citations. The agent has **no tools**.
5. Audit row written.

### SQL Agent — `POST /chat/sql`

1. Role gate: employees are refused and routed to the agents that serve them.
2. Claude generates one SELECT, seeing **only the allowlisted schema** — so
   forbidden columns are absent from the model's world.
3. `sql_guardrails.validate_sql` parses with sqlglot and enforces: one
   statement, SELECT-rooted, no destructive node anywhere (including CTEs and
   subqueries), allowlisted tables/columns/functions, no `SELECT *`, `LIMIT 200`.
   For managers, every `employees` reference is rewritten into a team-scoped
   subquery.
4. Execution on a connection opened **read-only at the SQLite level**.
5. Claude summarizes the rows. Raw DB errors never reach the user.

### Action Agent — `POST /chat/actions` + `/chat/actions/confirm`

1. The model is offered **only the tools its role permits**, so an employee's
   agent has no approve tool to be prompt-injected into calling.
2. Read tools execute inline via `api_tools` (existing REST endpoints, user's JWT).
3. **Mutating tools are intercepted server-side and not executed.** The response
   carries a signed `pending_action` (user-bound, 10-minute expiry) with the
   exact arguments and a human-readable summary.
4. `/chat/actions/confirm` consumes the token — an INSERT into `ai_action_claims`
   whose UNIQUE `jti` makes replay a database-level impossibility — then
   dispatches through the same tool layer. **Declining consumes the token too.**

## Security layering

Each agent has independent layers, so no single failure is fatal.

| Layer | Policy RAG | SQL Agent | Action Agent |
|---|---|---|---|
| 1. Capability | No tools at all | Read-only by construction | Tools filtered by role before the request is built |
| 2. Input framing | Chunks tagged as data, breakout neutralized | Model sees allowlisted schema only | Tool schemas omit `token`/`db`/`employee_id` |
| 3. Validation | — | sqlglot AST: statement/table/column/function | Tool layer re-checks role and team scope |
| 4. Execution | — | Connection opened `mode=ro` | Existing REST endpoints keep their own RBAC |
| 5. Consent | — | — | Signed single-use confirmation token |
| 6. Record | Audited | Audited incl. blocked SQL text | Audited: propose / confirmed / declined / replayed |

**Identity is structural, not prompted.** No tool accepts an `employee_id`; the
caller's JWT determines identity, so "apply leave for Rahul" is not something the
model can express, let alone be talked into.

## Data

| Table | Purpose |
|---|---|
| `ai_audit_logs` | One row per interaction: user, role, endpoint, sanitized message, intent, tool, status, sanitized SQL, record IDs, error code. No column exists for tool results. |
| `ai_action_claims` | One row per consumed confirmation token; UNIQUE `jti` is the single-use enforcement. |
| `storage/hr-policies/` | Committed policy corpus (authored fixtures — see CLAUDE.md). |
| `storage/policy_index.json` | Derived vector index, gitignored, rebuilt by `scripts/ingest_policies.py`. |

## Frontend

`/ai-copilot` with three explicit mode tabs rather than a unified router, so each
agent's behavior is individually observable. Components: `chat-panel`
(transcript, generic over message type), `source-list` (citations),
`sql-result-table` (rows + View SQL disclosure, shown only when the API returns
`sql`), `action-result-card` (the confirmation gate; resolution state lives on
the message, not in the component).
