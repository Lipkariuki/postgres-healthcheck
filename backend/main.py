"""Command-line entry point for the PostgreSQL health check."""

import argparse

from checks.connections import check_connection_health
from checks.database_health import check_database_health
from checks.index_health import check_index_health
from checks.locks import check_lock_health
from checks.query_health import check_query_health
from checks.replication_health import check_replication_health
from checks.table_health import check_table_health
from checks.transactions import check_transaction_health
from config import ConfigError
from database import DatabaseConnectionError, get_connection
from models.health import HealthCheckResult
from reporting import (
    render_error_json,
    render_health_check_result,
    render_human_report,
    render_json_report,
)


def main(argv: list[str] | None = None) -> None:
    """Run PostgreSQL health checks and print the requested report format."""
    args = _parse_args(argv)
    try:
        with get_connection() as connection:
            results = collect_health_checks(connection)
    except (ConfigError, DatabaseConnectionError) as exc:
        if args.json:
            print(render_error_json(exc))
        else:
            print("❌ Unable to connect:")
            print(str(exc))
        return

    if args.json:
        print(render_json_report(results))
    else:
        print(render_human_report(results))


def collect_health_checks(connection: object) -> list[HealthCheckResult]:
    """Run all configured health checks using an existing connection."""
    return [
        check_connection_health(connection),
        check_transaction_health(connection),
        check_lock_health(connection),
        check_database_health(connection),
        check_table_health(connection),
        check_index_health(connection),
        check_query_health(connection),
        check_replication_health(connection),
    ]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run PostgreSQL health checks.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="output the health report as JSON",
    )
    return parser.parse_args(argv)


def _print_health_check_result(result: HealthCheckResult) -> None:
    """Print one health check result section for backwards-compatible tests."""
    print(render_health_check_result(result))


if __name__ == "__main__":
    main()
