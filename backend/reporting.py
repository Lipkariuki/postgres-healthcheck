"""Human-readable and JSON reporting for PostgreSQL health checks."""

from __future__ import annotations

import json
from dataclasses import asdict

from models.health import HealthCheckResult


STATUS_SEVERITY = {
    "healthy": 0,
    "warning": 1,
    "critical": 2,
}

STATUS_MARKERS = {
    "healthy": "✓",
    "warning": "⚠",
    "critical": "✖",
}


def overall_status(results: list[HealthCheckResult]) -> str:
    """Return the strongest status from a list of health check results."""
    if not results:
        return "healthy"
    return max(results, key=lambda result: STATUS_SEVERITY[result.status]).status


def render_human_report(results: list[HealthCheckResult]) -> str:
    """Return a complete human-readable health check report."""
    lines = [
        "PostgreSQL Health Check",
        f"Database: {_database_name(results)}",
        "",
        f"Overall Status: {overall_status(results).upper()}",
        "",
        "Checks",
    ]

    name_width = max((len(result.name) for result in results), default=0)
    for result in results:
        marker = STATUS_MARKERS.get(result.status, "?")
        lines.append(f"{marker} {result.name:<{name_width}}  {result.status}")

    for result in results:
        lines.extend(["", render_health_check_result(result)])

    return "\n".join(lines)


def render_json_report(results: list[HealthCheckResult]) -> str:
    """Return a machine-readable JSON health check report."""
    payload = {
        "overall_status": overall_status(results),
        "checks": [asdict(result) for result in results],
    }
    return json.dumps(payload, default=str)


def render_error_json(reason: object) -> str:
    """Return structured JSON for expected connection or configuration errors."""
    return json.dumps(
        {
            "status": "error",
            "error": "Unable to connect",
            "reason": str(reason),
        }
    )


def render_health_check_result(result: HealthCheckResult) -> str:
    """Return a readable section for one health check result."""
    metrics = result.metrics
    lines = [
        result.name,
        f"Status: {result.status}",
    ]
    if _should_print_summary(result):
        lines.extend(["", result.summary])

    lines.append("")
    if result.name == "Connection Health":
        lines.extend(_connection_metric_lines(metrics))
    elif result.name == "Transaction Health":
        lines.extend(_transaction_metric_lines(metrics))
    elif result.name == "Lock Health":
        lines.extend(_lock_metric_lines(metrics))
    elif result.name == "Database Health":
        lines.extend(_database_metric_lines(metrics))
    elif result.name == "Table Health":
        lines.extend(_table_metric_lines(metrics))
    elif result.name == "Index Health":
        lines.extend(_index_metric_lines(metrics))
    elif result.name == "Query Health":
        lines.extend(_query_metric_lines(metrics))
    elif result.name == "Replication & WAL Health":
        lines.extend(_replication_metric_lines(metrics))

    lines.extend(["", "Recommendation:", result.recommendation])
    return "\n".join(lines)


def format_duration(seconds: object) -> str:
    """Return a compact human-readable duration from seconds."""
    if seconds is None:
        return "N/A"

    remaining_seconds = int(float(seconds))
    if remaining_seconds < 0:
        remaining_seconds = 0

    days, remaining_seconds = divmod(remaining_seconds, 86400)
    hours, remaining_seconds = divmod(remaining_seconds, 3600)
    minutes, remaining_seconds = divmod(remaining_seconds, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if remaining_seconds or not parts:
        parts.append(f"{remaining_seconds}s")
    return " ".join(parts)


def format_bytes(value: object) -> str:
    """Return a human-readable byte size."""
    if value is None:
        return "N/A"

    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while abs(size) >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_index]}"


def format_percent(value: object) -> str:
    """Return a CLI-friendly percentage string."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def format_ms(value: object) -> str:
    """Return a CLI-friendly millisecond duration."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f} ms"


def _database_name(results: list[HealthCheckResult]) -> str:
    """Return the current database name when a check reports it."""
    for result in results:
        database_name = result.metrics.get("database_name")
        if database_name is not None:
            return str(database_name)
    return "unknown"


