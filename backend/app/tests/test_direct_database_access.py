from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import Base, engine
from app.tests.conftest import records, workspace


def test_non_owner_browser_role_cannot_read_or_insert_business_data(client):
    headers = workspace(client)
    records(client, headers)
    role = "creatorops_probe_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Transactional role creation is rolled back at the end of this test.
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            for table in Base.metadata.tables:
                assert (
                    connection.execute(
                        text(
                            "SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=:name"
                        ),
                        {"name": table},
                    ).scalar()
                    is True
                )
                connection.execute(text(f'GRANT SELECT, INSERT ON "{table}" TO "{role}"'))
            assert connection.execute(text("SELECT count(*) FROM agencies")).scalar() > 0
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            for table in Base.metadata.tables:
                assert connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() == 0
            with pytest.raises(DBAPIError) as failure, connection.begin_nested():
                connection.execute(
                    text("""
                    INSERT INTO agencies (id,name,slug,default_currency,timezone,created_at,updated_at)
                    VALUES (gen_random_uuid(),'blocked','blocked','USD','UTC',now(),now())
                """)
                )
            assert failure.value.orig.sqlstate == "42501"
        finally:
            transaction.rollback()
