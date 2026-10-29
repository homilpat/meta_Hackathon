import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base

config = context.config
# DATABASE_URL replaces only the alembic.ini default; a URL set by the caller (tests: set_main_option) wins.
_url = config.get_main_option("sqlalchemy.url") or ""
_default = Path(config.config_file_name or "alembic.ini").resolve().parent / "qualityops.db"
if os.environ.get("DATABASE_URL") and _url.startswith("sqlite:///") and Path(_url[10:]).resolve() == _default:
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