def _connection_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return connection-specific health metric lines."""
    lines = [
        f"Connections: {metrics['current_connections']} / {metrics['max_connections']}",
        f"Utilization: {float(metrics['connection_utilization_percent']):.1f}%",
        f"Active: {metrics['active_connections']}",
        f"Idle: {metrics['idle_connections']}",
        f"Idle in transaction: {metrics['idle_in_transaction_connections']}",
    ]
    if int(metrics["idle_in_transaction_connections"]) > 0:
        lines.append(
            "Oldest idle transaction PID: "
            f"{metrics['oldest_idle_transaction_pid']}"
        )
        lines.append(
            "Oldest idle transaction age: "
            f"{format_duration(metrics['oldest_idle_transaction_seconds'])}"
        )
    return lines


def _transaction_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return transaction-specific health metric lines."""
    lines = [
        f"Open transactions: {metrics['open_transactions']}",
        f"Long-running transactions: {metrics['long_running_transactions']}",
    ]
    if metrics["open_transactions"] == 0:
        return lines

    lines.extend(
        [
            f"Oldest transaction PID: {metrics['oldest_transaction_pid']}",
            "Oldest transaction age: "
            f"{format_duration(metrics['oldest_transaction_seconds'])}",
            f"Oldest transaction state: {metrics['oldest_transaction_state']}",
            f"Oldest transaction user: {metrics['oldest_transaction_user']}",
            "Oldest transaction application: "
            f"{metrics['oldest_transaction_application']}",
            "Oldest transaction wait event: "
            f"{metrics['oldest_transaction_wait_event_type']} / "
            f"{metrics['oldest_transaction_wait_event']}",
        ]
    )
    return lines


def _lock_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return lock-specific health metric lines."""
    lines = [
        f"Blocked sessions: {metrics['blocked_sessions']}",
        f"Blocking sessions: {metrics['blocking_sessions']}",
    ]
    if metrics["blocked_sessions"] == 0:
        return lines

    lines.extend(
        [
            f"Blocked PID: {metrics['oldest_blocked_pid']}",
            f"Blocked for: {format_duration(metrics['oldest_blocked_seconds'])}",
            "Wait event: "
            f"{metrics['blocked_wait_event_type']} / {metrics['blocked_wait_event']}",
            f"Root blocker PID: {metrics['root_blocker_pid']}",
            f"Blocker user: {metrics['root_blocker_user']}",
            f"Blocker application: {metrics['root_blocker_application']}",
            f"Blocker state: {metrics['root_blocker_state']}",
            "Blocker transaction age: "
            f"{format_duration(metrics['root_blocker_transaction_seconds'])}",
        ]
    )
    return lines


def _database_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return database-level activity health metric lines."""
    lines = [
        f"Database: {metrics['database_name']}",
        f"Cache hit ratio: {format_percent(metrics['cache_hit_ratio_percent'])}",
        f"Rollback ratio: {format_percent(metrics['rollback_ratio_percent'])}",
        f"Temporary files: {metrics['temp_files']}",
        f"Temporary bytes: {format_bytes(metrics['temp_bytes'])}",
        f"Deadlocks: {metrics['deadlocks']}",
    ]
    if (
        metrics["cache_hit_ratio_percent"] is None
        and metrics["rollback_ratio_percent"] is None
    ):
        return lines

    lines.extend(
        [
            f"Transactions committed: {metrics['transactions_committed']}",
            f"Transactions rolled back: {metrics['transactions_rolled_back']}",
            f"Blocks read: {metrics['blocks_read']}",
            f"Blocks hit: {metrics['blocks_hit']}",
        ]
    )
    return lines


