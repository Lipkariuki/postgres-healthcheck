"""Database-level activity health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


DATABASE_ACTIVITY_SQL = """
SELECT
    datname,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit,
    tup_returned,
    tup_fetched,
    tup_inserted,
    tup_updated,
    tup_deleted,
    temp_files,
    temp_bytes,
    deadlocks
FROM pg_stat_database
WHERE datname = current_database();
"""

CACHE_HIT_HEALTHY_PERCENT = 99.0
CACHE_HIT_CRITICAL_PERCENT = 95.0
ROLLBACK_WARNING_PERCENT = 5.0
ROLLBACK_CRITICAL_PERCENT = 20.0


def check_database_health(connection: Any) -> HealthCheckResult:
    """Check cumulative pg_stat_database metrics for the current database."""
    with connection.cursor() as cursor:
        cursor.execute(DATABASE_ACTIVITY_SQL)
        database_row = cursor.fetchone()

    if database_row is None:
        raise RuntimeError("Unable to read current database statistics")

    metrics = _metrics_from_row(database_row)
    status = _status_for(metrics)

    return HealthCheckResult(
        name="Database Health",
        status=status,
        summary=_summary_for(status, metrics),
        metrics=metrics,
        recommendation=_recommendation_for(status, metrics),
    )


def _metrics_from_row(row: Any) -> dict[str, object]:
    """Return normalized database health metrics from pg_stat_database."""
    transactions_committed = _int_or_zero(row[1])
    transactions_rolled_back = _int_or_zero(row[2])
    blocks_read = _int_or_zero(row[3])
    blocks_hit = _int_or_zero(row[4])

    return {
        "database_name": row[0],
        "transactions_committed": transactions_committed,
        "transactions_rolled_back": transactions_rolled_back,
        "rollback_ratio_percent": _ratio_percent(
            transactions_rolled_back,
            transactions_committed + transactions_rolled_back,
        ),
        "blocks_read": blocks_read,
        "blocks_hit": blocks_hit,
        "cache_hit_ratio_percent": _ratio_percent(
            blocks_hit,
            blocks_hit + blocks_read,
        ),
        "tuples_returned": _int_or_zero(row[5]),
        "tuples_fetched": _int_or_zero(row[6]),
        "tuples_inserted": _int_or_zero(row[7]),
        "tuples_updated": _int_or_zero(row[8]),
        "tuples_deleted": _int_or_zero(row[9]),
        "temp_files": _int_or_zero(row[10]),
        "temp_bytes": _int_or_zero(row[11]),
        "deadlocks": _int_or_zero(row[12]),
    }


def _int_or_zero(value: object) -> int:
    """Return an integer metric value, treating NULL as zero."""
    if value is None:
        return 0
    return int(value)


def _ratio_percent(numerator: int, denominator: int) -> float | None:
    """Return a percentage ratio, or None when the ratio is undefined."""
    if denominator == 0:
        return None
    return (numerator / denominator) * 100


def _status_for(metrics: dict[str, object]) -> str:
    """Return the strongest database health status from diagnostic metrics."""
    cache_hit_ratio = metrics["cache_hit_ratio_percent"]
    rollback_ratio = metrics["rollback_ratio_percent"]

    if (
        cache_hit_ratio is not None
        and float(cache_hit_ratio) < CACHE_HIT_CRITICAL_PERCENT
    ):
        return "critical"
    if (
        rollback_ratio is not None
        and float(rollback_ratio) >= ROLLBACK_CRITICAL_PERCENT
    ):
        return "critical"

    if (
        cache_hit_ratio is not None
        and float(cache_hit_ratio) < CACHE_HIT_HEALTHY_PERCENT
    ):
        return "warning"
    if (
        rollback_ratio is not None
        and float(rollback_ratio) >= ROLLBACK_WARNING_PERCENT
    ):
        return "warning"
    if int(metrics["temp_files"]) > 0 or int(metrics["deadlocks"]) > 0:
        return "warning"

    return "healthy"


def _summary_for(status: str, metrics: dict[str, object]) -> str:
    """Return a concise database health summary."""
    if status == "healthy":
        return "Database-level statistics show no immediate health concerns."

    signals = []
    cache_hit_ratio = metrics["cache_hit_ratio_percent"]
    rollback_ratio = metrics["rollback_ratio_percent"]
    if (
        cache_hit_ratio is not None
        and float(cache_hit_ratio) < CACHE_HIT_HEALTHY_PERCENT
    ):
        signals.append(f"cache hit ratio is {float(cache_hit_ratio):.2f}%")
    if (
        rollback_ratio is not None
        and float(rollback_ratio) >= ROLLBACK_WARNING_PERCENT
    ):
        signals.append(f"rollback ratio is {float(rollback_ratio):.2f}%")
    if int(metrics["temp_files"]) > 0:
        signals.append(f"{metrics['temp_files']} temporary file(s) were recorded")
    if int(metrics["deadlocks"]) > 0:
        signals.append(f"{metrics['deadlocks']} deadlock(s) were recorded")

    return "Database-level statistics have investigation signals: " + "; ".join(
        signals
    )


def _recommendation_for(status: str, metrics: dict[str, object]) -> str:
    """Return an actionable database statistics recommendation."""
    if status == "healthy":
        return "Database-level statistics show no immediate health concerns."

    recommendations = [
        "pg_stat_database counters are cumulative since statistics were last reset, "
        "so correlate these signals with recent workload timing before drawing "
        "real-time conclusions."
    ]
    cache_hit_ratio = metrics["cache_hit_ratio_percent"]
    rollback_ratio = metrics["rollback_ratio_percent"]

    if (
        cache_hit_ratio is not None
        and float(cache_hit_ratio) < CACHE_HIT_HEALTHY_PERCENT
    ):
        recommendations.append(
            "A low cache hit ratio means more block requests are being served "
            "from storage instead of PostgreSQL buffers. Investigate workload "
            "behavior, query plans, table and index access patterns, memory "
            "configuration, and actual I/O behavior."
        )
    if (
        rollback_ratio is not None
        and float(rollback_ratio) >= ROLLBACK_WARNING_PERCENT
    ):
        recommendations.append(
            "An elevated rollback ratio can point to application errors, retries, "
            "or transaction lifecycle issues. Review application logs and "
            "transaction handling before treating rollbacks as a database fault."
        )
    if int(metrics["temp_files"]) > 0:
        recommendations.append(
            "Temporary files can be created when sorts, hashes, or similar "
            "operations exceed available working memory. Investigate the queries "
            "producing temporary files, execution plans, workload characteristics, "
            "and memory settings before changing configuration."
        )
    if int(metrics["deadlocks"]) > 0:
        recommendations.append(
            "Deadlocks recorded here are historical cumulative events, not proof "
            "that a deadlock is happening now. Investigate application lock order, "
            "transaction scope, and recent error logs."
        )

    return " ".join(recommendations)
