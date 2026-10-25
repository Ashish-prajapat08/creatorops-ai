"""Deny direct Data API access; business access is authorized by FastAPI.

No permissive policies are installed. Runtime SQLAlchemy must connect as the
application table owner or a trusted BYPASSRLS role, never anon/authenticated.
"""

from alembic import op

revision = "a71d96c240be"
down_revision = "ff8cbac1385c"
branch_labels = None
depends_on = None

TABLES = (
    "agencies",
    "users",
    "agency_memberships",
    "brands",
    "creators",
    "campaigns",
    "invoices",
    "collection_tasks",
    "email_threads",
    "email_messages",
    "integrations",
    "oauth_states",
    "ai_actions",
    "audit_logs",
    "jobs",
    "email_analyses",
    "payment_promises",
    "email_syncs",
    "payment_transactions",
    "payment_allocations",
    "reconciliation_decisions",
)


def upgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
