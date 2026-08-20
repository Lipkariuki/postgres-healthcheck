"""Unit tests for PostgreSQL database health statistics checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

database_health_module = importlib.import_module("checks.database_health")
check_database_health = database_health_module.check_database_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class DatabaseHealthTests(unittest.TestCase):
    """Tests for cumulative database activity health statistics."""

    def test_healthy_database_statistics(self) -> None:
        result = check_database_health(
            _mock_connection(_row(committed=9999, rolled_back=1, blocks_read=5, blocks_hit=9995))
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["database_name"], "healthcheck_db")
        self.assertEqual(result.metrics["transactions_committed"], 9999)
        self.assertEqual(result.metrics["transactions_rolled_back"], 1)
        self.assertEqual(result.metrics["rollback_ratio_percent"], 0.01)
        self.assertEqual(result.metrics["cache_hit_ratio_percent"], 99.95)
        self.assertEqual(
            result.recommendation,
            "Database-level statistics show no immediate health concerns.",
        )

    def test_cache_hit_ratio_at_ninety_nine_percent_is_healthy(self) -> None:
        result = check_database_health(
            _mock_connection(_row(blocks_read=1, blocks_hit=99))
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["cache_hit_ratio_percent"], 99.0)

    def test_cache_hit_ratio_between_ninety_five_and_ninety_nine_is_warning(self) -> None:
        result = check_database_health(
            _mock_connection(_row(blocks_read=2, blocks_hit=98))
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("query plans", result.recommendation)
        self.assertIn("actual I/O behavior", result.recommendation)
        self.assertNotIn("proves", result.recommendation)

    def test_cache_hit_ratio_at_ninety_five_percent_is_warning(self) -> None:
        result = check_database_health(
            _mock_connection(_row(blocks_read=5, blocks_hit=95))
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["cache_hit_ratio_percent"], 95.0)

    def test_cache_hit_ratio_below_ninety_five_percent_is_critical(self) -> None:
        result = check_database_health(
            _mock_connection(_row(blocks_read=6, blocks_hit=94))
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["cache_hit_ratio_percent"], 94.0)

    def test_zero_blocks_read_and_hit_is_healthy_with_no_ratio(self) -> None:
        result = check_database_health(
            _mock_connection(_row(blocks_read=0, blocks_hit=0))
        )

        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.metrics["cache_hit_ratio_percent"])

    def test_low_rollback_ratio_is_normal(self) -> None:
        result = check_database_health(
            _mock_connection(_row(committed=99, rolled_back=1))
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["rollback_ratio_percent"], 1.0)

    def test_rollback_ratio_at_five_percent_is_warning(self) -> None:
        result = check_database_health(
            _mock_connection(_row(committed=95, rolled_back=5))
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["rollback_ratio_percent"], 5.0)
        self.assertIn("transaction lifecycle", result.recommendation)

    def test_rollback_ratio_at_twenty_percent_is_critical(self) -> None:
        result = check_database_health(
            _mock_connection(_row(committed=80, rolled_back=20))
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["rollback_ratio_percent"], 20.0)

    def test_zero_transactions_has_no_rollback_ratio(self) -> None:
        result = check_database_health(
            _mock_connection(_row(committed=0, rolled_back=0))
        )

        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.metrics["rollback_ratio_percent"])

    def test_temporary_files_present_is_warning_not_critical(self) -> None:
        result = check_database_health(
            _mock_connection(_row(temp_files=3, temp_bytes=2048))
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["temp_files"], 3)
        self.assertEqual(result.metrics["temp_bytes"], 2048)
        self.assertIn("Temporary files", result.recommendation)
        self.assertIn("before changing configuration", result.recommendation)

    def test_deadlocks_present_is_warning_not_current_deadlock_claim(self) -> None:
        result = check_database_health(_mock_connection(_row(deadlocks=2)))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["deadlocks"], 2)
        self.assertIn("historical cumulative events", result.recommendation)
        self.assertIn("not proof", result.recommendation)

    def test_null_counters_are_zero_safe(self) -> None:
        result = check_database_health(
            _mock_connection(
                (
                    "healthcheck_db",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["transactions_committed"], 0)
        self.assertEqual(result.metrics["blocks_read"], 0)
        self.assertIsNone(result.metrics["cache_hit_ratio_percent"])
        self.assertIsNone(result.metrics["rollback_ratio_percent"])

    def test_query_uses_current_database_and_does_not_reset_statistics(self) -> None:
        connection = _mock_connection(_row())

        check_database_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("WHERE datname = current_database()", executed_sql)
        self.assertNotIn("pg_stat_reset", executed_sql)


def _mock_connection(row: tuple[object, ...]) -> Mock:
    cursor = Mock()
    cursor.fetchone.return_value = row

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    database_name: str = "healthcheck_db",
    committed: int = 100,
    rolled_back: int = 0,
    blocks_read: int = 1,
    blocks_hit: int = 999,
    tuples_returned: int = 1000,
    tuples_fetched: int = 500,
    tuples_inserted: int = 10,
    tuples_updated: int = 5,
    tuples_deleted: int = 1,
    temp_files: int = 0,
    temp_bytes: int = 0,
    deadlocks: int = 0,
) -> tuple[object, ...]:
    return (
        database_name,
        committed,
        rolled_back,
        blocks_read,
        blocks_hit,
        tuples_returned,
        tuples_fetched,
        tuples_inserted,
        tuples_updated,
        tuples_deleted,
        temp_files,
        temp_bytes,
        deadlocks,
    )


if __name__ == "__main__":
    unittest.main()
