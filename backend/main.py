"""Command-line entry point for the PostgreSQL health check."""

from checks.connections import check_connection_health
from checks.database_health import check_database_health
from checks.locks import check_lock_health
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
                check_lock_health(connection),
                check_database_health(connection),
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
    if _should_print_summary(result):
        print(result.summary)

    if result.name == "Connection Health":
        _print_connection_metrics(metrics)
    elif result.name == "Transaction Health":
        _print_transaction_metrics(metrics)
    elif result.name == "Lock Health":
        _print_lock_metrics(metrics)
    elif result.name == "Database Health":
        _print_database_metrics(metrics)

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
    if metrics["open_transactions"] == 0:
        return

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


def _print_lock_metrics(metrics: dict[str, object]) -> None:
    """Print lock-specific health metrics."""
    print(f"Blocked sessions: {metrics['blocked_sessions']}")
    print(f"Blocking sessions: {metrics['blocking_sessions']}")
    if metrics["blocked_sessions"] == 0:
        return

    print(f"Blocked PID: {metrics['oldest_blocked_pid']}")
    print(f"Blocked for: {metrics['oldest_blocked_seconds']} seconds")
    print(
        "Wait event: "
        f"{metrics['blocked_wait_event_type']} / {metrics['blocked_wait_event']}"
    )
    print(f"Root blocker PID: {metrics['root_blocker_pid']}")
    print(f"Blocker user: {metrics['root_blocker_user']}")
    print(f"Blocker application: {metrics['root_blocker_application']}")
    print(f"Blocker state: {metrics['root_blocker_state']}")
    print(
        "Blocker transaction age: "
        f"{metrics['root_blocker_transaction_seconds']}"
    )


def _print_database_metrics(metrics: dict[str, object]) -> None:
    """Print database-level activity health metrics."""
    print(f"Database: {metrics['database_name']}")
    print(
        "Cache hit ratio: "
        f"{_format_percent(metrics['cache_hit_ratio_percent'])}"
    )
    print(
        "Rollback ratio: "
        f"{_format_percent(metrics['rollback_ratio_percent'])}"
    )
    print(f"Temporary files: {metrics['temp_files']}")
    print(f"Temporary bytes: {metrics['temp_bytes']}")
    print(f"Deadlocks: {metrics['deadlocks']}")
    if (
        metrics["cache_hit_ratio_percent"] is None
        and metrics["rollback_ratio_percent"] is None
    ):
        return

    print(f"Transactions committed: {metrics['transactions_committed']}")
    print(f"Transactions rolled back: {metrics['transactions_rolled_back']}")
    print(f"Blocks read: {metrics['blocks_read']}")
    print(f"Blocks hit: {metrics['blocks_hit']}")


def _should_print_summary(result: HealthCheckResult) -> bool:
    """Return whether the CLI should print a health result summary line."""
    metrics = result.metrics
    if result.name == "Transaction Health" and metrics["open_transactions"] == 0:
        return False
    if result.name == "Lock Health" and metrics["blocked_sessions"] == 0:
        return False
    if result.name == "Database Health" and result.status == "healthy":
        return False
    return True


def _format_percent(value: object) -> str:
    """Return a CLI-friendly percentage string."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


if __name__ == "__main__":
    main()
