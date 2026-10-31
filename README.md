# NEXUS AI — Autonomous AI Agents for Enterprise Operations

A working multi-agent enterprise automation platform, not a dashboard mock-up.
A natural-language business request is planned by a **Planner Agent**, routed
through a **LangGraph orchestrator** to specialised HR, Document, IT, Finance and
Customer-Support agents, **paused at human-approval checkpoints** for sensitive
actions, executed against a **permission-checked tool registry** fronting
simulated enterprise systems, protected by **retry with exponential backoff,
idempotency keys and compensation rollbacks**, recorded in an **append-only audit
trail**, and finally rendered as a downloadable execution report.

> **Sandbox guarantee.** Every integration (`*.sandbox.nexus-ai.example`) is a
> simulated adapter returning synthetic data. No production HR, finance, CRM, IT,
> document or mail system is contacted, and no report ever claims otherwise — each
> final report carries an explicit `simulation_notice`.

| | |
|---|---|
| Frontend | `frontend/` — React 19, TypeScript, Vite 8, Tailwind v4, Lucide, Recharts, @xyflow/react |
| Backend | `backend/` — Python 3.11+, FastAPI, LangGraph 1.2, SQLAlchemy 2, Pydantic v2 |
| Data | SQLite (default) or PostgreSQL 16 · Redis optional · LangGraph SQLite checkpointer |
| LLM | Gemini / OpenAI / Ollama / **none** (deterministic rule planner) — switchable at runtime |
| Auth | JWT bearer (HS256), PBKDF2-SHA256 passwords, 4 roles, capability permissions |
| API docs | http://localhost:8000/api/docs (Swagger) · `/api/redoc` · `/api/openapi.json` |

---

## 1. Contents of this repository

```
.
├── .env.example              # every supported environment variable, documented
├── docker-compose.yml        # db (postgres) + redis + api + web
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py           # FastAPI app, /api/health, /api/architecture, SPA fallback
│   │   ├── config.py         # pydantic-settings; secrets from env only
│   │   ├── database.py       # engine, SQLite WAL pragmas, session scope
│   │   ├── models.py         # 13 tables: FKs, indexes, timestamps
│   │   ├── schemas.py        # request/response models (input validation)
│   │   ├── security.py       # PBKDF2 hashing, JWT issue/verify
│   │   ├── rbac.py           # role → permission definitions
│   │   ├── deps.py           # auth dependency, has_permission(), DB session
│   │   ├── serializers.py    # workflow/detail/timeline payloads
│   │   ├── seed.py           # roles, 4 demo users, 9 agents, 22 tools
│   │   ├── agents/           # catalog.py (9 agent specs) + planner.py
│   │   ├── llm/provider.py   # Gemini / OpenAI / Ollama / none behind one interface
│   │   ├── graph/            # state.py, orchestrator.py, recovery.py, runtime.py
│   │   ├── tools/            # definitions.py, registry.py, adapters.py, mock_data.py
│   │   ├── services/         # audit.py, approvals.py, workflows.py, reports.py
│   │   └── api/              # auth, workflows, approvals, catalog, audit,
│   │                         # dashboard, reports, settings routers
│   ├── scripts/demo_scenarios.py  # end-to-end API demo of the 3 reference scenarios
│   └── tests/                # 29 pytest cases (API + orchestrator)
└── frontend/
    ├── Dockerfile · nginx.conf
    └── src/
        ├── api/              # client.ts (typed fetch) · types.ts (backend contracts)
        ├── components/       # Layout, Sidebar, Topbar, StageFlow (React Flow), ui, charts
        ├── lib/              # hooks.ts (usePoll, auth, theme) · format.ts · icons.ts
        ├── pages/            # the 10 sidebar pages + LoginPage, CreateWorkflowPage, WorkflowDetailPage
        └── state/            # AuthContext.tsx · ThemeContext.tsx · ToastContext.tsx
```

---

## 2. Quick start

### Option A — Docker (PostgreSQL + Redis, one command)

