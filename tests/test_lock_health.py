"""Unit tests for PostgreSQL lock health checks."""

from contextlib import redirect_stdout
from io import StringIO
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

locks_module = importlib.import_module("checks.locks")
main_module = importlib.import_module("main")
health_module = importlib.import_module("models.health")
check_lock_health = locks_module.check_lock_health
HealthCheckResult = health_module.HealthCheckResult


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class LockHealthTests(unittest.TestCase):
    """Tests for blocking session and lock contention health checks."""

    def test_no_blocked_sessions(self) -> None:
        result = check_lock_health(_mock_connection([]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["blocked_sessions"], 0)
        self.assertEqual(result.metrics["blocking_sessions"], 0)
        self.assertIsNone(result.metrics["oldest_blocked_pid"])
        self.assertIsNone(result.metrics["root_blocker_pid"])
        self.assertEqual(result.recommendation, "No lock contention detected.")

    def test_one_blocked_session(self) -> None:
        result = check_lock_health(_mock_connection([_row(blocked_seconds=12.0)]))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["blocked_sessions"], 1)
        self.assertEqual(result.metrics["blocking_sessions"], 1)
        self.assertEqual(result.metrics["oldest_blocked_pid"], 8201)
        self.assertEqual(result.metrics["root_blocker_pid"], 8123)
        self.assertIn("conflicting lock", result.recommendation)

    def test_one_blocker_blocking_multiple_sessions(self) -> None:
        result = check_lock_health(
            _mock_connection(
                [
                    _row(blocked_pid=8201, blocker_pid=8123),
                    _row(blocked_pid=8202, blocker_pid=8123),
                ]
            )
        )

        self.assertEqual(result.metrics["blocked_sessions"], 2)
        self.assertEqual(result.metrics["blocking_sessions"], 1)
        self.assertEqual(result.metrics["root_blocker_pid"], 8123)

    def test_blocked_session_under_thirty_seconds_is_warning(self) -> None:
        result = check_lock_health(_mock_connection([_row(blocked_seconds=29.0)]))

        self.assertEqual(result.status, "warning")

    def test_blocked_session_at_thirty_seconds_is_warning(self) -> None:
        result = check_lock_health(_mock_connection([_row(blocked_seconds=30.0)]))

        self.assertEqual(result.status, "warning")

    def test_blocked_session_over_thirty_seconds_is_critical(self) -> None:
        result = check_lock_health(_mock_connection([_row(blocked_seconds=31.0)]))

        self.assertEqual(result.status, "critical")

    def test_null_application_name_is_tolerated(self) -> None:
        result = check_lock_health(
            _mock_connection([_row(blocker_application=None)])
        )

        self.assertIsNone(result.metrics["root_blocker_application"])

    def test_null_wait_event_is_tolerated(self) -> None:
        result = check_lock_health(
            _mock_connection(
                [_row(blocked_wait_event_type=None, blocked_wait_event=None)]
            )
        )

        self.assertIsNone(result.metrics["blocked_wait_event_type"])
        self.assertIsNone(result.metrics["blocked_wait_event"])

    def test_long_running_blocker_transaction_is_called_out(self) -> None:
        result = check_lock_health(
            _mock_connection([_row(blocker_transaction_seconds=1800.0)])
        )

        self.assertIn("blocker transaction has been open", result.recommendation)
        self.assertIn("1800", result.recommendation)

    def test_monitoring_backend_is_excluded(self) -> None:
        connection = _mock_connection([])

        check_lock_health(connection)

        cursor = connection.cursor.return_value.cursor
        executed_sql = cursor.execute.call_args.args[0]
        self.assertIn("blocked.pid <> pg_backend_pid()", executed_sql)

    def test_healthy_cli_output_hides_none_fields(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            main_module._print_health_check_result(
                HealthCheckResult(
                    name="Transaction Health",
                    status="healthy",
                    summary="No open transactions were found.",
                    metrics={
                        "open_transactions": 0,
                        "long_running_transactions": 0,
                        "oldest_transaction_pid": None,
                        "oldest_transaction_seconds": None,
                        "oldest_transaction_state": None,
                        "oldest_transaction_user": None,
                        "oldest_transaction_application": None,
                        "oldest_transaction_wait_event_type": None,
                        "oldest_transaction_wait_event": None,
                    },
                    recommendation="No long-running transaction risk detected.",
                )
            )
            print()
            main_module._print_health_check_result(
                HealthCheckResult(
                    name="Lock Health",
                    status="healthy",
                    summary="No blocked sessions were found.",
                    metrics={
                        "blocked_sessions": 0,
                        "blocking_sessions": 0,
                        "oldest_blocked_pid": None,
                        "oldest_blocked_seconds": None,
                        "root_blocker_pid": None,
                        "root_blocker_user": None,
                        "root_blocker_application": None,
                        "root_blocker_state": None,
                        "root_blocker_transaction_seconds": None,
                        "blocked_wait_event_type": None,
                        "blocked_wait_event": None,
                    },
                    recommendation="No lock contention detected.",
                )
            )

        rendered = output.getvalue()
        self.assertIn("Open transactions: 0", rendered)
        self.assertIn("Blocked sessions: 0", rendered)
        self.assertNotIn("Oldest transaction PID: None", rendered)
        self.assertNotIn("Root blocker PID: None", rendered)
        self.assertNotIn("Blocked wait event: None", rendered)


def _mock_connection(rows: list[tuple[object, ...]]) -> Mock:
    cursor = Mock()
    cursor.fetchall.return_value = rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _row(
    blocked_pid: int = 8201,
    blocked_user: str = "postgres",
    blocked_application: str | None = "app-worker",
    blocked_state: str = "active",
    blocked_wait_event_type: str | None = "Lock",
    blocked_wait_event: str | None = "transactionid",
    blocked_seconds: float = 12.0,
    blocked_query: str | None = "UPDATE accounts SET balance = balance + 1",
    blocker_pid: int = 8123,
    blocker_user: str = "postgres",
    blocker_application: str | None = "psql",
    blocker_state: str = "idle in transaction",
    blocker_transaction_seconds: float | None = 120.0,
    blocker_query: str | None = "UPDATE accounts SET balance = balance - 1",
) -> tuple[object, ...]:
    return (
        blocked_pid,
        blocked_user,
        blocked_application,
        blocked_state,
        blocked_wait_event_type,
        blocked_wait_event,
        blocked_seconds,
        blocked_query,
        blocker_pid,
        blocker_user,
        blocker_application,
        blocker_state,
        blocker_transaction_seconds,
        blocker_query,
    )


if __name__ == "__main__":
    unittest.main()
