"""Index usage and review-signal health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


INDEX_ACTIVITY_SQL = """
SELECT
    s.schemaname,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    pg_relation_size(s.indexrelid) AS index_size_bytes,
    i.indisprimary AS is_primary,
    i.indisunique AS is_unique
FROM pg_stat_user_indexes s
JOIN pg_index i
    ON i.indexrelid = s.indexrelid
ORDER BY pg_relation_size(s.indexrelid) DESC;
"""

LARGE_INDEX_REVIEW_BYTES = 100 * 1024 * 1024


def check_index_health(connection: Any) -> HealthCheckResult:
    """Check index usage statistics for large zero-scan review candidates."""
    with connection.cursor() as cursor:
        cursor.execute(INDEX_ACTIVITY_SQL)
        index_rows = cursor.fetchall()

    indexes = [_index_from_row(row) for row in index_rows]
    review_candidates = [
        index for index in indexes if _is_large_zero_scan_review_candidate(index)
    ]
    protected_zero_scan_indexes = [
        index for index in indexes if _is_protected_zero_scan_index(index)
    ]
    largest_index = _largest_index(indexes)
    most_used_index = _most_used_index(indexes)
    largest_review_candidate = _largest_index(review_candidates)
    status = "warning" if review_candidates else "healthy"

    return HealthCheckResult(
        name="Index Health",
        status=status,
        summary=_summary_for(status, largest_review_candidate),
        metrics=_metrics_for(
            indexes,
            review_candidates,
            protected_zero_scan_indexes,
            largest_index,
            most_used_index,
            largest_review_candidate,
        ),
        recommendation=_recommendation_for(
            review_candidates,
            protected_zero_scan_indexes,
        ),
    )


def _index_from_row(row: Any) -> dict[str, object]:
    """Return a normalized index statistics dictionary."""
    return {
        "schema": row[0],
        "table": row[1],
        "index": row[2],
        "idx_scan": _int_or_zero(row[3]),
        "idx_tup_read": _int_or_zero(row[4]),
        "idx_tup_fetch": _int_or_zero(row[5]),
        "index_size_bytes": _int_or_zero(row[6]),
        "is_primary": bool(row[7]),
        "is_unique": bool(row[8]),
    }


def _int_or_zero(value: object) -> int:
    """Return an integer metric value, treating NULL as zero."""
    if value is None:
        return 0
    return int(value)


def _is_large_zero_scan_review_candidate(index: dict[str, object]) -> bool:
    """Return whether an index should be surfaced for review."""
    return (
        int(index["idx_scan"]) == 0
        and int(index["index_size_bytes"]) >= LARGE_INDEX_REVIEW_BYTES
        and not bool(index["is_primary"])
        and not bool(index["is_unique"])
    )


def _is_protected_zero_scan_index(index: dict[str, object]) -> bool:
    """Return whether a zero-scan index is protected by constraint semantics."""
    return int(index["idx_scan"]) == 0 and (
        bool(index["is_primary"]) or bool(index["is_unique"])
    )


def _largest_index(indexes: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the largest index by relation size."""
    if not indexes:
        return None
    return max(indexes, key=lambda index: int(index["index_size_bytes"]))


def _most_used_index(indexes: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the index with the highest scan count."""
    if not indexes:
        return None
    return max(indexes, key=lambda index: int(index["idx_scan"]))


def _metrics_for(
    indexes: list[dict[str, object]],
    review_candidates: list[dict[str, object]],
    protected_zero_scan_indexes: list[dict[str, object]],
    largest_index: dict[str, object] | None,
    most_used_index: dict[str, object] | None,
    largest_review_candidate: dict[str, object] | None,
) -> dict[str, object]:
    """Return index health metrics for the result model."""
    return {
        "indexes_checked": len(indexes),
        "indexes_used": sum(1 for index in indexes if int(index["idx_scan"]) > 0),
        "indexes_with_zero_scans": sum(
            1 for index in indexes if int(index["idx_scan"]) == 0
        ),
        "large_zero_scan_indexes": len(review_candidates),
        "protected_zero_scan_indexes": len(protected_zero_scan_indexes),
        "largest_index_name": largest_index["index"] if largest_index else None,
        "largest_index_table": largest_index["table"] if largest_index else None,
        "largest_index_size_bytes": (
            largest_index["index_size_bytes"] if largest_index else None
        ),
        "most_used_index_name": most_used_index["index"] if most_used_index else None,
        "most_used_index_table": most_used_index["table"] if most_used_index else None,
        "most_used_index_scans": most_used_index["idx_scan"] if most_used_index else None,
        "largest_review_candidate_name": (
            largest_review_candidate["index"] if largest_review_candidate else None
        ),
        "largest_review_candidate_table": (
            largest_review_candidate["table"] if largest_review_candidate else None
        ),
        "largest_review_candidate_size_bytes": (
            largest_review_candidate["index_size_bytes"]
            if largest_review_candidate
            else None
        ),
        "largest_review_candidate_idx_tup_read": (
            largest_review_candidate["idx_tup_read"]
            if largest_review_candidate
            else None
        ),
        "largest_review_candidate_idx_tup_fetch": (
            largest_review_candidate["idx_tup_fetch"]
            if largest_review_candidate
            else None
        ),
    }


def _summary_for(
    status: str,
    largest_review_candidate: dict[str, object] | None,
) -> str:
    """Return a concise index health summary."""
    if status == "healthy":
        return "No significant index-usage concerns detected."
    if largest_review_candidate is None:
        return "No large zero-scan review candidate details were found."

    return (
        f"{largest_review_candidate['schema']}."
        f"{largest_review_candidate['index']} is a large zero-scan index "
        "review candidate."
    )


def _recommendation_for(
    review_candidates: list[dict[str, object]],
    protected_zero_scan_indexes: list[dict[str, object]],
) -> str:
    """Return an actionable index review recommendation."""
    if review_candidates:
        return (
            "This large index has not been scanned since PostgreSQL statistics "
            "were last reset. Large unused indexes consume storage and add "
            "write-maintenance cost. Review application query patterns, "
            "scheduled or reporting jobs, execution plans, overlapping indexes, "
            "recent statistics resets, and whether the index backs a constraint "
            "before considering removal."
        )

    if protected_zero_scan_indexes:
        return (
            "No large non-protected zero-scan index concerns detected. Some "
            "zero-scan indexes are primary key or unique indexes, which may be "
            "required for data correctness rather than query performance."
        )

    return "No significant index-usage concerns detected."
