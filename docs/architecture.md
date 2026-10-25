# V0 architecture decisions

## Boundaries

`backend/app/api/v1` is the HTTP boundary. Pydantic request and response contracts live in `schemas`. Authorization and identity verification live in `core/security.py`. Services own state transitions and transaction boundaries; `repositories/tenant.py` scopes business queries. SQLAlchemy models and migrations enforce tenant-owned references, financial ranges, statuses, uniqueness and audit immutability. FastAPI is the single backend; Celery processes work from that same codebase.

The frontend API client is the only browser HTTP layer. Workspace context resolves identity/membership, protected screens handle loading/errors/empty states, and reusable Radix-based UI components provide accessible controls and dialogs. Financial values stay strings in browser code.

## Narrow AI contract

The collections service loads invoice, brand, and deterministic Gmail matches. LangGraph orchestrates generation and validation. OpenAI's [structured-output API](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) is parsed into Pydantic schemas. The model returns greeting, request, closing and email-understanding fields. Invoice subject, amount, currency, due date and recipient are inserted by deterministic code.

The model has no tools or financial mutation access. Email text is explicitly untrusted data. The validator rejects additional fields, invalid intents/confidence, fabricated evidence, prose containing numeric financial facts/fees/legal threats, and promised-date extraction (future V1 scope). Intent summaries are informational; `PAYMENT_SENT` is not evidence of receipt and cannot change status. The human reviews all prose. These checks reduce hallucinations; they do not claim semantic certainty or perfect prompt-injection resistance.

The structured-output tests validate the contract and guardrails using fixed fixtures and provider adapters. They are not a claim about live model accuracy. Live model evaluation requires a configured key and recorded evaluation samples.

## Approval and execution

PostgreSQL is the checkpoint for the human wait; LangGraph is only the drafting workflow. Drafts carry revisions. Edit increments the revision. Approval requires the current revision, stores exact content, invoice facts, recipient, sender, approver and time, then inserts a send job atomically. An invoice edit invalidates unapproved drafts; approved/in-flight tasks block edits. A changed brand contact invalidates approval.

Job intent lives in the database outbox. Redis/Celery is transport. Beat periodically dispatches pending jobs; duplicate transport delivery is harmless because each database job is claimed once. Overdue scanners lock an agency's invoice set and create at most one V0 collection task per invoice. This is intentionally a single-follow-up V0, not V1 scheduled collection campaigns.

Gmail sending uses a committed barrier before the external operation. A lost confirmation can therefore leave an unsent task uncertain, but cannot cause a retry to send twice. Reconciliation only reads Sent mail. V0 does not claim exactly-once Gmail delivery. Database audit rows record generation, edits, approvals, send initiation, success, failure, and recovery requests; updates/deletes are blocked by a PostgreSQL trigger.

## Deliberate V0 choices

- Supabase owns sign-up, credential storage, email confirmation and sessions. The backend validates each session through `/auth/v1/user`, then uses application memberships for authorization. No custom password system.
- Membership creation adds an existing signed-in application user. No separate invitation email infrastructure is needed for the specification's invite/create-members criterion.
- Owner/Admin manage integrations and membership. Finance approves communications; Ops prepares drafts; Viewer reads. Owners retain control over ownership changes.
- Currency totals are separate. The supported precision is two decimal places. Currency conversion, tax, commission/payout calculation, payment evidence and reconciliation are outside V0.
- Unissued invoice drafts are never collected. Issued invoices are voided rather than deleted to preserve financial history.
- One worker service has an embedded Beat process. Keep exactly one Beat scheduler. Scaling out workers would require moving Beat to a single separate process, which is not necessary for V0.
- A sanitized outer LangSmith trace tracks workflow latency/results; raw email/state tracing is disabled. Sentry is optional and redacted. Neither integration is a prerequisite for local tests.
- Next's webpack mode is used because the default CSS helper failed under the host's process/port restrictions. No stack was replaced.

## Provider references

[Supabase session verification](https://supabase.com/docs/guides/auth/jwts) supports server-side validation for both signing-key modes. [Google's Gmail scope documentation](https://developers.google.com/workspace/gmail/api/auth/scopes) distinguishes read and send access; V0 avoids modify, delete and mailbox-wide management scopes.

## V1/V2 extension

The active scope is now `master_context_v1_v2.md`; the V0 decisions above describe the original baseline. Stage-specific collection tasks, versioned email analyses/promises, polling checkpoints, manual payment transactions, reviewed allocations and reversals extend the same monolith. See `v1-v2-implementation.md` for the normalized model, migration, API/UI modules and current verification. Legacy V0 manually paid invoices are not converted into fabricated payment records. Email claims remain separate from confirmed manual allocations and never establish payment receipt by themselves.
