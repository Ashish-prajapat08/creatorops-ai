# CreatorOps AI — V1 + V2

Creator agency finance operations with a real collection workflow: deterministic overdue detection → relevant Gmail context → a validated AI draft → human edit/approval → Gmail send → an append-only audit trail.

`master_context_v1_v2.md` is the active V1/V2 specification. `MASTER_CONTEXT.md` preserves the original V0 source of truth verbatim. V0 is retained; V1 adds stage-based collections, and V2 adds email intelligence and manual/mock transaction reconciliation. V3, gateways, transfers, payout calculations, real payment processing, and automatic email sending remain excluded. See [the implementation report](docs/v1-v2-implementation.md) for actual verification and limitations.

## Architecture

- **Frontend:** Next.js, TypeScript, Tailwind, shadcn-style components backed by Radix primitives.
- **Backend:** a FastAPI modular monolith, Pydantic contracts, SQLAlchemy repositories/services, Alembic migrations.
- **State:** PostgreSQL owns financial truth, approval snapshots, jobs, and audit records. Redis only transports Celery jobs.
- **Identity:** Supabase Auth owns credentials; the backend verifies the bearer session against the provider before resolving workspace membership.
- **AI:** OpenAI structured outputs inside LangGraph. AI writes prose and summarizes inbound intent. Python inserts invoice facts and recipient; AI has no financial mutation or sending tools.
- **Email:** Google OAuth with PKCE, one-use expiring state, encrypted tokens, `gmail.readonly` + `gmail.send` scopes.
- **Operations:** Celery worker with one embedded Beat scheduler, structured logs, optional Sentry and sanitized LangSmith traces.

See [architecture decisions](docs/architecture.md), [phase acceptance evidence](docs/acceptance.md), and [deployment guide](docs/deployment.md).

## Local setup

Requirements: Python 3.13, Node 24, Docker Desktop, a Supabase project, an OpenAI API key, and a Google OAuth web client with Gmail API enabled.

```sh
docker compose up -d postgres redis
cp .env.example .env
cp frontend/.env.example frontend/.env.local
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.lock.txt
cd backend
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Put the generated value in `ENCRYPTION_KEY` in the root `.env`. Configure Supabase, OpenAI, and Google keys there. Configure the three public frontend values in `frontend/.env.local`. Never put service-role keys or Google/OpenAI secrets in `NEXT_PUBLIC_*` variables. Both env files are ignored by Git.

Docker uses **55432** for PostgreSQL and **56379** for Redis to avoid common local port conflicts. The database URL in `.env.example` already matches these ports.

In Supabase, enable email/password sign-up and email confirmation, set a minimum password length of 12, and allow `http://localhost:3000/login` as a redirect. Use the project's publishable key in the frontend and backend. The backend never stores passwords or a service-role key. Users sign up, confirm email, and sign in through Supabase.

In Google Cloud, enable Gmail API, create a web OAuth client, and register this exact local callback:

```text
http://localhost:8000/api/v1/integrations/gmail/callback
```

Add your testing account to the OAuth consent screen. Production consent and scope verification are described in the deployment guide.

Run in separate terminals:

```sh
# API (from backend/)
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000 --no-access-log

# Worker + the single scheduler (from backend/)
.venv/bin/celery -A app.workers.celery_app:celery worker -B --concurrency=2 --loglevel=WARNING

# Frontend (from frontend/)
npm ci
npm run dev
```

On macOS, Celery's `--pool=solo` can be used for development. Use prefork in production. Next.js uses webpack because the default compiler could not start its CSS helper in the execution environment; the application stack is unchanged.

Open `http://localhost:3000`. API docs are at `http://localhost:8000/docs`; liveness and readiness are `/health/live` and `/health/ready`.

## Using V0

1. Sign up, confirm email, sign in, and create an agency workspace with currency and timezone.
2. Add brands and creators, then a campaign and its invoices. The campaign and invoice must share brand and currency.
3. Add registered application users to the workspace in Settings. Members first sign up and open the app. Owner/Admin manage membership; Finance handles invoice operations and approves sends; Ops handles campaigns/creators and prepares drafts; Viewer is read-only. Only Owners can grant ownership; the last Owner cannot be removed.
4. Connect the agency Gmail in Settings. Only Owner/Admin can connect or disconnect.
5. The worker scans every five minutes. Use **Scan overdue invoices** for an immediate scan. Unissued drafts, paid invoices, and void invoices are excluded.
6. Generate a collection draft. The worker retrieves only relevant plain-text messages involving the brand and invoice number, classifies the latest inbound context, validates output, and saves a draft.
7. Review the recipient, facts, email context, subject, and body. Save edits before approval. Approval binds the exact saved revision, content, invoice facts, sender, recipient, and approving user.
8. **Approve & send** queues the approved email. View delivery status and the invoice's collection timeline.

