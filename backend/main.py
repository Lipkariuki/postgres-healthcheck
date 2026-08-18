"""Command-line entry point for the PostgreSQL health check."""

from checks.connections import check_connection_health
from checks.transactions import check_transaction_health
from config import ConfigError
from database import DatabaseConnectionError, get_connection
from models.health import HealthCheckResult


def main() -> None:
    """Attempt to connect to PostgreSQL and print the health check result."""
    try:
        with get_connection() as connection:
            print("✅ Connected to PostgreSQL")
            print()
            results = [
                check_connection_health(connection),
                check_transaction_health(connection),
            ]
            for index, result in enumerate(results):
                if index > 0:
                    print()
                _print_health_check_result(result)
    except (ConfigError, DatabaseConnectionError) as exc:
        print("❌ Unable to connect:")
        print(str(exc))


def _print_health_check_result(result: HealthCheckResult) -> None:
    """Print a readable health check result for CLI users."""
    metrics = result.metrics

    print(result.name)
    print(f"Status: {result.status}")
    print(result.summary)

    if result.name == "Connection Health":
        _print_connection_metrics(metrics)
    elif result.name == "Transaction Health":
        _print_transaction_metrics(metrics)

    print()
    print("Recommendation:")
    print(result.recommendation)


def _print_connection_metrics(metrics: dict[str, object]) -> None:
    """Print connection-specific health metrics."""
    print(
        "Connections: "
        f"{metrics['current_connections']} / {metrics['max_connections']}"
    )
    print(f"Utilization: {metrics['connection_utilization_percent']:.1f}%")
    print(f"Active: {metrics['active_connections']}")
    print(f"Idle: {metrics['idle_connections']}")
    print(f"Idle in transaction: {metrics['idle_in_transaction_connections']}")


def _print_transaction_metrics(metrics: dict[str, object]) -> None:
    """Print transaction-specific health metrics."""
    print(f"Open transactions: {metrics['open_transactions']}")
    print(f"Long-running transactions: {metrics['long_running_transactions']}")
    print(f"Oldest transaction PID: {metrics['oldest_transaction_pid']}")
    print(f"Oldest transaction age: {metrics['oldest_transaction_seconds']}")
    print(f"Oldest transaction state: {metrics['oldest_transaction_state']}")
    print(f"Oldest transaction user: {metrics['oldest_transaction_user']}")
    print(
        "Oldest transaction application: "
        f"{metrics['oldest_transaction_application']}"
    )
    print(
        "Oldest transaction wait event: "
        f"{metrics['oldest_transaction_wait_event_type']} / "
        f"{metrics['oldest_transaction_wait_event']}"
    )


if __name__ == "__main__":
    main()
