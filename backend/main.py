"""Command-line entry point for the PostgreSQL health check."""

from checks.connections import check_connection_health
from config import ConfigError
from database import DatabaseConnectionError, get_connection
from models.health import HealthCheckResult


def main() -> None:
    """Attempt to connect to PostgreSQL and print the health check result."""
    try:
        with get_connection() as connection:
            print("✅ Connected to PostgreSQL")
            print()
            result = check_connection_health(connection)
            _print_health_check_result(result)
    except (ConfigError, DatabaseConnectionError) as exc:
        print("❌ Unable to connect:")
        print(str(exc))


def _print_health_check_result(result: HealthCheckResult) -> None:
    """Print a readable health check result for CLI users."""
    metrics = result.metrics

    print(result.name)
    print(f"Status: {result.status}")
    print(
        "Connections: "
        f"{metrics['current_connections']} / {metrics['max_connections']}"
    )
    print(f"Utilization: {metrics['connection_utilization_percent']:.1f}%")
    print(f"Active: {metrics['active_connections']}")
    print(f"Idle: {metrics['idle_connections']}")
    print(f"Idle in transaction: {metrics['idle_in_transaction_connections']}")
    print()
    print("Recommendation:")
    print(result.recommendation)


if __name__ == "__main__":
    main()
