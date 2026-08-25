"""Query latency and cumulative execution health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


PG_STAT_STATEMENTS_EXTENSION_SQL = """
SELECT 1
FROM pg_extension
WHERE extname = 'pg_stat_statements';
"""

QUERY_ACTIVITY_SQL = """
SELECT
    LEFT(query, 300) AS query,
    calls,
    total_exec_time,
    mean_exec_time,
    max_exec_time,
    rows
FROM pg_stat_statements
WHERE query NOT ILIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC;
"""

QUERY_TEXT_LIMIT = 150
MEAN_EXEC_WARNING_MS = 100.0
MEAN_EXEC_CRITICAL_MS = 500.0


def check_query_health(connection: Any) -> HealthCheckResult:
    """Check pg_stat_statements for query latency and cumulative cost signals."""
    with connection.cursor() as cursor:
        cursor.execute(PG_STAT_STATEMENTS_EXTENSION_SQL)
        extension_row = cursor.fetchone()

        if extension_row is None:
            return _unavailable_result()

        cursor.execute(QUERY_ACTIVITY_SQL)
        query_rows = cursor.fetchall()

    queries = [_query_from_row(row) for row in query_rows]
    warning_latency_queries = sum(
        1 for query in queries if _has_warning_latency(query)
    )
    critical_latency_queries = sum(
        1 for query in queries if _has_critical_latency(query)
    )
    top_total_query = _top_total_query(queries)
    slowest_mean_query = _slowest_mean_query(queries)
    highest_max_query = _highest_max_query(queries)
    status = _status_for(warning_latency_queries, critical_latency_queries)

    return HealthCheckResult(
        name="Query Health",
        status=status,
        summary=_summary_for(status, slowest_mean_query),
        metrics=_metrics_for(
            queries,
            warning_latency_queries,
            critical_latency_queries,
            top_total_query,
            slowest_mean_query,
            highest_max_query,
        ),
        recommendation=_recommendation_for(status, slowest_mean_query),
    )


def _unavailable_result() -> HealthCheckResult:
    """Return a non-crashing result when pg_stat_statements is unavailable."""
    return HealthCheckResult(
        name="Query Health",
        status="warning",
        summary=(
            "Query Health cannot be evaluated because pg_stat_statements is "
            "unavailable."
        ),
        metrics={
            "pg_stat_statements_available": False,
            "queries_checked": 0,
            "total_calls": 0,
            "warning_latency_queries": 0,
            "critical_latency_queries": 0,
            "top_total_query": None,
            "top_total_calls": None,
            "top_total_exec_time_ms": None,
            "top_total_mean_exec_time_ms": None,
            "top_total_max_exec_time_ms": None,
            "slowest_mean_query": None,
            "slowest_mean_calls": None,
            "slowest_mean_exec_time_ms": None,
            "slowest_mean_total_exec_time_ms": None,
            "slowest_mean_max_exec_time_ms": None,
            "highest_max_query": None,
            "highest_max_calls": None,
            "highest_max_exec_time_ms": None,
        },
        recommendation=(
            "Enable pg_stat_statements in the current database before "
            "historical query statistics can be inspected. This check does not "
            "install or configure extensions automatically."
        ),
    )


def _query_from_row(row: Any) -> dict[str, object]:
    """Return a normalized pg_stat_statements query dictionary."""
    return {
        "query": _truncate_query(row[0]),
        "calls": _int_or_zero(row[1]),
        "total_exec_time_ms": _float_or_zero(row[2]),
        "mean_exec_time_ms": _float_or_zero(row[3]),
        "max_exec_time_ms": _float_or_zero(row[4]),
        "rows": _int_or_zero(row[5]),
    }


def _truncate_query(query: object) -> str | None:
    """Return safely truncated query text, tolerating unavailable text."""
    if query is None:
        return None
    query_text = str(query).strip()
    if len(query_text) <= QUERY_TEXT_LIMIT:
        return query_text
    return query_text[: QUERY_TEXT_LIMIT - 3] + "..."


def _int_or_zero(value: object) -> int:
    """Return an integer metric value, treating NULL as zero."""
    if value is None:
        return 0
    return int(value)


def _float_or_zero(value: object) -> float:
    """Return a float metric value, treating NULL as zero."""
    if value is None:
        return 0.0
    return float(value)


def _has_warning_latency(query: dict[str, object]) -> bool:
    """Return whether the query has a warning-level average latency signal."""
    mean_exec_time = float(query["mean_exec_time_ms"])
    return MEAN_EXEC_WARNING_MS <= mean_exec_time < MEAN_EXEC_CRITICAL_MS


def _has_critical_latency(query: dict[str, object]) -> bool:
    """Return whether the query has a critical-level average latency signal."""
    return float(query["mean_exec_time_ms"]) >= MEAN_EXEC_CRITICAL_MS


def _top_total_query(queries: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the query with the highest cumulative execution time."""
    if not queries:
        return None
    return max(queries, key=lambda query: float(query["total_exec_time_ms"]))