```bash
cp .env.example .env          # then set SECRET_KEY (see §4)
docker compose up --build
```

* Web UI → http://localhost:3000
* API + Swagger → http://localhost:8000/api/docs
* Postgres is published on `127.0.0.1:5432` only, for inspection.

Compose runs `db` first, waits for `api` to pass its `/api/health` check, then
starts `web`. The API container creates the schema and seeds reference data on
boot; `app_data:/app/data` keeps LangGraph checkpoints and generated documents
across restarts, so a workflow parked at an approval can still be resumed after
`docker compose restart`.

```bash
docker compose logs -f api    # orchestrator + request log
docker compose down           # keeps volumes
docker compose down -v        # deletes the demo data too
```

The API deliberately runs a **single uvicorn worker**: workflow execution lives in
that process's thread pool and the checkpointer is a local SQLite file, so extra
workers would each hold a different view of the same run.

### Option B — Local development (no Docker, no database server)

```bash
# 1. backend — SQLite at backend/data/nexus.db
python -m venv .venv
source .venv/bin/activate                      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload --port 8000      # http://127.0.0.1:8000/api/docs

# 2. frontend — separate shell
cd frontend
npm install
npm run dev                                    # http://localhost:5173
```

`vite.config.ts` proxies `/api` to `http://127.0.0.1:8000`, so the browser stays
single-origin. **No API key is required** — with `LLM_PROVIDER=auto` and no keys
present, the deterministic planner takes over and every scenario still runs.

To use an LLM instead, put one of these in `.env` and restart:

```bash
GEMINI_API_KEY=…                 # + GEMINI_MODEL=gemini-2.0-flash
OPENAI_API_KEY=…                 # + OPENAI_MODEL=gpt-4o-mini
OLLAMA_BASE_URL=http://127.0.0.1:11434   # + OLLAMA_MODEL=llama3.1
```

Settings → *LLM providers* lets an admin test and switch provider at runtime
(`PUT /api/settings/llm/provider`) without a restart.

### Production build served by the API

```bash
cd frontend && npm run build     # tsc -b && vite build → frontend/dist
```

`app/main.py` detects a sibling `frontend/dist` and serves it from the same
origin (static assets mounted at `/assets`, SPA fallback on every other path), so
a single container can expose the whole platform.

---

## 3. Demo accounts

Seeded by `backend/app/seed.py`. The shared password comes from `DEMO_PASSWORD`
(default `NexusDemo2026!`) and exists only for this synthetic sandbox.

| Email | Name | Role | Can do |
|---|---|---|---|
| `admin@nexus-ai.example` | Dana Whitfield | **admin** | Everything, incl. registry/settings writes and any checkpoint |
| `approver@nexus-ai.example` | Samuel Okonjo | **approver** | Decide checkpoints, grant elevated capability to a workflow, read all |
| `operator@nexus-ai.example` | Leena Kapoor | **operator** | Start and monitor workflows; **cannot self-approve** |
| `viewer@nexus-ai.example` | Tomas Berg | **viewer** | Read-only dashboards, reports, audit |

`GET /api/auth/demo-accounts` returns this list at runtime.

---

## 4. Environment configuration

