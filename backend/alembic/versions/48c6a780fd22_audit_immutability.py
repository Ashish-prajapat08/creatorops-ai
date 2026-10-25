"""Append-only audit records are enforced by PostgreSQL."""

from alembic import op

revision = "48c6a780fd22"
down_revision = "39f05e6ad89b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION creatorops_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'CreatorOps audit records are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION creatorops_audit_immutable();
    """)


def downgrade():
    op.execute("DROP TRIGGER audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION creatorops_audit_immutable()")