Issued invoices are retained: change status to `VOID` instead of deleting. Only unissued drafts can be deleted. An approved or in-flight collection blocks invoice edits. An approved queue entry can be cancelled through the rejection endpoint before sending starts.

## Seed data

Sign in first, then run from `backend/`:

```sh
.venv/bin/python -m app.seed --email YOUR_REGISTERED_EMAIL
```

The idempotent seed creates Acme Creator Management, Nike/Google/Amazon, three creators, three campaigns, six invoices (one paid, two upcoming, three overdue), five stage-specific collection tasks (three overdue and two due soon), and sample invoice messages. Dates are relative to the agency's local date. `.example` contacts are placeholders; edit them before testing live sending. Seed data does not fake a Gmail connection or bypass approval.

## Tests and checks

Tests use actual PostgreSQL, not SQLite, to verify constraints and row locking. Create a separate database once:

```sh
docker compose exec -T postgres psql -U creatorops -c 'CREATE DATABASE creatorops_test'
cd backend
DATABASE_URL=postgresql+psycopg://creatorops:creatorops@localhost:55432/creatorops_test .venv/bin/alembic upgrade head
.venv/bin/pytest -q
.venv/bin/ruff check app alembic
.venv/bin/ruff format --check app alembic
```

The test suite refuses to truncate a database whose name does not end in `_test`. Do not point browser tests at development or production data.

