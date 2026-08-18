"""Connection health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


CONNECTION_COUNTS_SQL = """
SELECT
    COUNT(*) AS current_connections,
    COUNT(*) FILTER (WHERE state = 'active') AS active_connections,
    COUNT(*) FILTER (WHERE state = 'idle') AS idle_connections,
    COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction_connections
FROM pg_stat_activity;
"""

OLDEST_IDLE_TRANSACTION_SQL = """
SELECT
    pid,
    EXTRACT(EPOCH FROM (now() - xact_start)) AS transaction_age_seconds
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND xact_start IS NOT NULL
ORDER BY xact_start ASC
LIMIT 1;
"""

OLD_IDLE_TRANSACTION_SECONDS = 30 * 60


def check_connection_health(connection: Any) -> HealthCheckResult:
    """Check PostgreSQL connection utilization using an existing connection."""
    with connection.cursor() as cursor:
        cursor.execute(CONNECTION_COUNTS_SQL)
        counts_row = cursor.fetchone()

        cursor.execute(OLDEST_IDLE_TRANSACTION_SQL)
        oldest_idle_transaction_row = cursor.fetchone()

        cursor.execute("SHOW max_connections;")
        max_connections_row = cursor.fetchone()

    if counts_row is None:
        raise RuntimeError("Unable to read connection counts from pg_stat_activity")
    if max_connections_row is None:
        raise RuntimeError("Unable to read max_connections")

    current_connections = int(counts_row[0])
    active_connections = int(counts_row[1])
    idle_connections = int(counts_row[2])
    idle_in_transaction = int(counts_row[3])
    oldest_idle_transaction_pid: int | None = None
    oldest_idle_transaction_seconds: float | None = None
    if oldest_idle_transaction_row is not None:
        oldest_idle_transaction_pid = int(oldest_idle_transaction_row[0])
        oldest_idle_transaction_seconds = float(oldest_idle_transaction_row[1])

    max_connections = int(max_connections_row[0])

    if max_connections <= 0:
        raise RuntimeError("PostgreSQL max_connections must be greater than zero")

    utilization_percent = (current_connections / max_connections) * 100
    status = _status_for_utilization(utilization_percent)

    summary = (
        f"{current_connections} of {max_connections} connections are in use "
        f"({utilization_percent:.1f}%)."
    )

    recommendation = _recommendation_for(
        status,
        idle_in_transaction,
        oldest_idle_transaction_seconds,
    )

    return HealthCheckResult(
        name="Connection Health",
        status=status,
        summary=summary,
        metrics={
            "current_connections": current_connections,
            "active_connections": active_connections,
            "idle_connections": idle_connections,
            "idle_in_transaction_connections": idle_in_transaction,
            "oldest_idle_transaction_pid": oldest_idle_transaction_pid,
            "oldest_idle_transaction_seconds": oldest_idle_transaction_seconds,
            "max_connections": max_connections,
            "connection_utilization_percent": utilization_percent,
        },
        recommendation=recommendation,
    )


def _status_for_utilization(utilization_percent: float) -> str:
    """Return the health status for a connection utilization percentage."""
    if utilization_percent < 70:
        return "healthy"
    if utilization_percent <= 90:
        return "warning"
    return "critical"


def _recommendation_for(
    status: str,
    idle_in_transaction: int,
    oldest_idle_transaction_seconds: float | None,
) -> str:
    """Return an actionable recommendation for the connection health result."""
    if status == "healthy":
        recommendation = "Connection capacity is healthy."
    elif status == "warning":
        recommendation = (
            "Connection utilization is elevated. Review application connection "
            "pool sizing and connection lifecycle behavior."
        )
    else:
        recommendation = (
            "Connection utilization is critical. Reduce connection usage or "
            "increase max_connections after reviewing database capacity."
        )

    if idle_in_transaction > 0:
        idle_transaction_warning = (
            "Idle-in-transaction sessions are present. Long-lived open "
            "transactions can retain locks, prevent VACUUM from reclaiming "
            "obsolete tuple versions, and contribute to table bloat."
        )
        if (
            oldest_idle_transaction_seconds is not None
            and oldest_idle_transaction_seconds > OLD_IDLE_TRANSACTION_SECONDS
        ):
            idle_transaction_warning = (
                f"Urgent: the oldest idle-in-transaction session has been open "
                f"for {oldest_idle_transaction_seconds:.0f} seconds. "
                "Do not automatically terminate it; investigate the session "
                "owner and application behavior. Long-lived open transactions "
                "can retain locks, prevent VACUUM from reclaiming obsolete "
                "tuple versions, and contribute to table bloat."
            )

        if status == "healthy":
            return f"Connection capacity is healthy. {idle_transaction_warning}"
        return f"{recommendation} {idle_transaction_warning}"

    return recommendation
