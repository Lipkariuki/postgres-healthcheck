"""Unit tests for PostgreSQL connection health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

check_connection_health = importlib.import_module(
    "checks.connections"
).check_connection_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class ConnectionHealthTests(unittest.TestCase):
    """Tests for connection utilization status and recommendations."""

    def test_healthy_utilization(self) -> None:
        result = check_connection_health(_mock_connection((12, 2, 10, 0), ("100",)))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["current_connections"], 12)
        self.assertEqual(result.metrics["max_connections"], 100)
        self.assertEqual(result.metrics["connection_utilization_percent"], 12.0)
        self.assertEqual(result.recommendation, "Connection capacity is healthy.")

    def test_warning_utilization(self) -> None:
        result = check_connection_health(_mock_connection((70, 10, 60, 0), ("100",)))

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["connection_utilization_percent"], 70.0)
        self.assertIn("elevated", result.recommendation)

    def test_critical_utilization(self) -> None:
        result = check_connection_health(_mock_connection((91, 20, 71, 0), ("100",)))

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["connection_utilization_percent"], 91.0)
        self.assertIn("critical", result.recommendation)

    def test_idle_in_transaction_recommendation(self) -> None:
        result = check_connection_health(
            _mock_connection((12, 2, 9, 1), ("100",), (1234, 120.0))
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["idle_in_transaction_connections"], 1)
        self.assertEqual(result.metrics["oldest_idle_transaction_pid"], 1234)
        self.assertEqual(result.metrics["oldest_idle_transaction_seconds"], 120.0)
        self.assertIn("Idle-in-transaction", result.recommendation)
        self.assertIn("retain locks", result.recommendation)
        self.assertIn("VACUUM", result.recommendation)
        self.assertIn("table bloat", result.recommendation)

    def test_no_idle_transaction_oldest_metrics_are_none(self) -> None:
        result = check_connection_health(_mock_connection((12, 2, 10, 0), ("100",)))

        self.assertIsNone(result.metrics["oldest_idle_transaction_pid"])
        self.assertIsNone(result.metrics["oldest_idle_transaction_seconds"])

    def test_old_idle_transaction_recommendation_is_urgent(self) -> None:
        result = check_connection_health(
            _mock_connection((12, 2, 9, 1), ("100",), (2345, 1801.0))
        )

        self.assertEqual(result.metrics["oldest_idle_transaction_pid"], 2345)
        self.assertEqual(result.metrics["oldest_idle_transaction_seconds"], 1801.0)
        self.assertIn("Urgent", result.recommendation)
        self.assertIn("Do not automatically terminate", result.recommendation)


def _mock_connection(
    counts_row: tuple[int, int, int, int],
    max_connections_row: tuple[str],
    oldest_idle_transaction_row: tuple[int, float] | None = None,
) -> Mock:
    cursor = Mock()
    cursor.fetchone.side_effect = [
        counts_row,
        oldest_idle_transaction_row,
        max_connections_row,
    ]

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


if __name__ == "__main__":
    unittest.main()
