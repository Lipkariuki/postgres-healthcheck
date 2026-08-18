"""Unit tests for PostgreSQL transaction health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

transactions_module = importlib.import_module("checks.transactions")
check_transaction_health = transactions_module.check_transaction_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class TransactionHealthTests(unittest.TestCase):
    """Tests for long-running transaction health status and recommendations."""

    def test_no_long_running_transactions(self) -> None:
        result = check_transaction_health(_mock_connection([]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["open_transactions"], 0)
        self.assertEqual(result.metrics["long_running_transactions"], 0)
        self.assertIsNone(result.metrics["oldest_transaction_pid"])
        self.assertIsNone(result.metrics["oldest_transaction_seconds"])

    def test_transaction_under_five_minutes_is_healthy(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=299.0)]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["open_transactions"], 1)
        self.assertEqual(result.metrics["long_running_transactions"], 0)
        self.assertEqual(result.metrics["oldest_transaction_seconds"], 299.0)

    def test_transaction_at_five_minutes_is_warning(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=300.0)]))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["long_running_transactions"], 1)
        self.assertIn("Investigate", result.recommendation)

    def test_transaction_between_five_and_thirty_minutes_is_warning(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=600.0)]))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["oldest_transaction_pid"], 1234)

    def test_transaction_at_thirty_minutes_is_warning(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=1800.0)]))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["long_running_transactions"], 1)

    def test_transaction_between_thirty_and_sixty_minutes_is_warning(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=2400.0)]))

        self.assertEqual(result.status, "warning")
        self.assertIn("VACUUM", result.recommendation)
        self.assertIn("table bloat", result.recommendation)

    def test_transaction_at_sixty_minutes_is_warning(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=3600.0)]))

        self.assertEqual(result.status, "warning")

    def test_transaction_over_sixty_minutes_is_critical(self) -> None:
        result = check_transaction_health(_mock_connection([_row(age_seconds=3601.0)]))

        self.assertEqual(result.status, "critical")
        self.assertIn("old row versions", result.recommendation)

    def test_long_running_idle_in_transaction_is_highlighted(self) -> None:
        result = check_transaction_health(
            _mock_connection([_row(age_seconds=600.0, state="idle in transaction")])
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("idle in transaction", result.summary)
        self.assertIn("idle in transaction", result.recommendation)

    def test_null_application_name_is_tolerated(self) -> None:
        result = check_transaction_health(
            _mock_connection([_row(age_seconds=600.0, application_name=None)])
        )

        self.assertIsNone(result.metrics["oldest_transaction_application"])

    def test_null_wait_event_is_tolerated(self) -> None:
        result = check_transaction_health(
            _mock_connection(
                [
                    _row(
                        age_seconds=600.0,
                        wait_event_type=None,
                        wait_event=None,
                    )
                ]
            )
        )

        self.assertIsNone(result.metrics["oldest_transaction_wait_event_type"])
        self.assertIsNone(result.metrics["oldest_transaction_wait_event"])

    def test_unavailable_query_text_is_tolerated(self) -> None:
        result = check_transaction_health(
            _mock_connection([_row(age_seconds=600.0, query=None)])
        )

        self.assertIsNone(result.metrics["oldest_transaction_query"])

    def test_monitoring_backend_is_excluded(self) -> None:
        connection = _mock_connection([])

        check_transaction_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("pid <> pg_backend_pid()", executed_sql)


def _mock_connection(rows: list[tuple[object, ...]]) -> Mock:
    cursor = Mock()
    cursor.fetchall.return_value = rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    pid: int = 1234,
    user: str = "postgres",
    application_name: str | None = "health-check-app",
    state: str = "active",
    age_seconds: float = 600.0,
    wait_event_type: str | None = "Lock",
    wait_event: str | None = "transactionid",
    query: str | None = "SELECT * FROM accounts",
) -> tuple[object, ...]:
    return (
        pid,
        user,
        application_name,
        state,
        age_seconds,
        wait_event_type,
        wait_event,
        query,
    )


if __name__ == "__main__":
    unittest.main()
