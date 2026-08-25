"""Command-line entry point for the PostgreSQL health check."""

from checks.connections import check_connection_health
from checks.database_health import check_database_health
from checks.index_health import check_index_health
from checks.locks import check_lock_health
from checks.query_health import check_query_health
from checks.table_health import check_table_health
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
                check_table_health(connection),
                check_index_health(connection),
                check_query_health(connection),
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
    elif result.name == "Table Health":
        _print_table_metrics(metrics)
    elif result.name == "Index Health":
        _print_index_metrics(metrics)
    elif result.name == "Query Health":
        _print_query_metrics(metrics)

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


def _print_table_metrics(metrics: dict[str, object]) -> None:
    """Print table maintenance health metrics."""
    print(f"Tables checked: {metrics['tables_checked']}")
    print(f"Tables with dead tuples: {metrics['tables_with_dead_tuples']}")
    print(f"Warning tables: {metrics['warning_tables']}")
    print(f"Critical tables: {metrics['critical_tables']}")
    if metrics["warning_tables"] == 0 and metrics["critical_tables"] == 0:
        return

    print()
    print("Most concerning table:")
    print(f"{metrics['most_concerning_schema']}.{metrics['most_concerning_table']}")
    print(f"Live tuples: {metrics['most_concerning_live_tuples']}")
    print(f"Dead tuples: {metrics['most_concerning_dead_tuples']}")
    print(
        "Dead tuple ratio: "
        f"{_format_percent(metrics['highest_dead_tuple_ratio_percent'])}"
    )
    print(f"Last autovacuum: {metrics['most_concerning_last_autovacuum']}")
    print(f"Last autoanalyze: {metrics['most_concerning_last_autoanalyze']}")
    print(f"Updates: {metrics['most_concerning_updates']}")
    print(f"HOT updates: {metrics['most_concerning_hot_updates']}")


def _print_index_metrics(metrics: dict[str, object]) -> None:
    """Print index usage health metrics."""
    print(f"Indexes checked: {metrics['indexes_checked']}")
    print(f"Indexes used: {metrics['indexes_used']}")
    print(f"Zero-scan indexes: {metrics['indexes_with_zero_scans']}")
    print(f"Large review candidates: {metrics['large_zero_scan_indexes']}")
    print(f"Protected zero-scan indexes: {metrics['protected_zero_scan_indexes']}")
    if metrics["large_zero_scan_indexes"] == 0:
        return

    print()
    print("Largest review candidate:")
    print(f"{metrics['largest_review_candidate_name']}")
    print(f"Table: {metrics['largest_review_candidate_table']}")
    print(
        "Size: "
        f"{_format_bytes(metrics['largest_review_candidate_size_bytes'])}"
    )
    print("Scans: 0")
    print(
        "Tuples read/fetched: "
        f"{metrics['largest_review_candidate_idx_tup_read']} / "
        f"{metrics['largest_review_candidate_idx_tup_fetch']}"
    )


def _print_query_metrics(metrics: dict[str, object]) -> None:
    """Print query latency and cumulative execution health metrics."""
    if not metrics["pg_stat_statements_available"]:
        return

    print(f"Queries checked: {metrics['queries_checked']}")
    print(f"Total calls: {metrics['total_calls']}")
    print(f"Warning latency queries: {metrics['warning_latency_queries']}")
    print(f"Critical latency queries: {metrics['critical_latency_queries']}")
    if metrics["queries_checked"] == 0:
        return

    print()
    print("Slowest average query:")
    print(metrics["slowest_mean_query"])
    print(f"Calls: {metrics['slowest_mean_calls']}")
    print(
        "Mean execution time: "
        f"{_format_ms(metrics['slowest_mean_exec_time_ms'])}"
    )
    print(
        "Maximum execution time: "
        f"{_format_ms(metrics['slowest_mean_max_exec_time_ms'])}"
    )
    print(
        "Total execution time: "
        f"{_format_ms(metrics['slowest_mean_total_exec_time_ms'])}"
    )

    print()
    print("Top cumulative query:")
    print(metrics["top_total_query"])
    print(f"Calls: {metrics['top_total_calls']}")
    print(
        "Total execution time: "
        f"{_format_ms(metrics['top_total_exec_time_ms'])}"
    )


def _should_print_summary(result: HealthCheckResult) -> bool:
    """Return whether the CLI should print a health result summary line."""
    metrics = result.metrics
    if result.name == "Transaction Health" and metrics["open_transactions"] == 0:
        return False
    if result.name == "Lock Health" and metrics["blocked_sessions"] == 0:
        return False
    if result.name == "Database Health" and result.status == "healthy":
        return False
    if result.name == "Table Health" and result.status == "healthy":
        return False
    if result.name == "Index Health" and result.status == "healthy":
        return False
    if (
        result.name == "Query Health"
        and result.status == "healthy"
        and result.metrics["pg_stat_statements_available"]
    ):
        return False
    return True


def _format_percent(value: object) -> str:
    """Return a CLI-friendly percentage string."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def _format_bytes(value: object) -> str:
    """Return a CLI-friendly byte-size string."""
    if value is None:
        return "N/A"
    size_bytes = int(value)
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_mb:.0f} MB"


def _format_ms(value: object) -> str:
    """Return a CLI-friendly millisecond duration."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f} ms"


if __name__ == "__main__":
    main()
