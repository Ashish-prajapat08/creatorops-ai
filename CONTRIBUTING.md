# Contributing

Read `MASTER_CONTEXT.md` and `master_context_v1_v2.md` completely before changes. The active scope is V1/V2 on top of V0; V3 remains excluded.

Keep the modular monolith: route → validated contract → authorized service → tenant repository → PostgreSQL. Every business query scopes `agency_id`; cross-tenant relationships are also constrained by PostgreSQL. Never trust UI permissions.

Use Decimal for money; serialize it as strings. AI may draft prose and interpret messages, never write financial state or decide to execute a send. Approval must bind the reviewed revision and the saved context. External operations need durable idempotency barriers and audit records.

Schema changes need reviewed Alembic migrations, not runtime schema creation. Do not edit an applied migration. Keep `.env` and tokens out of Git. Keep source formatting, dependency locks and documentation current.

Run the backend suite against a dedicated `_test` PostgreSQL database, frontend checks, and the primary Playwright workflow before submitting a change. Add tests for changed critical workflows, tenant access, role permissions, structured AI boundaries, and failure recovery. Record acceptance evidence honestly; simulated providers are not live verification.
 