def _table_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return table maintenance health metric lines."""
    lines = [
        f"Tables checked: {metrics['tables_checked']}",
        f"Tables with dead tuples: {metrics['tables_with_dead_tuples']}",
        f"Warning tables: {metrics['warning_tables']}",
        f"Critical tables: {metrics['critical_tables']}",
    ]
    if metrics["warning_tables"] == 0 and metrics["critical_tables"] == 0:
        return lines

    lines.extend(
        [
            "",
            "Most concerning table:",
            f"{metrics['most_concerning_schema']}.{metrics['most_concerning_table']}",
            f"Live tuples: {metrics['most_concerning_live_tuples']}",
            f"Dead tuples: {metrics['most_concerning_dead_tuples']}",
            "Dead tuple ratio: "
            f"{format_percent(metrics['highest_dead_tuple_ratio_percent'])}",
            f"Last autovacuum: {metrics['most_concerning_last_autovacuum']}",
            f"Last autoanalyze: {metrics['most_concerning_last_autoanalyze']}",
            f"Updates: {metrics['most_concerning_updates']}",
            f"HOT updates: {metrics['most_concerning_hot_updates']}",
        ]
    )
    return lines


def _index_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return index usage health metric lines."""
    lines = [
        f"Indexes checked: {metrics['indexes_checked']}",
        f"Indexes used: {metrics['indexes_used']}",
        f"Zero-scan indexes: {metrics['indexes_with_zero_scans']}",
        f"Large review candidates: {metrics['large_zero_scan_indexes']}",
        f"Protected zero-scan indexes: {metrics['protected_zero_scan_indexes']}",
    ]
    if metrics["large_zero_scan_indexes"] == 0:
        return lines

    lines.extend(
        [
            "",
            "Largest review candidate:",
            f"{metrics['largest_review_candidate_name']}",
            f"Table: {metrics['largest_review_candidate_table']}",
            "Size: "
            f"{format_bytes(metrics['largest_review_candidate_size_bytes'])}",
            "Scans: 0",
            "Tuples read/fetched: "
            f"{metrics['largest_review_candidate_idx_tup_read']} / "
            f"{metrics['largest_review_candidate_idx_tup_fetch']}",
        ]
    )
    return lines


def _query_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return query latency and cumulative execution metric lines."""
    if not metrics["pg_stat_statements_available"]:
        return []

    lines = [
        f"Queries checked: {metrics['queries_checked']}",
        f"Total calls: {metrics['total_calls']}",
        f"Warning latency queries: {metrics['warning_latency_queries']}",
        f"Critical latency queries: {metrics['critical_latency_queries']}",
    ]
    if metrics["queries_checked"] == 0:
        return lines

    lines.extend(
        [
            "",
            "Slowest average query:",
            str(metrics["slowest_mean_query"]),
            f"Calls: {metrics['slowest_mean_calls']}",
            "Mean execution time: "
            f"{format_ms(metrics['slowest_mean_exec_time_ms'])}",
            "Maximum execution time: "
            f"{format_ms(metrics['slowest_mean_max_exec_time_ms'])}",
            "Total execution time: "
            f"{format_ms(metrics['slowest_mean_total_exec_time_ms'])}",
            "",
            "Top cumulative query:",
            str(metrics["top_total_query"]),
            f"Calls: {metrics['top_total_calls']}",
            "Total execution time: "
            f"{format_ms(metrics['top_total_exec_time_ms'])}",
        ]
    )
    return lines


def _replication_metric_lines(metrics: dict[str, object]) -> list[str]:
    """Return replication and WAL health metric lines."""
    lines = [
        f"Server role: {metrics['server_role']}",
        f"Replicas connected: {metrics['replicas_connected']}",
        f"Warning replicas: {metrics['warning_replicas']}",
        f"Critical replicas: {metrics['critical_replicas']}",
        f"WAL bytes recorded: {format_bytes(metrics['wal_bytes'])}",
        f"WAL records: {metrics['wal_records']}",
        f"WAL buffers full: {metrics['wal_buffers_full']}",
    ]

    if metrics["server_role"] == "replica":
        lines.extend(
            [
                f"Last WAL receive LSN: {metrics['last_wal_receive_lsn']}",
                f"Last WAL replay LSN: {metrics['last_wal_replay_lsn']}",
                f"Replay delay: {format_duration(metrics['replay_delay_seconds'])}",
            ]
        )
        return lines

    if metrics["replicas_connected"] == 0:
        return lines

    lines.extend(
        [
            "",
            "Most lagging replica:",
            f"Application: {metrics['most_lagging_replica_application']}",
            f"Client address: {metrics['most_lagging_replica_client_addr']}",
            f"State: {metrics['most_lagging_replica_state']}",
            f"Sync state: {metrics['most_lagging_replica_sync_state']}",
            "Replay lag: "
            f"{format_duration(metrics['most_lagging_replay_lag_seconds'])}",
        ]
    )
    return lines


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
    if result.name == "Replication & WAL Health" and result.status == "healthy":
        return False
    return True