Every variable is documented in [`.env.example`](.env.example); copy it to `.env`.
The backend reads `.env` and `../.env` (pydantic-settings), so one root file
serves both local and Docker runs. **Keys are never hardcoded** — no fallback
secrets exist in source.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/nexus.db` | `postgresql+psycopg2://user:pass@host:5432/nexus` for Postgres |
| `REDIS_URL` | *(unset)* | Optional; execution uses the in-process worker pool either way |
| `SECRET_KEY` | generated at boot | **Set it in production.** Unset → random key per start, which invalidates existing tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | JWT lifetime |
| `JWT_ALGORITHM` | `HS256` | |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated |
| `LLM_PROVIDER` | `auto` | `auto` \| `gemini` \| `openai` \| `ollama` \| `none` |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-2.0-flash` | |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | — / `gpt-4o-mini` / OpenAI | `OPENAI_BASE_URL` targets any OpenAI-compatible gateway |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | — / `llama3.1` | Empty URL = not configured |
| `LLM_TIMEOUT_SECONDS` | `60` | Provider failure degrades to the rule planner, it does not fail the workflow |
| `MAX_TASK_ATTEMPTS` | `3` | Retry ceiling for `retry_safe` tools |
| `RETRY_BASE_DELAY_SECONDS` / `RETRY_BACKOFF_FACTOR` | `0.5` / `2.0` | `delay = base × factor^(attempt-1)` |
| `CHECKPOINT_DATABASE_PATH` | `./data/nexus_checkpoints.db` | LangGraph SQLite checkpointer (see §5) |
| `GENERATED_DOCUMENTS_DIR` | `./data/generated_documents` | Offer letters, onboarding packs, invoice summaries |
| `WORKFLOW_ESCALATION_EMAIL` | `it-administrator@nexus-ai.example` | Target of the escalation notification |
| `SEED_DEMO_DATA` | `true` | Reference data only — never workflows |
| `DEMO_PASSWORD` | `NexusDemo2026!` | Password for the four synthetic accounts |
| `ENVIRONMENT` / `DEBUG` / `SQLALCHEMY_ECHO` | `development` / `true` / `false` | `DEBUG=false` hides exception detail from responses |

Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

---

## 5. Database configuration

The schema is created with `Base.metadata.create_all()` during `bootstrap()` on
startup — no migration step is needed for a fresh environment.

**13 tables**, all with timestamps and indexed lookups
([`backend/app/models.py`](backend/app/models.py)):

| Table | Purpose | Key relationships |
|---|---|---|
| `roles` | Capability permission lists | ← `users` (RESTRICT) |
| `users` | Local accounts, PBKDF2 hashes | `role_id` → `roles` |
| `workflows` | One natural-language request and its run | `user_id` → `users` (CASCADE) |
| `workflow_tasks` | Planner tasks, deps, attempts, status | `workflow_id` → `workflows`; composite `ix_task_workflow_status` |
| `agents` | Nine agent definitions + scoped tool allow-lists | ← `agent_executions` |
| `agent_executions` | Per-agent reasoning and outcome | `workflow_id`, `agent_id` |
| `approvals` | Checkpoints: policy reason, risk, decision, comment | `workflow_id`, `decided_by` → `users` |
| `integrations` | Six simulated enterprise systems | ← `tool_registry` |
| `tool_registry` | 22 tools: schema, permission, risk, retry/reversible flags | `integration_id` |
| `tool_calls` | Every execution incl. idempotency key and duration | `workflow_id`, `tool_name` |
| `audit_logs` | Append-only trail | `workflow_id`, `task_id`, `agent_name`, `event_type` indexed |
| `generated_documents` | Document metadata + storage path | `workflow_id` |
| `notifications` | In-app alerts for approvals, completions, failures | `user_id`, `workflow_id`, `read` |

**SQLite (default).** `data/nexus.db` in WAL mode with `PRAGMA foreign_keys=ON`,
`check_same_thread=False` and a 30 s busy timeout so the API and the orchestration
worker never block each other.

**PostgreSQL.** Set `DATABASE_URL=postgresql+psycopg2://…`; `psycopg2-binary` is
already in `requirements.txt`. Connection pool: `pool_size=10`, `max_overflow=20`,
`pool_pre_ping=True`.

**Reset the demo.** Stop the server and delete `backend/data/*.db*` plus
`backend/data/generated_documents/*`; the next boot re-seeds reference data.
`docker compose down -v` does the same for the containerised stack.

**Checkpointer.** LangGraph persists graph state to a SQLite file at
`CHECKPOINT_DATABASE_PATH` even when the main database is PostgreSQL. It is what
allows an `interrupt()`-ed run to resume after a process restart — back it up
alongside the app data (compose mounts it in the `app_data` volume).