```sh
# From frontend/
npm run typecheck
npm run lint
npm run format:check
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright starts the actual API, Next.js, Celery, and Redis queue workflow. External AI/Gmail providers and authentication sessions use **explicit isolated test adapters**. These require `ENVIRONMENT=test`, a test signing secret, and `TEST_MODE=true`; production refuses test mode. E2E uses a separate Redis database, ports 8001/3001, unique identities/workspaces, and a dedicated test database. Do not run backend destructive fixtures and E2E at the same time. Reports/screenshots are under `frontend/playwright-report/` and `frontend/test-results/`.

CI runs lint, formatting, type checking, migration drift detection, PostgreSQL integration tests, AI structured-output tests, production build, production dependency audit, and primary browser tests. A local pass does not imply GitHub Actions or cloud deployment has run.

## Send failures and recovery

Gmail has no caller-provided exactly-once send guarantee. V0 prioritizes preventing duplicate email:

- Approval creates a durable PostgreSQL job in the same transaction. Beat republishes queued jobs after broker failures. Workers claim job IDs under database locks.
- Before invoking Gmail, the worker commits a `SENDING` barrier and deterministic RFC Message-ID. Repeat approval requests and duplicate job deliveries cannot send again.
- A timeout, lost response, or worker crash after the barrier yields `SEND_UNCERTAIN`. **No automatic resend is allowed.** Use reconciliation to search Sent mail for the Message-ID.
- An empty search result does not prove failure, because Gmail indexing can lag. The task remains uncertain until confirmed or manually investigated. Do not create a replacement send to work around it.
- Transient read/draft failures retry with exponential backoff. Invalid OAuth, permissions, malformed output, or stale approval do not blindly retry.

Money is stored in PostgreSQL `NUMERIC(18,2)`, calculated with Python `Decimal`, and serialized as strings. Dashboard totals are grouped by currency, with no cross-currency arithmetic. The money contract uses two decimal places. A due date is overdue only after that date in the agency timezone. AI payment claims never mark an invoice paid.

## Configuration and observability

The root `.env.example` lists backend configuration. `SENTRY_DSN` and `LANGSMITH_API_KEY`/`LANGSMITH_TRACING` are optional. Request IDs appear in error envelopes and `X-Request-ID`; structured logs contain references and statuses, not credentials or email bodies. Sentry redacts request data, breadcrumbs, exception values and local variables. LangSmith traces a sanitized workflow summary while suppressing raw LangGraph-state traces. Full approved messages and changes belong in tenant-scoped PostgreSQL records and audit history.

The `braces` dependency currently has an unresolved development-only advisory inherited through Next's ESLint glob tooling; the installed registry version has no patched release. It is not part of the production runtime. See `docs/acceptance.md`; production dependency audits are checked independently. No live provider credentials are included in this repository.

## V2 email intelligence and promises

Open **Email intelligence**, select an invoice and click **Sync email**. The existing Celery worker polls connected accounts every `EMAIL_SYNC_INTERVAL_SECONDS` (default 300). Every invoice has a persistent checkpoint; polling uses a one-day overlap, pages relevant results, and deduplicates by agency/Gmail message ID. Only uniquely associated inbound replies from the brand are queued. Plain text is preferred; HTML-only replies are converted to text without scripts or attachments. Quoted outbound text is removed.

The versioned `email-v1` schema contains eight categories, confidence, evidence quotes, optional explicit promised date/amount/currency/reference, and a proposed next action. Evidence and extracted values are checked against the source. Conflicts, uncertainty, confidence below `EMAIL_HIGH_CONFIDENCE`, and ambiguous/missing promise dates enter review. Relative dates such as “Friday” are never silently converted. **Accept reviewed claim** records human interpretation, not payment verification. Authorized users can correct classification/date, reject interpretation, and reprocess failed/reviewed messages. Reprocessing preserves audit history and requires renewed review after a prior human decision.

Promises retain their source and date certainty. An accepted explicit promise that passes in the agency timezone with an outstanding balance becomes `MISSED` and creates one `PROMISE_MISSED:<promise-id>` follow-up stage. No automatic reply is sent. For old/delayed mailbox messages beyond the polling overlap, `POST /api/v1/invoices/{id}/sync-email?full=true` requests a complete relevant-context rescan; repeated messages still deduplicate. Messages that cannot be uniquely associated are skipped and audited for manual investigation. An excessively large mailbox result fails safely without advancing its checkpoint.

## V2 manual reconciliation

Open **Reconciliation**. Owner/Admin can enter immutable `MANUAL` or `MOCK` transaction records; Owner/Admin/Finance can approve, reject or reverse allocations. These records are **not bank verified**. Duplicate source IDs and external references are idempotent; conflicting duplicates return 409.

The deterministic engine considers explicit invoice IDs/numbers, the invoice's optional **Expected payment reference**, payer brand, currency, amount and issue-date context. Equal amounts alone never create a match. Suggestions do not change balances. Select an invoice or explicitly split a transaction across invoices, enter decimal-string allocations, supply a reason, and confirm. Currency mismatches and transaction overallocation are blocked. Overpayments, conflicting references/payers, possible duplicates, pre-issue dates and multi-invoice splits require explicit acknowledgement.

Confirmed allocations are separate normalized records. Partial payments leave the invoice open; fully allocated amounts produce `PAID`; overpayments remain visible. Dashboard amounts use the remaining balance and keep currencies separate. Unmatched/rejected/duplicate imports do not count as paid. Reversals retain the original allocation and actor/reason/time, restore balances deterministically, and appear in invoice history. Financial fields of reconciliation-managed invoices cannot be overridden through generic editing. Legacy V0 manually-PAID invoices remain labelled legacy records without fabricated bank evidence; explicitly reopen them before adding payment allocations.

Payment changes invalidate saved/approved collection drafts, so queued email cannot use a stale balance. An actively drafting, sending, or uncertain-send task must be resolved first. Membership is revalidated under the agency mutation lock before financial decisions and again before Gmail sending.

Apply the additive V1/V2 migration with `alembic upgrade head`. No new dependencies, credentials, services or infrastructure are required. V1 adds `DUE_SOON` tasks within `COLLECTION_DUE_SOON_DAYS` (default 7), while preserving the overdue stage. The seed now creates three overdue and two due-soon tasks. The V0 browser workflow remains, and V2's browser test covers promise review, partial allocation and audited reversal. Test adapters do not substitute for live provider verification.

## NVIDIA development provider

For synthetic-data prototyping with NVIDIA's hosted endpoint, set root `.env`:

```env
AI_PROVIDER=nvidia
NVIDIA_API_KEY=your_local_secret
NVIDIA_MODEL=openai/gpt-oss-20b
```

Restart API and worker after changes. The shared provider uses NVIDIA Chat Completions
with JSON Schema and validates outputs through the existing Pydantic contracts and
business/evidence guardrails. Reasoning content is never displayed or persisted.
OpenAI remains available with `AI_PROVIDER=openai`. NVIDIA prototype terms and limits
apply; do not send confidential or personal email/invoice data to the trial endpoint.
Provider schema validity is not a guarantee of semantic accuracy.

## Zero-cost resume demo deployment

The default Render blueprint now creates only a free combined API/solo-worker service
and a free Redis broker; PostgreSQL/Auth use Supabase. Follow `docs/deployment.md`.
The service sleeps when idle, so scheduled work pauses. This is a limited personal
demo configuration, not an always-on production guarantee. Migration `a71d96c240be`
blocks direct browser Data API access to business tables; backend access still uses
FastAPI authorization and the trusted server database role. No hosting accounts or
public resources are created by merely saving this configuration.
