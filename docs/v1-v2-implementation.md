# V1/V2 implementation checklist

Authoritative scope: `master_context_v1_v2.md`, explicitly requested after V0. Historical V0 context remains unchanged. Keep the current modular monolith, Supabase identity, FastAPI API, Next.js UI, PostgreSQL, Redis/Celery, LangGraph/OpenAI and Gmail.

- Phase A: inspect specification and existing implementation; run baseline checks.
- Phase B: stage-specific due-soon/overdue tasks; richer grounded context; persistent Gmail thread IDs; retain approval/send barriers and V0 tests.
- Phase C: durable incremental Gmail polling; idempotent inbound classification jobs; evidence-validated structured results; confidence/review queue; source-linked payment promises and missed-promise tasks.
- Phase D: immutable manual/mock transaction ingestion; deterministic candidates; reviewed allocations, partial balances, discrepancies and audited reversals; retain legacy manually paid invoices without inventing bank evidence.
- Phase E: email intelligence/reconciliation screens; invoice balances and histories; regression/E2E tests; migrations; documentation and actual validation results.

Decisions: polling reuses Celery rather than adding push infrastructure. New extraction/classification schema is versioned separately from the established V0 draft contract. No automatic reconciliation or sending. Multi-invoice transaction splitting is supported only through explicit reviewed allocations. Legacy `PAID` invoices remain manual legacy records; new reconciliation-managed invoices derive status from confirmed allocations.

## Implementation report

### Already implemented and retained

V0 supplied Supabase signup/login, workspaces/membership/RBAC, core entity CRUD, Decimal financial fields, dashboard/overdue scanning, Gmail OAuth and encrypted tokens, LangGraph draft generation, human review and a durable send barrier/outbox, audit records, seed data, CI and deployment configuration. Existing provider adapters remain test-only. Inspection confirmed genuine integration paths rather than placeholder UI. The original 50-test regression set passed after bringing PostgreSQL/Redis back up (the seed expectation intentionally changed from three overdue tasks to five stage-specific tasks).

### Changes and modules

- **V1 collections:** `services/finance.py`, `collections.py`, `collection_execution.py`, `entities.py`, Gmail client/normalizer, task response schemas and collections UI. Tasks are unique per invoice/workflow stage; due-soon, overdue and missed-promise stages use deterministic eligibility. Campaign, terms, balance, recent collection history and compact Gmail context are supplied to drafts. Approval/send checks include current membership, revision, recipient, sender, invoice and balance. Genuine Gmail thread IDs are retained. Transient token/quota failures remain retryable; permanent failures and ambiguous sends remain explicit.
- **V2 intelligence:** `agents/email_intelligence.py`, `services/email_sync.py`, `services/email_intelligence.py`, `api/v1/intelligence.py`, versioned Pydantic schemas and `components/email-intelligence.tsx`. Polling checkpoints, overlap, pagination, message uniqueness, queued classification, structured evidence validation, review/reprocess and source-linked promises reuse the existing worker/outbox. No automatic replies or email-driven PAID transitions.
- **V2 reconciliation:** `services/balances.py`, `services/reconciliation.py`, `api/v1/reconciliation.py`, `models/operations.py`, request/response schemas and `components/reconciliation.tsx`. Manual/mock imports deduplicate by source ID and external reference. Deterministic suggestions require identifiers or payer identity. Reviewed allocations support exact/partial/multiple/split/overpaid cases, with transactional validation and idempotent approvals. Reversals retain original allocations and restore balances. Legacy manually paid records remain distinct.
- **Shared UI:** invoice details now show balances, promise history, allocation history and reconciliation audit events; navigation includes both V2 queues. Permissions, loading/error/empty states and accessible labels reuse the existing component system. Sidebar navigation scrolls instead of overlapping the footer.
- **Engineering:** `core/security.py` revalidates current membership after acquiring mutation locks; Celery dispatch handles classification/sync job types and transient failures. README, CONTRIBUTING, `.env.example`, CI, architecture and deployment guidance updated. Added PostgreSQL integration/AI/recovery/RBAC tests and a V2 Playwright flow.

