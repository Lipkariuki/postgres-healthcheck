"""Unit tests for PostgreSQL table maintenance health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

table_health_module = importlib.import_module("checks.table_health")
check_table_health = table_health_module.check_table_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class TableHealthTests(unittest.TestCase):
    """Tests for table maintenance and autovacuum health checks."""

    def test_no_user_tables(self) -> None:
        result = check_table_health(_mock_connection([]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_checked"], 0)
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 0)
        self.assertIsNone(result.metrics["highest_dead_tuple_ratio_percent"])
        self.assertIsNone(result.metrics["most_concerning_table"])
        self.assertEqual(result.recommendation, "No table-maintenance risk detected.")

    def test_healthy_table_with_no_dead_tuples(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=100, dead_tuples=0)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_checked"], 1)
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 0)
        self.assertEqual(result.metrics["warning_tables"], 0)
        self.assertEqual(result.metrics["critical_tables"], 0)

    def test_dead_tuple_ratio_below_ten_percent_is_healthy(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=91, dead_tuples=9)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 1)
        self.assertIsNone(result.metrics["most_concerning_table"])

    def test_dead_tuple_ratio_exactly_ten_percent_is_warning(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=900, dead_tuples=100)])
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["warning_tables"], 1)
        self.assertEqual(result.metrics["critical_tables"], 0)
        self.assertEqual(result.metrics["highest_dead_tuple_ratio_percent"], 10.0)
        self.assertEqual(
            result.metrics["most_concerning_total_estimated_tuples"],
            1000,
        )

    def test_dead_tuple_ratio_between_ten_and_twenty_percent_is_warning(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=850, dead_tuples=150)])
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("elevated dead tuple ratio", result.recommendation)
        self.assertIn("long-running transactions", result.recommendation)

    def test_dead_tuple_ratio_exactly_twenty_percent_is_critical(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=800, dead_tuples=200)])
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["critical_tables"], 1)
        self.assertEqual(result.metrics["highest_dead_tuple_ratio_percent"], 20.0)
        self.assertEqual(
            result.metrics["most_concerning_total_estimated_tuples"],
            1000,
        )

    def test_dead_tuple_ratio_above_twenty_percent_is_critical(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=750, dead_tuples=250)])
        )

        self.assertEqual(result.status, "critical")
        self.assertIn("VACUUM", result.recommendation)
        self.assertNotIn("VACUUM FULL", result.recommendation)

    def test_multiple_tables_selects_highest_ratio_as_most_concerning(self) -> None:
        result = check_table_health(
            _mock_connection(
                [
                    _row(table="orders", live_tuples=900, dead_tuples=100),
                    _row(table="payments", live_tuples=700, dead_tuples=300),
                    _row(table="customers", live_tuples=1000, dead_tuples=0),
                ]
            )
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["most_concerning_table"], "payments")
        self.assertEqual(result.metrics["highest_dead_tuple_ratio_percent"], 30.0)

    def test_null_last_autovacuum_is_preserved_without_forcing_critical(self) -> None:
        result = check_table_health(
            _mock_connection(
                [_row(live_tuples=900, dead_tuples=100, last_autovacuum=None)]
            )
        )

        self.assertEqual(result.status, "warning")
        self.assertIsNone(result.metrics["most_concerning_last_autovacuum"])

    def test_null_last_autoanalyze_is_preserved_without_forcing_critical(self) -> None:
        result = check_table_health(
            _mock_connection(
                [_row(live_tuples=900, dead_tuples=100, last_autoanalyze=None)]
            )
        )

        self.assertEqual(result.status, "warning")
        self.assertIsNone(result.metrics["most_concerning_last_autoanalyze"])

    def test_zero_live_and_dead_tuples_is_healthy_with_no_ratio(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=0, dead_tuples=0)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.metrics["highest_dead_tuple_ratio_percent"])

    def test_high_raw_dead_tuple_count_with_low_ratio_is_healthy(self) -> None:
        result = check_table_health(
            _mock_connection(
                [_row(live_tuples=2_000_000_000, dead_tuples=1_000_000)]
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 1)
        self.assertIsNone(result.metrics["most_concerning_table"])

    def test_one_live_two_dead_is_healthy_despite_high_ratio(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=1, dead_tuples=2)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 1)
        self.assertIsNone(result.metrics["most_concerning_table"])

    def test_three_live_one_dead_is_healthy_despite_high_ratio(self) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=3, dead_tuples=1)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["tables_with_dead_tuples"], 1)
        self.assertIsNone(result.metrics["most_concerning_table"])

    def test_low_raw_count_high_ratio_can_be_critical_for_meaningful_table(
        self,
    ) -> None:
        result = check_table_health(
            _mock_connection([_row(live_tuples=750, dead_tuples=250)])
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["highest_dead_tuple_ratio_percent"], 25.0)

    def test_hot_update_metric_is_preserved(self) -> None:
        result = check_table_health(
            _mock_connection(
                [_row(live_tuples=800, dead_tuples=200, hot_updates=7)]
            )
        )

        self.assertEqual(result.metrics["most_concerning_hot_updates"], 7)

    def test_query_is_read_only_and_uses_pg_stat_user_tables(self) -> None:
        connection = _mock_connection([])

        check_table_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("FROM pg_stat_user_tables", executed_sql)
        self.assertNotIn("VACUUM FULL", executed_sql.upper())
        self.assertNotIn("UPDATE ", executed_sql.upper())
        self.assertNotIn("DELETE ", executed_sql.upper())
        self.assertNotIn("INSERT ", executed_sql.upper())


def _mock_connection(rows: list[tuple[object, ...]]) -> Mock:
    cursor = Mock()
    cursor.fetchall.return_value = rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    schema: str = "public",
    table: str = "orders",
    live_tuples: int = 100,
    dead_tuples: int = 0,
    inserts: int = 10,
    updates: int = 5,
    deletes: int = 1,
    hot_updates: int = 2,
    last_vacuum: str | None = "2026-08-20 09:00:00+03",
    last_autovacuum: str | None = "2026-08-20 10:00:00+03",
    last_analyze: str | None = "2026-08-20 09:30:00+03",
    last_autoanalyze: str | None = "2026-08-20 10:30:00+03",
) -> tuple[object, ...]:
    return (
        schema,
        table,
        live_tuples,
        dead_tuples,
        inserts,
        updates,
        deletes,
        hot_updates,
        last_vacuum,
        last_autovacuum,
        last_analyze,
        last_autoanalyze,
    )


if __name__ == "__main__":
    unittest.main()
