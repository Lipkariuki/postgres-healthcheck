"""Table maintenance and autovacuum health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


TABLE_ACTIVITY_SQL = """
SELECT
    schemaname,
    relname,
    n_live_tup,
    n_dead_tup,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_tup_hot_upd,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
"""

DEAD_TUPLE_WARNING_PERCENT = 10.0
DEAD_TUPLE_CRITICAL_PERCENT = 20.0
MIN_TUPLES_FOR_RATIO_SEVERITY = 1000


def check_table_health(connection: Any) -> HealthCheckResult:
    """Check user tables for dead tuple and maintenance health signals."""
    with connection.cursor() as cursor:
        cursor.execute(TABLE_ACTIVITY_SQL)
        table_rows = cursor.fetchall()

    parsed_tables = [_table_from_row(row) for row in table_rows]
    warning_tables = sum(
        1
        for table in parsed_tables
        if _is_warning_table(table) and not _is_critical_table(table)
    )
    critical_tables = sum(1 for table in parsed_tables if _is_critical_table(table))
    most_concerning_table = _most_concerning_table(parsed_tables)
    status = _status_for(warning_tables, critical_tables)

    return HealthCheckResult(
        name="Table Health",
        status=status,
        summary=_summary_for(status, most_concerning_table),
        metrics=_metrics_for(
            parsed_tables,
            warning_tables,
            critical_tables,
            most_concerning_table,
        ),
        recommendation=_recommendation_for(status, most_concerning_table),
    )


def _table_from_row(row: Any) -> dict[str, object]:
    """Return a normalized table statistics dictionary."""
    live_tuples = _int_or_zero(row[2])
    dead_tuples = _int_or_zero(row[3])

    return {
        "schema": row[0],
        "table": row[1],
        "live_tuples": live_tuples,
        "dead_tuples": dead_tuples,
        "total_estimated_tuples": live_tuples + dead_tuples,
        "dead_tuple_ratio_percent": _dead_tuple_ratio_percent(
            live_tuples,
            dead_tuples,
        ),
        "inserts": _int_or_zero(row[4]),
        "updates": _int_or_zero(row[5]),
        "deletes": _int_or_zero(row[6]),
        "hot_updates": _int_or_zero(row[7]),
        "last_vacuum": row[8],
        "last_autovacuum": row[9],
        "last_analyze": row[10],
        "last_autoanalyze": row[11],
    }


def _int_or_zero(value: object) -> int:
    """Return an integer metric value, treating NULL as zero."""
    if value is None:
        return 0
    return int(value)


def _dead_tuple_ratio_percent(live_tuples: int, dead_tuples: int) -> float | None:
    """Return dead tuples as a percentage of total estimated tuples."""
    total_tuples = live_tuples + dead_tuples
    if total_tuples == 0:
        return None
    return (dead_tuples / total_tuples) * 100


def _is_warning_table(table: dict[str, object]) -> bool:
    """Return whether a table crosses the warning threshold."""
    ratio = table["dead_tuple_ratio_percent"]
    return (
        _has_meaningful_tuple_population(table)
        and ratio is not None
        and float(ratio) >= DEAD_TUPLE_WARNING_PERCENT
    )


def _is_critical_table(table: dict[str, object]) -> bool:
    """Return whether a table crosses the critical threshold."""
    ratio = table["dead_tuple_ratio_percent"]
    return (
        _has_meaningful_tuple_population(table)
        and ratio is not None
        and float(ratio) >= DEAD_TUPLE_CRITICAL_PERCENT
    )


def _has_meaningful_tuple_population(table: dict[str, object]) -> bool:
    """Return whether ratio severity should apply to the table."""
    # V1 significance heuristic: avoid alarming on tiny tables where a few
    # dead tuples can produce a large ratio without operational impact.
    return int(table["total_estimated_tuples"]) >= MIN_TUPLES_FOR_RATIO_SEVERITY


def _most_concerning_table(
    tables: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the table with the highest dead tuple ratio, if meaningful."""
    tables_with_ratios = [
        table
        for table in tables
        if table["dead_tuple_ratio_percent"] is not None
        and _has_meaningful_tuple_population(table)
        and float(table["dead_tuple_ratio_percent"]) >= DEAD_TUPLE_WARNING_PERCENT
    ]
    if not tables_with_ratios:
        return None
    return max(
        tables_with_ratios,
        key=lambda table: float(table["dead_tuple_ratio_percent"]),
    )


