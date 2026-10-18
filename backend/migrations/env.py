import os

from alembic import context
from sqlalchemy import create_engine, text

from app.foundation import models as _foundation_models  # noqa: F401
from app.foundation.db import Base
from app.foundation.registry import discover
from app.foundation.settings import get_settings

for _m in discover():  # import every tool's models via its manifest
    pass

LEAST_PRIVILEGE = """
GRANT USAGE ON SCHEMA public TO itp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO itp_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO itp_app;
DO $$ BEGIN
  IF to_regclass('public.audit_events') IS NOT NULL THEN
    REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM itp_app;
  END IF;
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    REVOKE ALL ON alembic_version FROM itp_app;
  END IF;
END $$;
"""


def run() -> None:
    url = os.environ.get("ITP_OWNER_DATABASE_URL", get_settings().owner_database_url)
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
            conn.execute(text(LEAST_PRIVILEGE))


run()
