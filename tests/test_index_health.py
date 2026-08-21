"""Unit tests for PostgreSQL index health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

index_health_module = importlib.import_module("checks.index_health")
check_index_health = index_health_module.check_index_health

ONE_MB = 1024 * 1024


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class IndexHealthTests(unittest.TestCase):
    """Tests for index usage and review-signal health checks."""

    def test_no_indexes(self) -> None:
        result = check_index_health(_mock_connection([]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["indexes_checked"], 0)
        self.assertEqual(result.metrics["indexes_used"], 0)
        self.assertIsNone(result.metrics["largest_review_candidate_name"])
        self.assertEqual(
            result.recommendation,
            "No significant index-usage concerns detected.",
        )

    def test_healthy_used_index(self) -> None:
        result = check_index_health(_mock_connection([_row(idx_scan=10)]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["indexes_checked"], 1)
        self.assertEqual(result.metrics["indexes_used"], 1)
        self.assertEqual(result.metrics["indexes_with_zero_scans"], 0)

    def test_zero_scan_small_index_stays_healthy(self) -> None:
        result = check_index_health(
            _mock_connection([_row(idx_scan=0, size_bytes=99 * ONE_MB)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["indexes_with_zero_scans"], 1)
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 0)

    def test_zero_scan_large_index_becomes_warning(self) -> None:
        result = check_index_health(
            _mock_connection([_row(idx_scan=0, size_bytes=101 * ONE_MB)])
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 1)
        self.assertEqual(result.metrics["largest_review_candidate_name"], "orders_idx")
        self.assertIn("not been scanned", result.recommendation)
        self.assertIn("write-maintenance cost", result.recommendation)

    def test_zero_scan_large_primary_key_is_protected(self) -> None:
        result = check_index_health(
            _mock_connection(
                [_row(idx_scan=0, size_bytes=200 * ONE_MB, is_primary=True)]
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 0)
        self.assertEqual(result.metrics["protected_zero_scan_indexes"], 1)
        self.assertIn("data correctness", result.recommendation)

    def test_zero_scan_large_unique_index_is_protected(self) -> None:
        result = check_index_health(
            _mock_connection(
                [_row(idx_scan=0, size_bytes=200 * ONE_MB, is_unique=True)]
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 0)
        self.assertEqual(result.metrics["protected_zero_scan_indexes"], 1)
        self.assertIn("unique indexes", result.recommendation)

    def test_multiple_review_candidates_select_largest(self) -> None:
        result = check_index_health(
            _mock_connection(
                [
                    _row(index="orders_created_at_idx", size_bytes=200 * ONE_MB),
                    _row(index="orders_status_idx", size_bytes=500 * ONE_MB),
                ]
            )
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 2)
        self.assertEqual(
            result.metrics["largest_review_candidate_name"],
            "orders_status_idx",
        )
        self.assertEqual(
            result.metrics["largest_review_candidate_size_bytes"],
            500 * ONE_MB,
        )

    def test_most_used_index_is_selected_correctly(self) -> None:
        result = check_index_health(
            _mock_connection(
                [
                    _row(index="orders_customer_idx", idx_scan=25),
                    _row(index="orders_status_idx", idx_scan=100),
                ]
            )
        )

        self.assertEqual(result.metrics["most_used_index_name"], "orders_status_idx")
        self.assertEqual(result.metrics["most_used_index_scans"], 100)

    def test_largest_index_is_selected_correctly(self) -> None:
        result = check_index_health(
            _mock_connection(
                [
                    _row(index="orders_customer_idx", size_bytes=50 * ONE_MB),
                    _row(index="orders_payload_idx", size_bytes=800 * ONE_MB),
                ]
            )
        )

        self.assertEqual(result.metrics["largest_index_name"], "orders_payload_idx")
        self.assertEqual(result.metrics["largest_index_size_bytes"], 800 * ONE_MB)

    def test_exactly_one_hundred_mb_zero_scan_index_is_review_candidate(self) -> None:
        result = check_index_health(
            _mock_connection([_row(idx_scan=0, size_bytes=100 * ONE_MB)])
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 1)

    def test_below_one_hundred_mb_zero_scan_index_is_not_review_candidate(self) -> None:
        result = check_index_health(
            _mock_connection([_row(idx_scan=0, size_bytes=(100 * ONE_MB) - 1)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["large_zero_scan_indexes"], 0)

    def test_query_is_read_only(self) -> None:
        connection = _mock_connection([])

        check_index_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("FROM pg_stat_user_indexes", executed_sql)
        self.assertIn("JOIN pg_index", executed_sql)
        self.assertNotIn("DROP INDEX", executed_sql.upper())
        self.assertNotIn("CREATE INDEX", executed_sql.upper())
        self.assertNotIn("REINDEX", executed_sql.upper())

    def test_no_drop_index_appears_in_recommendations(self) -> None:
        warning_result = check_index_health(
            _mock_connection([_row(idx_scan=0, size_bytes=200 * ONE_MB)])
        )
        protected_result = check_index_health(
            _mock_connection(
                [_row(idx_scan=0, size_bytes=200 * ONE_MB, is_primary=True)]
            )
        )

        self.assertNotIn("DROP INDEX", warning_result.recommendation.upper())
        self.assertNotIn("DROP INDEX", protected_result.recommendation.upper())

    def test_null_safe_handling(self) -> None:
        result = check_index_health(
            _mock_connection(
                [
                    (
                        "public",
                        "orders",
                        "orders_idx",
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ]
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["indexes_checked"], 1)
        self.assertEqual(result.metrics["indexes_with_zero_scans"], 1)
        self.assertEqual(result.metrics["largest_index_size_bytes"], 0)


def _mock_connection(rows: list[tuple[object, ...]]) -> Mock:
    cursor = Mock()
    cursor.fetchall.return_value = rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    schema: str = "public",
    table: str = "orders",
    index: str = "orders_idx",
    idx_scan: int | None = 0,
    idx_tup_read: int | None = 10,
    idx_tup_fetch: int | None = 5,
    size_bytes: int | None = 10 * ONE_MB,
    is_primary: bool | None = False,
    is_unique: bool | None = False,
) -> tuple[object, ...]:
    return (
        schema,
        table,
        index,
        idx_scan,
        idx_tup_read,
        idx_tup_fetch,
        size_bytes,
        is_primary,
        is_unique,
    )


if __name__ == "__main__":
    unittest.main()
