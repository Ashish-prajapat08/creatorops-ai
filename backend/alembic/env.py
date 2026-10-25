from sqlalchemy import create_engine

from alembic import context
from app.core.config import settings
from app.core.database import Base
from app.models import entities  # noqa: F401


def run():
    if context.is_offline_mode():
        context.configure(
            url=settings().database_url,
            target_metadata=Base.metadata,
            literal_binds=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        with create_engine(settings().database_url).connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()


run()
