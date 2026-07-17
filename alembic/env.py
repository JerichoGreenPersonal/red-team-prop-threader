"""alembic environment configuration for red-team-prop-threader migrations."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# import application metadata so alembic can compare against it
from red_team_prop_threader.tables import Base
from red_team_prop_threader.db import resolve_migration_url

config = context.config

# configure python logging from the ini file section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve the URL without allowing DATABASE_URL to override an explicit target."""
    override = config.attributes.get("database_url_override")
    if override is not None and not isinstance(override, str):
        raise TypeError("database_url_override must be a string")
    return resolve_migration_url(
        explicit_override=override,
        configured_url=config.get_main_option("sqlalchemy.url", "sqlite:///local/prop-threader.db"),
    )


def run_migrations_offline() -> None:
    """run migrations in 'offline' mode without a live DB connection.

    this mode emits SQL to stdout or a file for review. the URL is resolved
    from the alembic config (which callers may override via set_main_option).
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """run migrations in 'online' mode with an active DB connection."""
    cfg_section = config.get_section(config.config_ini_section, {})
    cfg_section["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