---

## 6. How a request flows through the platform

The twelve stages of the reference architecture are served live by
`GET /api/architecture` and rendered as the React Flow pipeline on the monitor:

`User Input → AI Command Center → Backend Processing → Planner Agent → LangGraph
Orchestrator → Specialized AI Agents → Tool Registry → Human Approval → Execution
Agent → Failure Recovery → Audit Logging → Final Report`

1. **Intake.** `POST /api/workflows` authenticates the caller, checks
   `workflows.create`, allocates a `WF-xxxxxxxxxxxx` id and queues the run; the
   HTTP call returns immediately.
2. **Planning.** `agents/planner.py` classifies the request into one of three
   categories, extracts entities (name, role, department, invoice/vendor/amount,
   customer/order/ticket), then emits an ordered task list with `agent`, `tool`,
   `depends_on`, `requires_approval` and `risk_level`. With an LLM configured the
   provider produces the plan; otherwise the deterministic rule planner produces
   the same shape — the orchestrator never depends on a provider being reachable.
3. **Orchestration.** `graph/orchestrator.py` builds a `StateGraph` over a shared
   `WorkflowState`. `select_task` performs topological resolution and only
   dispatches tasks whose dependencies completed; a failed prerequisite skips its
   dependents instead of executing them.
4. **Agents.** HR, Document, IT, Finance and Support nodes each receive only
   their own task plus the fields they need, and each may call only the tools in
   its allow-list.
5. **Tool registry.** `tools/registry.py` authorises the call (role permission or
   a task-scoped elevated capability), validates the payload with
   `jsonschema` (Draft 2020-12) against the tool's declared input schema, then
   hands it to a simulated adapter. Rejections are audited as `access_denied`.
6. **Approval.** `approval` raises a checkpoint for any tool flagged
   `requires_approval`, `side_effect ∈ {write, financial}` at high/critical risk,
   or non-reversible actions, then calls LangGraph `interrupt()`; the worker
   thread parks, the workflow is `awaiting_approval`, and the approver's decision
   resumes the graph **from the persisted checkpoint** (`Command(resume=…)`).
   Agents cannot bypass this: the decision is read from the database, not the state.
7. **Execution.** The Execution Agent performs approved operations, verifies
   results, and records the outcome, duration and idempotency key in `tool_calls`.
8. **Recovery.** `graph/recovery.py` retries transient failures with
   `base × factor^(attempt-1)` backoff — but only for tools with
   `retry_safe=True`. A financial operation that has already been issued (idempotency
   key found, or `retry_safe=False`) is never auto-retried. Failed tasks with
   compensation handlers are rolled back; exhausted tasks escalate
   (`WORKFLOW_ESCALATION_EMAIL`) and mark the run
   `completed_with_exceptions` rather than silently dropping work. Retry history
   is visible per task in the monitor.
9. **Audit.** Every decision, tool call, approval, failure and timestamp is
   written to `audit_logs` with severity and payload.
10. **Report.** A structured report is stored on the workflow, markdown is
    rendered on demand, and notifications are raised for the requester, approvers
    and admins.

---

## 7. Agents, integrations and tools

**Nine agents** (`GET /api/agents`) — orchestration agents have no tool access,
working agents receive a scoped allow-list:

| Agent | Role | Scoped tools |
|---|---|---|
| `planner` | Classify, extract entities, decompose, assign, order | 0 |
| `hr` | Employee records, validation, department, onboarding tracker | 4 |
| `document` | Templates, offer letter, onboarding pack, invoice summary, references | 5 |
| `it` | Mailbox, SSO identity, system access, equipment | 4 |
| `finance` | Extract, validate, de-duplicate, payment request | 4 |
| `support` | Customer/order lookup, ticket update, resolution, notification | 5 |
| `approval` | Policy detection, checkpoint creation, decision intake | 0 |
| `execution` | Perform approved operations and verify results | 1 |
| `audit` | Append-only recording of every decision | 0 |

