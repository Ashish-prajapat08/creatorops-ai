# Historical V0 acceptance report

This file records the V0 baseline. For the current V1/V2 scope and final verification, see [V1/V2 implementation report](v1-v2-implementation.md).

# V0 implementation and acceptance evidence

The supplied context was read completely before implementation. The repository initially contained only `master_contex.md`; `MASTER_CONTEXT.md` is an exact copy. No future-scope features were implemented.

Status vocabulary: **verified locally** means executable evidence against the real application/database; **provider-adapter verified** means the external provider was simulated; **pending live** requires configured accounts or cloud access. Local checks are not a claim that CI or deployment has run.

## Phase acceptance

| Phase | Acceptance result | Evidence and remaining live checks |
|---|---|---|
| 1 Foundation | Verified locally | Git initialized; Next.js/TypeScript/Tailwind/Radix UI; FastAPI/Pydantic/SQLAlchemy/Alembic; PostgreSQL 17 and Redis 7 running through Compose. Backend Linux image built; production frontend build passes. Locked runtime/development dependencies and CI configuration included. |
| 2 Auth/workspace | Implemented; provider-adapter verified | Supabase signup/login screens; provider-verified bearer sessions; email confirmation enforced; workspace creation/switching and member creation/removal; five-role RBAC matrix; no custom credentials. Tests cover forged sessions, unconfirmed identity, concurrent first login, last-owner retention and admin ownership escalation. Real Supabase signup/email confirmation remains pending. |
| 3 Core entities | Verified locally | Brands, creators, campaigns and invoices CRUD; validation, pagination, related-record views, backend authorization, cross-tenant reads/writes and relationship constraints. Issued invoices retained via voiding; draft deletes tested. |
| 4 Dashboard | Verified locally | Decimal totals grouped by currency; outstanding/overdue/due-soon/paid; overdue table and pending approval count. Exact `0.10 + 0.20 = 0.30` test; no JS float money arithmetic. |
| 5 Overdue engine | Verified locally | Tenant timezone date logic; paid/void/draft exclusion; scheduled Celery scan; immediate scan; four concurrent scanners generate exactly one collection task. |
| 6 Gmail | Implemented; provider-adapter verified | OAuth PKCE, hashed one-use expiring state, encrypted access/refresh tokens, tenant-scoped integration, plaintext-only deterministic invoice/brand matching, send and reconciliation client. Callback replay/expiration/encryption tests pass. Live consent, refresh, mailbox context and delivery remain pending. |
| 7 AI collections | Implemented; provider-adapter verified | OpenAI Pydantic structured output; LangGraph generation/validation; informational inbound intent; verbatim evidence check; deterministic invoice facts/recipient; extra keys, numeric facts, fees, legal threats, invalid enums/confidence and fabricated evidence rejected. Live model quality/accuracy is not claimed. |
| 8 Human approval | Verified locally | Review, edit, save revision, reject, approve exact saved draft; stale revisions rejected; invoice/recipient/sender snapshot checked before execution; revoked approval is blocked. Primary browser test exercises actual API + Redis + Celery. |
| 9 Audit | Verified locally | Generation, edits, approval, rejection, send initiation/result/failures and integration changes audited. Financial edits retain before/after truth. Reviewed email revisions preserved. PostgreSQL rejects audit updates/deletes; human-readable UI history. |
| 10 Testing | Verified locally; hosted CI pending | Unit/integration/AI contract/security tests and primary Playwright browser workflow run locally. CI YAML performs lint, formatting, typecheck, migrations, tests, build and runtime dependency audit. No remote repository/Actions execution yet. |
| 11 Demo data | Verified locally | Idempotent six-invoice seed: one paid, two upcoming, three overdue; three brands/creators/campaigns; three collection tasks; sample messages. Requires an application user and never fakes production identity/integration. |
| 12 Deployment | Release configuration prepared; pending live | Vercel config, Render blueprint, non-root Linux backend image, migration release command, health checks and deployment/provider setup guide. No public deployment URLs or hosted database/worker verification yet. |

## Executed checks

- PostgreSQL backend tests: **49 passing** before the final approval-revocation regression was added; final count recorded below after rerun.
- Playwright Chromium: **2 passing**, including create → draft → edit → approve → worker send → audit, and unauthenticated route protection. Provider adapters are explicit; application HTTP, database, broker, worker and UI are real.
- Frontend TypeScript and ESLint checks: passing.
- Next.js webpack production build: passing for all V0 routes.
- Backend Ruff lint and formatting: passing.
- Alembic upgrade and schema drift detection: passing; no new upgrade operations detected.
- Linux backend image: built successfully with locked dependencies.
- Source/CI/Render/Vercel configuration parse checks: passing.
- Frontend production dependency audit: **0 vulnerabilities** in the installed runtime tree.
- Git ignore checks cover root/backend/frontend environment files, virtualenv, node_modules and generated test/build artifacts. Source context copy verified byte-for-byte.

## Material limits and outstanding release checks

1. Configure real Supabase, OpenAI, and Google OAuth values in ignored environment files/hosting secrets. No live credentials were available, and no real email was sent during tests.
2. Run the provider and cloud release verification in `deployment.md`, then record URLs and evidence here. The complete definition of done remains open until these pass. Provider-adapter tests do not prove live model quality or provider configuration.
3. The installed `braces@3.0.3` has an unresolved stack-exhaustion advisory inherited via Next ESLint → fast-glob → micromatch. The registry currently exposes no patched release. Five reported high entries describe this same development-tool dependency chain; the production dependency tree audits clean. Upgrade the lint tooling when a safe patched version becomes available; do not downgrade the application stack blindly.
4. A Gmail timeout/crash can leave `SEND_UNCERTAIN`. Reconciliation searches by deterministic Message-ID, but absence cannot prove a failed send. V0 deliberately refuses automatic resend to prevent duplication; operational investigation may be required.
5. Currency totals are separate and precision is two decimals; V0 does not convert currencies or verify actual payment receipt. Email claims never mark invoices paid.

## Live release record

```text
Frontend URL: pending
API URL: pending
Release identifier: pending
Supabase signup/login: pending
Google OAuth/context/refresh: pending
Live OpenAI draft and human review: pending
Controlled Gmail delivery (one message): pending
Hosted CI: pending
Hosted API/database/Redis/worker readiness: pending
Sentry/LangSmith account verification: pending if configured
```