def _slowest_mean_query(queries: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the query with the highest mean execution time."""
    if not queries:
        return None
    return max(queries, key=lambda query: float(query["mean_exec_time_ms"]))


def _highest_max_query(queries: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the query with the highest recorded max execution time."""
    if not queries:
        return None
    return max(queries, key=lambda query: float(query["max_exec_time_ms"]))


def _status_for(warning_latency_queries: int, critical_latency_queries: int) -> str:
    """Return health status from average latency signals."""
    if critical_latency_queries > 0:
        return "critical"
    if warning_latency_queries > 0:
        return "warning"
    return "healthy"


def _metrics_for(
    queries: list[dict[str, object]],
    warning_latency_queries: int,
    critical_latency_queries: int,
    top_total_query: dict[str, object] | None,
    slowest_mean_query: dict[str, object] | None,
    highest_max_query: dict[str, object] | None,
) -> dict[str, object]:
    """Return query health metrics for the result model."""
    return {
        "pg_stat_statements_available": True,
        "queries_checked": len(queries),
        "total_calls": sum(int(query["calls"]) for query in queries),
        "warning_latency_queries": warning_latency_queries,
        "critical_latency_queries": critical_latency_queries,
        "top_total_query": top_total_query["query"] if top_total_query else None,
        "top_total_calls": top_total_query["calls"] if top_total_query else None,
        "top_total_exec_time_ms": (
            top_total_query["total_exec_time_ms"] if top_total_query else None
        ),
        "top_total_mean_exec_time_ms": (
            top_total_query["mean_exec_time_ms"] if top_total_query else None
        ),
        "top_total_max_exec_time_ms": (
            top_total_query["max_exec_time_ms"] if top_total_query else None
        ),
        "slowest_mean_query": (
            slowest_mean_query["query"] if slowest_mean_query else None
        ),
        "slowest_mean_calls": (
            slowest_mean_query["calls"] if slowest_mean_query else None
        ),
        "slowest_mean_exec_time_ms": (
            slowest_mean_query["mean_exec_time_ms"] if slowest_mean_query else None
        ),
        "slowest_mean_total_exec_time_ms": (
            slowest_mean_query["total_exec_time_ms"]
            if slowest_mean_query
            else None
        ),
        "slowest_mean_max_exec_time_ms": (
            slowest_mean_query["max_exec_time_ms"] if slowest_mean_query else None
        ),
        "highest_max_query": (
            highest_max_query["query"] if highest_max_query else None
        ),
        "highest_max_calls": (
            highest_max_query["calls"] if highest_max_query else None
        ),
        "highest_max_exec_time_ms": (
            highest_max_query["max_exec_time_ms"] if highest_max_query else None
        ),
    }


def _summary_for(
    status: str,
    slowest_mean_query: dict[str, object] | None,
) -> str:
    """Return a concise query health summary."""
    if status == "healthy":
        return "No significant query-latency concerns detected."
    if slowest_mean_query is None:
        return "No query latency details were found."

    return (
        "Slowest average query has recorded executions averaging "
        f"{float(slowest_mean_query['mean_exec_time_ms']):.2f} ms."
    )


def _recommendation_for(
    status: str,
    slowest_mean_query: dict[str, object] | None,
) -> str:
    """Return an actionable query health recommendation."""
    if status == "healthy":
        return "No significant query-latency concerns detected."

    query_text = slowest_mean_query["query"] if slowest_mean_query else None
    calls = slowest_mean_query["calls"] if slowest_mean_query else 0
    total_time = (
        slowest_mean_query["total_exec_time_ms"] if slowest_mean_query else 0.0
    )

    return (
        f"This query pattern has elevated average execution time: {query_text!r}. "
        f"It executed {calls} time(s) with {float(total_time):.2f} ms of "
        "cumulative execution time. pg_stat_statements statistics are "
        "accumulated observations since statistics were last reset; this does "
        "not mean the query is currently running. Query context and workload "
        "frequency matter. Investigate execution plans where safe, indexes, "
        "row estimates, table statistics, query predicates, joins, and "
        "sort or aggregation behavior before making changes."
    )