**Six simulated integrations, 22 tools** (`GET /api/integrations`,
`GET /api/tools`) — HR Management System, Finance / Accounting System, CRM
System, IT Provisioning, Document Storage, Email / Notification Service. Each tool
row carries its JSON schema, required permission, risk level, side effect
(`read` / `write` / `financial`), `requires_approval`, `retry_safe` and
`reversible` flags — these drive policy rather than any hard-coded task list.

---

## 8. The web application (10 pages)

| Page | Route | What actually works there |
|---|---|---|
| Overview Dashboard | `/` | Live KPIs, status/category charts, agent activity, recent runs, prominent **Create New Workflow** |
| Create Workflow | `/workflows/new` | Natural-language request, three categories, example prompts, **Preview plan** (runs the real planner), submit |
| Agent Command Center | `/agents` | Nine agents, responsibilities, scoped tools, executions and success rates |
| Workflow Monitor | `/workflows`, `/workflows/{id}` | 12-stage React Flow pipeline, task table with attempts, tool calls, documents, approvals, audit per run; cancel and resume |
| Human Approvals | `/approvals` | Pending queue with policy reason and risk, approve/reject + comment, history; deciding one **resumes the paused graph** |
| Enterprise Applications | `/integrations` | Six cards with connection status, operations, permissions, last activity; **Test connection**, inspect authorised tools, edit configuration |
| Tool Registry | `/tools` | Filter/sort 22 tools, enable-disable (admin), register a new tool with schema, **validate a sample payload**, resynchronise the catalog |
| Audit Logs | `/audit` | Search and filter by workflow, agent, event, severity and date range, expandable payloads, per-workflow and per-agent views, **CSV export** |
| Reports & Analytics | `/reports` | KPIs, seven charts, per-workflow report, **download markdown**, window/category filters |
| Settings | `/settings` | Provider test/switch, orchestration and retry policy, approval policy, security posture, role matrix, health, 12-stage reference |

Colour coding in the pipeline: green completed · blue running · amber
awaiting-approval/retrying · red failed · grey pending or skipped. Dark and light
modes are both persisted; the layout is responsive down to mobile.

---

## 9. API reference

Base URL `http://localhost:8000`. All endpoints except `/api/health`,
`/api/architecture`, `/api/auth/login` and `/api/auth/demo-accounts` require
`Authorization: Bearer <token>`. Validation errors return
`{"detail": "…", "field": "…"}`; permission failures return 403 with a readable
reason. Interactive docs: `/api/docs`.

### Auth
| Method | Path | Purpose / permission |
|---|---|---|
| POST | `/api/auth/login` | Exchange email + password for a JWT |
| GET | `/api/auth/me` | Current user, role and permissions |
| GET | `/api/auth/demo-accounts` | Seeded sandbox accounts (no token needed) |

### Workflows
| Method | Path | Purpose / permission |
|---|---|---|
| POST | `/api/workflows` | Submit a natural-language request → 201 + queued run (`workflows.create`) |
| POST | `/api/workflows/preview-plan` | Dry-run the planner, changes nothing (`workflows.create`) |
| GET | `/api/workflows` | List with `status`, `category`, `search`, `limit`, `offset` |
| GET | `/api/workflows/categories` | Categories and example prompts for the UI |
| GET | `/api/workflows/{id}` | Detail: plan, tasks, timeline, approvals, documents, checkpoint state |
| GET | `/api/workflows/{id}/events` | Lightweight polling feed used by the live monitor |
| POST | `/api/workflows/{id}/resume` | Re-arm a checkpoint whose decision was already recorded |
| POST | `/api/workflows/{id}/cancel` | Cancel a run and its pending checkpoints |
| GET | `/api/workflows/{id}/report` | Structured final report |
| GET | `/api/workflows/{id}/report.md` | Same report as downloadable markdown |
| GET | `/api/workflows/{id}/documents/{docId}` | Download a generated document |

Ownership: your own workflows always; other users' require `workflows.view`
(and the access itself is audited).