### Migration

`ff8cbac1385c_v1_stages_and_v2_email_intelligence_.py`, after the existing audit-immutability migration, adds:

- `email_analyses`, `payment_promises`, `email_syncs`;
- `payment_transactions`, `payment_allocations`, `reconciliation_decisions`;
- tenant-safe unique/foreign-key constraints and lookup indexes;
- invoice `payment_reference` and `reconciliation_managed` fields;
- collection `workflow_key`, Gmail thread ID, and uniqueness by invoice/stage.

Existing tasks backfill to `OVERDUE`; existing invoices default to non-reconciliation-managed. No existing rows are dropped or reset by the upgrade. `scripts/check_upgrade.py` verified the V0-to-V1/V2 upgrade on preserved invoice/task fixtures in a temporary schema inside the dedicated test database. The schema is removed afterward. Do not downgrade a live V2 database to V0: multiple stages no longer satisfy V0's one-task-per-invoice invariant, and downgrading feature tables discards V2 history. Use tested forward migrations and backups.

### Verification evidence

- Frontend baseline: TypeScript, ESLint and production webpack build passed. Initial backend baseline was blocked by stopped/unreachable Docker infrastructure; after restoring the existing services, original regressions passed.
- Backend: `.venv/bin/pytest -q --tb=short -x` — **81 passed** at the last completed full run.
- Backend lint/format: Ruff checks passed.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` — passed with both new routes.
- Browser: `npm run test:e2e` — **3 passed**, covering V0 create/draft/edit/approve/send/audit, route protection, and V2 promise review → manual partial allocation → reversal → invoice history. HTTP, PostgreSQL, Redis/Celery and UI are real; external providers are test adapters.
- Migrations: `alembic upgrade head`, `alembic check`, `alembic current` passed; head `ff8cbac1385c`; no schema drift. Preserved-data migration fixture passed.
- `scripts/check_sources.py` validates the unchanged V0 context copy and deployment/CI configuration.
- Final follow-up checks passed: **81 backend tests**, **3 Playwright tests**, frontend formatting/typecheck/lint/production build, backend Ruff lint/formatting, source checks, and preserved-data migration verification. The final browser run completed with 3 passing tests in 29.8 seconds.

### Configuration and local setup

No new packages or external credentials were added. Existing Supabase, Google OAuth, OpenAI, database, Redis and encryption settings are still used. New optional settings:

| Setting | Default | Meaning |
|---|---|---|
| `EMAIL_HIGH_CONFIDENCE` | `0.90` | Minimum confidence for saving an unflagged interpretation without manual review |
| `EMAIL_SYNC_INTERVAL_SECONDS` | `300` | Poll interval on the existing worker |
| `COLLECTION_DUE_SOON_DAYS` | `7` | Upcoming-payment task window |

From the repository root, start `docker compose up -d postgres redis`; from `backend`, run `.venv/bin/alembic upgrade head`, then the API and existing Celery worker/Beat commands in README. From `frontend`, run `npm ci` and `npm run dev`. Configure real keys only in ignored env files or hosting secrets. Gmail still uses read-only plus send scopes; no broader permissions or push infrastructure are added.

### Remaining verification and deliberate limits

- Live Supabase signup/email confirmation, Google OAuth/token refresh/mailbox matching/delivery, and real OpenAI quality remain **unverified without configured credentials**. Mocked tests are not a successful live integration claim. The genuine integration paths are implemented.
- No public deployment or remote GitHub Actions run was performed. Existing hosting configuration remains; apply migrations before starting the updated API/worker. Production monitoring accounts also need their own verification.
- Classification confidence is a model score, not a calibrated financial guarantee. Evidence checks cannot prove semantic accuracy; uncertain/conflicting results and ambiguous dates enter review, all sender promises remain claims, and human correction is recorded separately from original model output.
- Polling uses a bounded result set and one-day overlap. Full rescan is available for older/delayed messages; non-unique invoice associations are skipped and audited rather than guessed. No Gmail push infrastructure, attachment extraction or universal mailbox mirror.
- Imports are manual/mock only, not verified bank records. Source-ID/reference idempotency is enforced; lookalike records with distinct IDs are flagged as possible duplicates. Explicit human acknowledgement is required where appropriate. No CSV import (optional in the specification).
- Reconciliation is synchronous and transactional under the agency lock; this intentionally serializes low-volume financial mutations. No automatic reconciliation, currency conversion, refunds or real payment execution.
- V0's ambiguous-send recovery remains conservative: no automatic resend after a lost Gmail confirmation. An in-flight/uncertain collection must be resolved before changing its balance.
- Existing development-only lint dependency advisory remains documented in the V0 acceptance report. No new dependencies were introduced.

**V3 was not implemented:** no creator payout calculations/management, transfers, Stripe/Razorpay/gateways, payment processing, or gateway webhooks.


### Final local state

Provider configuration was checked without printing secret values: Supabase, OpenAI, Google OAuth, and token encryption are not configured in the current local environment. Therefore no real mailbox was accessed and no real email was sent. No public deployment, remote push, or commit was created. Local PostgreSQL/Redis remain the existing development services; browser/API/worker processes started by Playwright were test-run managed. Existing V0 source context remains byte-for-byte unchanged.

### NVIDIA provider extension (user-requested)

Added an explicit `AI_PROVIDER` selector, `NVIDIA_API_KEY` and `NVIDIA_MODEL` settings,
with a shared structured-generation adapter in `app/agents/provider.py`. OpenAI's
Responses path remains available; NVIDIA uses Chat Completions JSON Schema, followed
by Pydantic validation and the unchanged draft/evidence validators. AI audit model
identifiers now reflect the configured model. No financial rules or send approval
requirements changed. Local secrets remain ignored by Git.

Verification: 89 backend tests passed, including eight provider contract tests;
Ruff passed. Live NVIDIA minimal synthetic chat returned HTTP 200. Live structured
drafting timed out; classification initially returned HTTP 400 and subsequent
attempts timed out, including after switching to serialization-mode JSON Schema.
Therefore NVIDIA authentication/connectivity is verified, but actual structured
workflow compatibility/latency is NOT yet verified. No real agency data was sent.
Do not claim the NVIDIA workflows are production-ready from these checks. Browser
E2E was not rerun for this backend-only change.

### NVIDIA nested draft contract fix

Reproduced `INVALID_AI_OUTPUT` with synthetic data: the hosted model returned
`understanding` as a string instead of the required nested object, despite accepting
`response_format=json_schema`. The NVIDIA adapter now also includes the exact schema
in its system instruction and permits one fresh generation after schema-validation
failure. Repair feedback contains only validation paths/types, excludes raw output,
and preserves the original trusted instructions and untrusted-data boundary. Local
Pydantic validation, evidence checks, financial guardrails, refusal/truncation rejection
and human approval remain mandatory; no fabricated fallback draft is substituted.

Verification: 91 backend tests passed, including regressions for the observed nested
string, explicit schema instructions and bounded retries; Ruff passed. A live synthetic
NVIDIA draft passed both schema and financial/evidence checks. This does not establish
live mailbox/send correctness or model semantic accuracy. Restart existing API/worker
processes before retrying failed tasks; no real email was sent during this fix.

### NVIDIA classification Decimal grammar fix

Reproduced HTTP 400 on a synthetic payment promise: NVIDIA's grammar compiler rejects
Pydantic's Decimal serialization regex because look-around is unsupported. Added a
provider-only recursive translation for Decimal strings using a compatible decimal
pattern and omitting Pydantic-specific wire keywords. Original Pydantic positive,
precision, digit-count and float-rejection checks remain mandatory on returned output;
evidence/date checks are unchanged. No business-model or database migration needed.
Regression suite: 97 passed; Ruff passed. Added six tests covering schema translation
and retention of local financial validation. Existing failed analyses must be explicitly
reprocessed after restarting the worker; repeated Gmail sync does not reclassify them.
Live verification after the change did not complete: the NVIDIA endpoint timed out.
The exact rejected regex is fixed and covered by tests, but live classification success
is not yet confirmed. No production email contents were used for diagnosis.

### Evidence-aware NVIDIA classification retry

Strengthened classifier instructions with exact source quoting, separate field-labelled
evidence examples, and explicit exclusion of trusted context values absent from the email.
The shared adapter accepts an optional evidence validator and permits at most two total
NVIDIA generations across schema/evidence failures, avoiding nested retry budgets. A
failed evidence check feeds only application-authored error guidance into a fresh request;
raw model output is not promoted to trusted instructions. Repeated unsupported claims
still fail with INVALID_AI_EVIDENCE; no fallback analysis is fabricated.

Verification: 100 backend tests passed; Ruff passed. Live synthetic payment promise
classified PAYMENT_PROMISED, extracted 2026-11-15, and passed source evidence validation
with no review reasons. Exact prior live response was not retained, so its specific failed
evidence field is not claimed. Tests cover missing per-field evidence, fabricated source
quotes, successful correction, and repeated invalid evidence rejection. Existing saved
failed analysis needs worker restart and explicit Reprocess source email. No real email
was sent and no mailbox contents were submitted during this verification.

### Human review save feedback

Confirmed the reported review had persisted (accepted, human-reviewed, revision 7).
The reason disappeared because the detail component remounted on revision change and
initialized its input to an empty string. Initialize it from the saved decision and show
an explicit persisted human-review banner, decision and reason. No financial or review
API semantics changed. TypeScript and ESLint passed; the targeted V2 Playwright flow
passed with new assertions that the saved reason/banner survive full page reload.
A separate reported worker PostgreSQL SSL/rollback exception was not reproduced or
claimed fixed by this UI change.

### Zero-cost deployment preparation — 25 October 2026

User explicitly requires no paid services. Replaced the paid default Render blueprint
with one free web service and one free Key Value instance, using Supabase PostgreSQL.
Added `app/deployment/free_demo.py` to run startup migrations, one API, one solo Celery
worker and one embedded scheduler. Child failure shuts down the service group; shutdown
terminates child process groups, including Beat. E2E now exercises this actual launcher,
with Playwright graceful shutdown to prevent force-kill orphan processes. No artificial
keep-alive traffic, separate paid worker or paid database is provisioned.

Deployment review found direct anon/authenticated SELECT grants on Supabase tables
with RLS disabled. Added migration `a71d96c240be` to enable default-deny browser RLS
on all 21 app tables while retaining trusted server access through FastAPI. A dedicated
non-owner-role test confirms table reads are denied and insert is rejected even with
explicit table grants. Applied to the configured Supabase DB: revision confirmed, checked
business tables have RLS, and trusted backend queries still work. No data was deleted.

Validation: 106 backend tests passed; 3 browser E2E tests passed on the combined launcher
(final run 42.5 seconds), with clean API shutdown/no listener remaining on test port 8001.
Frontend production build, lint/format, backend Ruff, source/blueprint checks and preserved
V0-data migration verification passed. Scan for configured secret values in source passed;
local env and Vercel credential files are Git-ignored. Production URLs and hosted memory/
cold-start behavior remain unverified; Render's 512 MB/sleep limits still apply.

No public deploy, commit, push or hosted resources created. Git remote absent; Vercel CLI
has no credentials; user confirmed GitHub/Render/Vercel accounts/repository must be created.
Next external step is an empty private GitHub repository, followed by authenticated source
push, Vercel/Render free project setup, callback/CORS settings and hosted acceptance checks.
The current secrets and existing encryption key must stay local/hosting-secret only.
