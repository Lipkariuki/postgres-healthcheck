"""Long-running transaction health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


TRANSACTION_ACTIVITY_SQL = """
SELECT
    pid,
    usename,
    application_name,
    state,
    EXTRACT(EPOCH FROM (now() - xact_start)) AS transaction_age_seconds,
    wait_event_type,
    wait_event,
    LEFT(query, 150) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND pid <> pg_backend_pid()
ORDER BY xact_start ASC;
"""

LONG_RUNNING_TRANSACTION_SECONDS = 5 * 60
CRITICAL_TRANSACTION_SECONDS = 60 * 60


def check_transaction_health(connection: Any) -> HealthCheckResult:
    """Check for transactions open long enough to create operational risk."""
    with connection.cursor() as cursor:
        cursor.execute(TRANSACTION_ACTIVITY_SQL)
        transaction_rows = cursor.fetchall()

    open_transactions = len(transaction_rows)
    parsed_rows = [_transaction_from_row(row) for row in transaction_rows]
    long_running_transactions = sum(
        1
        for row in parsed_rows
        if row["transaction_age_seconds"] >= LONG_RUNNING_TRANSACTION_SECONDS
    )
    oldest_transaction = parsed_rows[0] if parsed_rows else None
    oldest_transaction_seconds = (
        oldest_transaction["transaction_age_seconds"] if oldest_transaction else None
    )
    status = _status_for_oldest_transaction(oldest_transaction_seconds)
    summary = _summary_for(open_transactions, long_running_transactions, oldest_transaction)

    return HealthCheckResult(
        name="Transaction Health",
        status=status,
        summary=summary,
        metrics={
            "open_transactions": open_transactions,
            "long_running_transactions": long_running_transactions,
            "oldest_transaction_pid": (
                oldest_transaction["pid"] if oldest_transaction else None
            ),
            "oldest_transaction_seconds": oldest_transaction_seconds,
            "oldest_transaction_state": (
                oldest_transaction["state"] if oldest_transaction else None
            ),
            "oldest_transaction_user": (
                oldest_transaction["user"] if oldest_transaction else None
            ),
            "oldest_transaction_application": (
                oldest_transaction["application"] if oldest_transaction else None
            ),
            "oldest_transaction_wait_event_type": (
                oldest_transaction["wait_event_type"] if oldest_transaction else None
            ),
            "oldest_transaction_wait_event": (
                oldest_transaction["wait_event"] if oldest_transaction else None
            ),
            "oldest_transaction_query": (
                oldest_transaction["query"] if oldest_transaction else None
            ),
        },
        recommendation=_recommendation_for(status, oldest_transaction),
    )


def _transaction_from_row(row: Any) -> dict[str, object]:
    """Return a normalized transaction dictionary from a pg_stat_activity row."""
    return {
        "pid": int(row[0]),
        "user": row[1],
        "application": row[2],
        "state": row[3],
        "transaction_age_seconds": float(row[4]),
        "wait_event_type": row[5],
        "wait_event": row[6],
        "query": row[7],
    }


def _status_for_oldest_transaction(oldest_transaction_seconds: float | None) -> str:
    """Return health status for the oldest open transaction age."""
    if oldest_transaction_seconds is None:
        return "healthy"
    if oldest_transaction_seconds > CRITICAL_TRANSACTION_SECONDS:
        return "critical"
    if oldest_transaction_seconds >= LONG_RUNNING_TRANSACTION_SECONDS:
        return "warning"
    return "healthy"


def _summary_for(
    open_transactions: int,
    long_running_transactions: int,
    oldest_transaction: dict[str, object] | None,
) -> str:
    """Return a concise transaction health summary."""
    if oldest_transaction is None:
        return "No open transactions were found."

    summary = (
        f"{open_transactions} open transaction(s) found; "
        f"{long_running_transactions} are at least "
        f"{LONG_RUNNING_TRANSACTION_SECONDS} seconds old. "
        f"Oldest transaction is {oldest_transaction['transaction_age_seconds']:.0f} "
        f"seconds old."
    )
    if oldest_transaction["state"] == "idle in transaction":
        summary += " The oldest transaction is idle in transaction."
    return summary


def _recommendation_for(
    status: str,
    oldest_transaction: dict[str, object] | None,
) -> str:
    """Return an actionable transaction health recommendation."""
    if oldest_transaction is None:
        return "No long-running transaction risk detected."

    if status == "healthy":
        return (
            "Open transaction age is below the default review threshold. "
            "Continue monitoring normal application transaction lifecycle."
        )

    recommendation = (
        "Investigate the owning application or session before considering "
        "cancellation or termination. Long-running transactions can retain "
        "locks longer than expected, prevent VACUUM from reclaiming obsolete "
        "tuple versions, increase table bloat, keep old row versions visible, "
        "and indicate incorrect application transaction lifecycle behavior."
    )
    if oldest_transaction["state"] == "idle in transaction":
        return (
            "The oldest long-running transaction is idle in transaction. "
            f"{recommendation}"
        )
    return recommendation
