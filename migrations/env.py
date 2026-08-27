from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import create_engine

from config.settings import get_settings
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.engine import AZURE_SERVERLESS_RESUME_TIMEOUT_SECONDS, build_connection_url
from persistence.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL is Settings-driven (env vars / Parameter Store), built directly
# rather than via config.set_main_option(): the URL-encoded password
# contains "%" characters that ConfigParser's interpolation chokes on.
_settings = get_settings()
_connection_url = build_connection_url(_settings)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=_connection_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Only local dev's own fresh Azure SQL Edge container needs its database
    # created -- deployed envs reuse an already-existing database (see
    # docs/ROADMAP.md Phase 10) via a contained DB user with no `master`
    # access at all, so this would fail with a genuine "Login failed" (not
    # a credentials problem) rather than a no-op. Found live running MM-102's
    # first deployed migration.
    if _settings.app_env == "local":
        ensure_database_exists(_settings)
    connectable = create_engine(
        _connection_url,
        poolclass=pool.NullPool,
        connect_args={"timeout": AZURE_SERVERLESS_RESUME_TIMEOUT_SECONDS},
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
