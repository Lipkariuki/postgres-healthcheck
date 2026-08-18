"""PostgreSQL connection utilities."""

from psycopg import Connection, OperationalError, connect

from config import Config, ConfigError


class DatabaseConnectionError(RuntimeError):
    """Raised when a PostgreSQL connection cannot be established."""


def get_connection() -> Connection:
    """Return an open PostgreSQL connection using environment configuration."""
    try:
        config = Config.from_env()
    except ConfigError:
        raise

    try:
        return connect(
            host=config.db_host,
            port=config.db_port,
            dbname=config.db_name,
            user=config.db_user,
            password=config.db_password,
            connect_timeout=5,
        )
    except OperationalError as exc:
        raise DatabaseConnectionError(str(exc).strip()) from exc