### Approvals
| Method | Path | Purpose / permission |
|---|---|---|
| GET | `/api/approvals?status=pending\|all` | Pending queue incl. `can_decide` per row (`approvals.view`) |
| GET | `/api/approvals/history?workflow_id=` | Decided checkpoints |
| GET | `/api/approvals/{id}` | Full checkpoint detail |
| POST | `/api/approvals/{id}/decide` | `{ "action": "approve" \| "reject", "comment": "…" }` (`approvals.decide`) — approves the task-scoped elevation and resumes the graph; rejecting stops the action and skips dependents |

### Agents, integrations, tools
| Method | Path | Purpose / permission |
|---|---|---|
| GET | `/api/agents` · `/api/agents/{name}` | Roster, scoped tools, execution stats |
| GET | `/api/integrations` | Six systems with status and activity (`integrations.view`) |
| PATCH | `/api/integrations/{key}` | Connection status and configuration (`integrations.manage`) |
| POST | `/api/integrations/{key}/test` | Sandbox connectivity check per tool |
| GET | `/api/tools` | Registry with filters |
| POST | `/api/tools` | Register a tool with its JSON schema (`tools.manage`) |
| PATCH | `/api/tools/{name}` | Enable/disable and flags (`tools.manage`) |
| POST | `/api/tools/{name}/validate` | Validate a sample payload against the schema |
| POST | `/api/tools/sync` | Re synchronise the database from the declarative catalog (`tools.manage`) |

### Audit
| Method | Path | Purpose / permission |
|---|---|---|
| GET | `/api/audit` | Search (`q`, `workflow_id`, `agent_name`, `event_type`, `severity`, `date_from`, `date_to`, `limit`, `offset`) — `audit.view` |
| GET | `/api/audit/facets` | Distinct agents, event types, severities and totals for the filter chips |
| GET | `/api/audit/workflow/{id}` | Per-workflow history |
| GET | `/api/audit/export.csv` | Same filters, CSV download |

### Dashboard, reports, settings, platform
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard/stats` | KPIs, breakdowns, throughput, agent activity |
| GET | `/api/notifications` · POST `/api/notifications/{id}/read` · POST `/api/notifications/read-all` | In-app alert feed |
| GET | `/api/reports` | Report summaries + aggregate KPIs (`reports.view`) |
| GET | `/api/reports/platform?days=` | Task/agent/tool/risk/severity distributions |
| GET | `/api/reports/{workflow_id}.md` | Markdown report |
| GET | `/api/settings` | Provider, orchestration, approval policy, security, health |
| PUT | `/api/settings/llm/provider` | Switch provider at runtime (`settings.manage`) |
| POST | `/api/settings/llm/test` | Probe a provider without changing the active one |
| GET | `/api/settings/roles` | Role → permission matrix |
| GET | `/api/health` | Database, dialect, provider, active runs (public) |
| GET | `/api/architecture` | The twelve pipeline stages with descriptions (public) |

### Worked curl example

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@nexus-ai.example","password":"NexusDemo2026!"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://127.0.0.1:8000/api/workflows \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"request_text":"Onboard Anita Verma as a Senior Data Analyst in the Finance Department starting 2026-11-16.","category":"employee_onboarding"}'

# watch it stop at the first checkpoint
curl -s "http://127.0.0.1:8000/api/approvals?status=pending" -H "Authorization: Bearer $TOKEN"

# approving resumes the LangGraph run
curl -s -X POST http://127.0.0.1:8000/api/approvals/<approval_id>/decide \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"approve","comment":"Verified against the requisition."}'

curl -s http://127.0.0.1:8000/api/reports/<workflow_id>.md -H "Authorization: Bearer $TOKEN"
```

---

## 10. Security and governance

* **Authentication.** JWT bearer tokens (HS256) signed with `SECRET_KEY` from the
  environment; passwords are PBKDF2-SHA256 with 240 000 rounds and per-user salts.