def _status_for(warning_tables: int, critical_tables: int) -> str:
    """Return the strongest table maintenance health status."""
    if critical_tables > 0:
        return "critical"
    if warning_tables > 0:
        return "warning"
    return "healthy"


def _metrics_for(
    tables: list[dict[str, object]],
    warning_tables: int,
    critical_tables: int,
    most_concerning_table: dict[str, object] | None,
) -> dict[str, object]:
    """Return table health metrics for the result model."""
    return {
        "tables_checked": len(tables),
        "tables_with_dead_tuples": sum(
            1 for table in tables if int(table["dead_tuples"]) > 0
        ),
        "warning_tables": warning_tables,
        "critical_tables": critical_tables,
        "highest_dead_tuple_ratio_percent": (
            most_concerning_table["dead_tuple_ratio_percent"]
            if most_concerning_table
            else None
        ),
        "most_concerning_schema": (
            most_concerning_table["schema"] if most_concerning_table else None
        ),
        "most_concerning_table": (
            most_concerning_table["table"] if most_concerning_table else None
        ),
        "most_concerning_live_tuples": (
            most_concerning_table["live_tuples"] if most_concerning_table else None
        ),
        "most_concerning_dead_tuples": (
            most_concerning_table["dead_tuples"] if most_concerning_table else None
        ),
        "most_concerning_total_estimated_tuples": (
            most_concerning_table["total_estimated_tuples"]
            if most_concerning_table
            else None
        ),
        "most_concerning_last_autovacuum": (
            most_concerning_table["last_autovacuum"]
            if most_concerning_table
            else None
        ),
        "most_concerning_last_autoanalyze": (
            most_concerning_table["last_autoanalyze"]
            if most_concerning_table
            else None
        ),
        "most_concerning_updates": (
            most_concerning_table["updates"] if most_concerning_table else None
        ),
        "most_concerning_hot_updates": (
            most_concerning_table["hot_updates"] if most_concerning_table else None
        ),
        "most_concerning_inserts": (
            most_concerning_table["inserts"] if most_concerning_table else None
        ),
        "most_concerning_deletes": (
            most_concerning_table["deletes"] if most_concerning_table else None
        ),
    }


def _summary_for(
    status: str,
    most_concerning_table: dict[str, object] | None,
) -> str:
    """Return a concise table health summary."""
    if status == "healthy":
        return "No table-maintenance risk detected."
    if most_concerning_table is None:
        return "No concerning table details were found."

    return (
        f"{most_concerning_table['schema']}.{most_concerning_table['table']} "
        "has the highest dead tuple ratio at "
        f"{most_concerning_table['dead_tuple_ratio_percent']:.2f}%."
    )


def _recommendation_for(
    status: str,
    most_concerning_table: dict[str, object] | None,
) -> str:
    """Return an actionable table maintenance recommendation."""
    if status == "healthy":
        return "No table-maintenance risk detected."

    table_reference = "The table"
    if most_concerning_table is not None:
        table_reference = (
            f"{most_concerning_table['schema']}."
            f"{most_concerning_table['table']}"
        )

    return (
        f"{table_reference} has an elevated dead tuple ratio. High dead tuple "
        "ratios can make more table pages need to be scanned, grow table and "
        "index storage, give VACUUM more work to perform, and leave stale "
        "statistics that affect planner estimates. Investigate whether "
        "autovacuum is running frequently enough, long-running transactions "
        "that may prevent cleanup, write and update volume, autovacuum table "
        "settings, table size, and workload pattern before changing maintenance "
        "settings."
    )
