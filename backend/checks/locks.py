"""Blocking session and lock contention health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


BLOCKING_ACTIVITY_SQL = """
SELECT
    blocked.pid AS blocked_pid,
    blocked.usename AS blocked_user,
    blocked.application_name AS blocked_application,
    blocked.state AS blocked_state,
    blocked.wait_event_type AS blocked_wait_event_type,
    blocked.wait_event AS blocked_wait_event,
    EXTRACT(EPOCH FROM (now() - blocked.query_start)) AS blocked_seconds,
    LEFT(blocked.query, 150) AS blocked_query,
    blocker.pid AS blocker_pid,
    blocker.usename AS blocker_user,
    blocker.application_name AS blocker_application,
    blocker.state AS blocker_state,
    EXTRACT(EPOCH FROM (now() - blocker.xact_start)) AS blocker_transaction_seconds,
    LEFT(blocker.query, 150) AS blocker_query
FROM pg_stat_activity blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocking_pid(pid)
    ON true
JOIN pg_stat_activity blocker
    ON blocker.pid = blocking_pid.pid
WHERE blocked.pid <> pg_backend_pid()
ORDER BY blocked.query_start;
"""

CRITICAL_BLOCKED_SECONDS = 30
LONG_BLOCKER_TRANSACTION_SECONDS = 30 * 60


def check_lock_health(connection: Any) -> HealthCheckResult:
    """Check for sessions currently blocked by another PostgreSQL backend."""
    with connection.cursor() as cursor:
        cursor.execute(BLOCKING_ACTIVITY_SQL)
        blocking_rows = cursor.fetchall()

    blocked_sessions = len(blocking_rows)
    parsed_rows = [_blocking_pair_from_row(row) for row in blocking_rows]
    blocking_sessions = len({row["blocker_pid"] for row in parsed_rows})
    oldest_blocked = parsed_rows[0] if parsed_rows else None
    status = _status_for_blocking(parsed_rows)

    return HealthCheckResult(
        name="Lock Health",
        status=status,
        summary=_summary_for(blocked_sessions, blocking_sessions, oldest_blocked),
        metrics={
            "blocked_sessions": blocked_sessions,
            "blocking_sessions": blocking_sessions,
            "oldest_blocked_pid": (
                oldest_blocked["blocked_pid"] if oldest_blocked else None
            ),
            "oldest_blocked_seconds": (
                oldest_blocked["blocked_seconds"] if oldest_blocked else None
            ),
            "root_blocker_pid": (
                oldest_blocked["blocker_pid"] if oldest_blocked else None
            ),
            "root_blocker_user": (
                oldest_blocked["blocker_user"] if oldest_blocked else None
            ),
            "root_blocker_application": (
                oldest_blocked["blocker_application"] if oldest_blocked else None
            ),
            "root_blocker_state": (
                oldest_blocked["blocker_state"] if oldest_blocked else None
            ),
            "root_blocker_transaction_seconds": (
                oldest_blocked["blocker_transaction_seconds"]
                if oldest_blocked
                else None
            ),
            "blocked_wait_event_type": (
                oldest_blocked["blocked_wait_event_type"] if oldest_blocked else None
            ),
            "blocked_wait_event": (
                oldest_blocked["blocked_wait_event"] if oldest_blocked else None
            ),
            "oldest_blocked_query": (
                oldest_blocked["blocked_query"] if oldest_blocked else None
            ),
            "root_blocker_query": (
                oldest_blocked["blocker_query"] if oldest_blocked else None
            ),
        },
        recommendation=_recommendation_for(oldest_blocked),
    )


def _blocking_pair_from_row(row: Any) -> dict[str, object]:
    """Return a normalized blocking pair dictionary from pg_stat_activity."""
    return {
        "blocked_pid": int(row[0]),
        "blocked_user": row[1],
        "blocked_application": row[2],
        "blocked_state": row[3],
        "blocked_wait_event_type": row[4],
        "blocked_wait_event": row[5],
        "blocked_seconds": float(row[6]),
        "blocked_query": row[7],
        "blocker_pid": int(row[8]),
        "blocker_user": row[9],
        "blocker_application": row[10],
        "blocker_state": row[11],
        "blocker_transaction_seconds": (
            float(row[12]) if row[12] is not None else None
        ),
        "blocker_query": row[13],
    }


def _status_for_blocking(blocking_pairs: list[dict[str, object]]) -> str:
    """Return health status for current lock blocking."""
    if not blocking_pairs:
        return "healthy"
    if any(
        float(row["blocked_seconds"]) > CRITICAL_BLOCKED_SECONDS
        for row in blocking_pairs
    ):
        return "critical"
    return "warning"


def _summary_for(
    blocked_sessions: int,
    blocking_sessions: int,
    oldest_blocked: dict[str, object] | None,
) -> str:
    """Return a concise lock health summary."""
    if oldest_blocked is None:
        return "No blocked sessions were found."

    return (
        f"{blocked_sessions} blocked session(s) found from "
        f"{blocking_sessions} blocking session(s). Oldest blocked session has "
        f"waited {oldest_blocked['blocked_seconds']:.0f} seconds."
    )


def _recommendation_for(oldest_blocked: dict[str, object] | None) -> str:
    """Return an actionable lock contention recommendation."""
    if oldest_blocked is None:
        return "No lock contention detected."

    recommendation = (
        "Another backend currently holds a conflicting lock, so the blocked "
        "query cannot continue until that condition changes. Investigate the "
        "blocking transaction and application before considering cancellation "
        "or termination. Long-running transactions are common causes."
    )
    blocker_age = oldest_blocked["blocker_transaction_seconds"]
    if (
        blocker_age is not None
        and float(blocker_age) >= LONG_BLOCKER_TRANSACTION_SECONDS
    ):
        recommendation += (
            f" The blocker transaction has been open for {float(blocker_age):.0f} "
            "seconds."
        )
    return recommendation