* **RBAC.** Four roles mapped to capability permissions (`rbac.py`); every route
  checks the capability it needs and the frontend gates the same actions on the
  server's answer, so hidden buttons are never the actual control.
* **Tool-level authorisation.** Each tool declares the permission it requires;
  `registry.py` refuses calls whose agent is not allow-listed or whose actor lacks
  the permission, and writes an `access_denied` audit entry.
* **Least-privilege agents.** An agent receives its single task plus the fields it
  needs, and can only see its own tool subset (`GET /api/agents/{name}`).
* **Approval-based privilege elevation.** A critical action (e.g.
  `finance.payment.write`) does **not** widen the requester's role: approving the
  checkpoint grants that capability **for that task only**, recorded in the audit
  trail. An operator cannot approve their own checkpoint.
* **No bypass.** The checkpoint decision is read from the database inside the
  graph, so no agent path can continue an interrupted run without a recorded human
  decision. Rejecting stops the action and skips dependents.
* **Input validation.** Pydantic models constrain every request body (length,
  enums, email format); tool payloads are re-validated against their JSON schema
  before an adapter runs.
* **Idempotency.** `tool_calls.idempotency_key` is
  `{workflow_id}:{task_id}:{tool_name}`; a replayed execution is detected rather
  than duplicated.
* **Retry safety.** Automatic retry applies only when
  `MAX_TASK_ATTEMPTS` allows and `retry_safe=True`. Financial and other
  irreversible operations are excluded, so a payment can never be issued twice by
  the recovery loop.
* **Append-only audit.** `audit_logs` is written by `services/audit.py`; there is
  **no update or delete route** for ordinary users or for admins — the API surface
  exposes only reads and CSV export.
* **Secrets.** Environment variables only. Nothing is committed; `.env` is never
  baked into an image (compose injects it at runtime).
* **Sandbox honesty.** Reports and UI copy state that actions ran against
  simulated adapters; `simulation_notice` is part of every final report.
* **Known sandbox affordances.** `GET /api/auth/demo-accounts` is public and
  returns the shared demo password so the sign-in page can offer one-click access.
  That is only acceptable for synthetic accounts in a sandbox — before deploying
  for real, set `SEED_DEMO_DATA=false`, drop that route, issue real accounts, and
  replace the simulated adapters.

---

## 11. Demo scenarios

### The 12-step reference walkthrough (employee onboarding)

1. Sign in as `operator@nexus-ai.example` and open **Create Workflow**.
2. Paste: *“Onboard Anita Verma as a Senior Data Analyst in the Finance Department
   starting 2026-11-16. Generate the offer letter and onboarding pack, set up her
   email and SSO identity, grant access to the analytics tools, reserve a laptop
   and notify her manager.”*
3. **Preview plan** — the planner classifies the request, extracts the entities and
   lists the tasks, owning agents, tools, dependencies and approval checkpoints.
4. **Submit workflow** — the monitor shows the pipeline advancing stage by stage.
5. Sign in as `admin@nexus-ai.example` (or `approver@…`) and open **Human
   Approvals**.
6. Approve the HR-record checkpoint, adding a comment.
7. Watch the graph resume and the Document Agent produce the offer letter and
   onboarding pack.
8. Approve the IT-provisioning checkpoint (mailbox, SSO, access, equipment).
9. Observe a transient failure on `it.setup_equipment` recover on attempt 2 —
   visible in the task's retry history.
10. Approve the notification/dispatch checkpoint.
11. Open **Audit Logs**, filter by this workflow, expand entries, export CSV.
12. Open **Reports & Analytics** → the run's report, then download the markdown.

### Invoice processing

*“Process invoice INV-88214 from Acme Office Supplies for EUR 1,290.50. Extract
the data, validate it, check for duplicates and create the payment request.”*
→ 6 tasks (finance ×4, document, email), one **critical-risk** payment checkpoint
requiring `finance.payment.write`, one generated invoice summary, and no auto-retry
on the payment step.

### Customer support

