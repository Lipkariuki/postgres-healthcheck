"""Unit tests for PostgreSQL query health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

query_health_module = importlib.import_module("checks.query_health")
check_query_health = query_health_module.check_query_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class QueryHealthTests(unittest.TestCase):
    """Tests for query latency and cumulative execution health checks."""

    def test_pg_stat_statements_unavailable(self) -> None:
        connection = _mock_connection(extension_available=False, rows=[])

        result = check_query_health(connection)

        self.assertEqual(result.status, "warning")
        self.assertFalse(result.metrics["pg_stat_statements_available"])
        self.assertEqual(result.metrics["queries_checked"], 0)
        self.assertIn("pg_stat_statements", result.recommendation)
        self.assertIn("does not install", result.recommendation)
        cursor = connection.cursor.return_value.cursor
        self.assertEqual(cursor.execute.call_count, 1)

    def test_no_query_statistics(self) -> None:
        result = check_query_health(_mock_connection(rows=[]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["queries_checked"], 0)
        self.assertEqual(result.metrics["total_calls"], 0)
        self.assertIsNone(result.metrics["top_total_query"])
        self.assertEqual(
            result.recommendation,
            "No significant query-latency concerns detected.",
        )

    def test_fast_query_is_healthy(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=99.0)]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["warning_latency_queries"], 0)
        self.assertEqual(result.metrics["critical_latency_queries"], 0)

    def test_mean_exactly_one_hundred_ms_is_warning(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=100.0)]))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["warning_latency_queries"], 1)
        self.assertEqual(result.metrics["critical_latency_queries"], 0)

    def test_mean_between_one_hundred_and_five_hundred_ms_is_warning(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=250.0)]))

        self.assertEqual(result.status, "warning")
        self.assertIn("elevated average execution time", result.recommendation)
        self.assertIn("accumulated observations", result.recommendation)

    def test_mean_exactly_five_hundred_ms_is_critical(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=500.0)]))

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["critical_latency_queries"], 1)

    def test_mean_above_five_hundred_ms_is_critical(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=700.0)]))

        self.assertEqual(result.status, "critical")
        self.assertIn("does not mean the query is currently running", result.recommendation)

    def test_high_calls_with_low_mean_remains_healthy(self) -> None:
        result = check_query_health(
            _mock_connection(rows=[_row(calls=1_000_000, mean_ms=1.0)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["total_calls"], 1_000_000)

    def test_low_calls_with_high_mean_becomes_critical(self) -> None:
        result = check_query_health(
            _mock_connection(rows=[_row(calls=1, mean_ms=800.0)])
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["slowest_mean_calls"], 1)

    def test_highest_total_execution_query_selected_correctly(self) -> None:
        result = check_query_health(
            _mock_connection(
                rows=[
                    _row(query="SELECT 1", total_ms=100.0),
                    _row(query="SELECT 2", total_ms=900.0),
                ]
            )
        )

        self.assertEqual(result.metrics["top_total_query"], "SELECT 2")
        self.assertEqual(result.metrics["top_total_exec_time_ms"], 900.0)

    def test_highest_mean_query_selected_correctly(self) -> None:
        result = check_query_health(
            _mock_connection(
                rows=[
                    _row(query="SELECT fast", mean_ms=10.0),
                    _row(query="SELECT slow", mean_ms=300.0),
                ]
            )
        )

        self.assertEqual(result.metrics["slowest_mean_query"], "SELECT slow")
        self.assertEqual(result.metrics["slowest_mean_exec_time_ms"], 300.0)

    def test_highest_max_execution_query_selected_correctly(self) -> None:
        result = check_query_health(
            _mock_connection(
                rows=[
                    _row(query="SELECT steady", max_ms=50.0),
                    _row(query="SELECT spike", max_ms=1000.0),
                ]
            )
        )

        self.assertEqual(result.metrics["highest_max_query"], "SELECT spike")
        self.assertEqual(result.metrics["highest_max_exec_time_ms"], 1000.0)

    def test_multiple_queries_use_strongest_status(self) -> None:
        result = check_query_health(
            _mock_connection(
                rows=[
                    _row(query="SELECT warning", mean_ms=150.0),
                    _row(query="SELECT critical", mean_ms=650.0),
                    _row(query="SELECT fast", mean_ms=1.0),
                ]
            )
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["warning_latency_queries"], 1)
        self.assertEqual(result.metrics["critical_latency_queries"], 1)

    def test_null_and_zero_safe_handling(self) -> None:
        result = check_query_health(
            _mock_connection(rows=[(None, None, None, None, None, None)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["total_calls"], 0)
        self.assertIsNone(result.metrics["top_total_query"])
        self.assertEqual(result.metrics["top_total_exec_time_ms"], 0.0)

    def test_query_text_is_safely_truncated(self) -> None:
        long_query = "SELECT " + ", ".join(f"column_{index}" for index in range(50))

        result = check_query_health(_mock_connection(rows=[_row(query=long_query)]))

        query_text = result.metrics["top_total_query"]
        self.assertIsInstance(query_text, str)
        self.assertLessEqual(len(query_text), 150)
        self.assertTrue(query_text.endswith("..."))

    def test_sql_is_read_only(self) -> None:
        connection = _mock_connection(rows=[])

        check_query_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = " ".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn("FROM pg_extension", executed_sql)
        self.assertIn("FROM pg_stat_statements", executed_sql)
        self.assertNotIn("DROP", executed_sql.upper())
        self.assertNotIn("CREATE", executed_sql.upper())
        self.assertNotIn("ALTER", executed_sql.upper())
        self.assertNotIn("SET ", executed_sql.upper())
        self.assertNotIn("SELECT PG_TERMINATE_BACKEND", executed_sql.upper())
        self.assertNotIn("SELECT PG_CANCEL_BACKEND", executed_sql.upper())

    def test_no_automatic_explain_analyze(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=700.0)]))

        self.assertNotIn("EXPLAIN ANALYZE", result.recommendation.upper())

    def test_no_configuration_changes(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=700.0)]))

        self.assertNotIn("ALTER SYSTEM", result.recommendation.upper())
        self.assertNotIn("shared_buffers", result.recommendation)
        self.assertNotIn("work_mem", result.recommendation)

    def test_no_query_termination(self) -> None:
        result = check_query_health(_mock_connection(rows=[_row(mean_ms=700.0)]))

        self.assertNotIn("kill", result.recommendation.lower())
        self.assertNotIn("terminate", result.recommendation.lower())
        self.assertNotIn("cancel", result.recommendation.lower())

    def test_extension_absence_does_not_crash_the_application(self) -> None:
        result = check_query_health(
            _mock_connection(extension_available=False, rows=[])
        )

        self.assertEqual(result.name, "Query Health")
        self.assertFalse(result.metrics["pg_stat_statements_available"])


def _mock_connection(
    rows: list[tuple[object, ...]],
    extension_available: bool = True,
) -> Mock:
    cursor = Mock()
    cursor.fetchone.return_value = (1,) if extension_available else None
    cursor.fetchall.return_value = rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    query: str | None = "SELECT * FROM orders WHERE id = $1",
    calls: int | None = 10,
    total_ms: float | None = 100.0,
    mean_ms: float | None = 10.0,
    max_ms: float | None = 20.0,
    rows: int | None = 10,
) -> tuple[object, ...]:
    return (
        query,
        calls,
        total_ms,
        mean_ms,
        max_ms,
        rows,
    )


if __name__ == "__main__":
    unittest.main()