*“Customer Beacon Retail Group asks where order ORD-77301 is; ticket TCK-44102 is
late. Look up the order, update the ticket and log the resolution.”*
→ 5 tasks, all low-risk, so it completes without a checkpoint — the contrast shows
the approval policy is data-driven, not blanket.

### Scripted run

```bash
# backend must be reachable
python backend/scripts/demo_scenarios.py --base-url http://127.0.0.1:8000
python backend/scripts/demo_scenarios.py --scenario onboarding --timeout 300
python backend/scripts/demo_scenarios.py --reject      # exercise rejection + rollback
```

It logs in, previews and submits each scenario, polls the monitor, decides every
checkpoint through the approvals API, then prints the final status, task counts,
tool calls, documents, audit volume and the sandbox notice.

The delivered database was reset and rebuilt from scratch, so it contains exactly
four completed runs and no stray failures: the Rahul Sharma onboarding driven
end-to-end through the web UI (3 checkpoints, a transient `it.setup_equipment`
failure recovered on attempt 2, 10/10 tasks, 2 documents) plus the three scripted
scenarios above.

---

## 12. Testing

```bash
cd backend && ../.venv/Scripts/python -m pytest -q     # 29 passed
cd frontend && npm run lint                            # tsc -b --noEmit
cd frontend && npm run build                           # production bundle
```

`backend/tests/test_api.py` covers auth, RBAC refusals, workflow submission, plan
preview, approval-driven resume, idempotent decisions, audit search/export,
registry validation and report rendering; `test_orchestrator.py` covers planning,
dependency resolution, checkpoint interruption, retry policy and rollback. Manual
verification was done through the UI end to end: submit → pause → approve in the
portal → resume → complete → report download → CSV export, plus dark mode and
every page.

---

## 13. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Database is locked` toast | Two processes touched the same SQLite file (usually an old uvicorn still running). Stop the extra process; Postgres or a single server avoids it. |
| Signed out right after restart | `SECRET_KEY` was unset, so a new random key was generated. Set it in `.env`. |
| 401 in the UI but curl works | The token expired (`ACCESS_TOKEN_EXPIRE_MINUTES`) or the API moved ports; sign in again. |
| `/api` 404 on `:5173` | The backend is not on `VITE_API_TARGET`; start uvicorn on 8000 or set the target. |
| Plan looks generic | The request has no recognisable entities — use one of the example prompts, or pick the category explicitly (an explicit category always wins over inference). |
| Workflow stuck at `awaiting_approval` after a decision | The worker had already parked; press **Resume** on the detail page or `POST /api/workflows/{id}/resume`. |
| `docker compose up` fails on `env_file` | `.env` is missing: `cp .env.example .env`. |
| UI shows no data in Docker | The API health check is still warming up; `docker compose logs -f api`. |

---

## 14. Extending it

* **A new tool:** add a `ToolDefinition` in
  [`backend/app/tools/definitions.py`](backend/app/tools/definitions.py) (schema,
  permission, risk, side effect, retry/reversible flags) plus an adapter in
  [`backend/app/tools/adapters.py`](backend/app/tools/adapters.py), then
  `POST /api/tools/sync` — or register it at runtime from the Tool Registry page.
  Policy picks up the flags automatically.
* **A new agent:** add an `AgentSpec` to
  [`backend/app/agents/catalog.py`](backend/app/agents/catalog.py) with its tool
  allow-list, then wire a node in `graph/orchestrator.py` next to `make_agent_node`.
* **A real integration:** replace the simulated adapter body with an HTTP client
  and keep the registry contract (schema validation, idempotency key, audit
  record). The sandbox notice should then become a real environment label.
* **Queue scale-out:** move `graph/runtime.py` from the in-process thread pool to
  Redis-backed workers; the checkpointed graph is already resumable from any
  worker that can read the same checkpointer.

---

*Built as a demonstration platform with synthetic data only. No confidential
company information is present, and no action in this build touches a live
enterprise system.*
