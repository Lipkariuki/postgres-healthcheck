"""Unit tests for CLI reporting and JSON output."""

from contextlib import redirect_stdout
from io import StringIO
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

main_module = importlib.import_module("main")
reporting = importlib.import_module("reporting")
health_module = importlib.import_module("models.health")
HealthCheckResult = health_module.HealthCheckResult


class ReportingTests(unittest.TestCase):
    """Tests for health report rendering and CLI output modes."""

    def test_overall_healthy_status(self) -> None:
        self.assertEqual(
            reporting.overall_status([_result("Connection Health")]),
            "healthy",
        )

    def test_overall_warning_status(self) -> None:
        results = [
            _result("Connection Health"),
            _result("Database Health", status="warning"),
        ]

        self.assertEqual(reporting.overall_status(results), "warning")

    def test_overall_critical_status(self) -> None:
        results = [
            _result("Connection Health"),
            _result("Query Health", status="critical"),
        ]

        self.assertEqual(reporting.overall_status(results), "critical")

    def test_strongest_status_wins(self) -> None:
        results = [
            _result("Connection Health", status="warning"),
            _result("Query Health", status="critical"),
            _result("Table Health", status="healthy"),
        ]

        self.assertEqual(reporting.overall_status(results), "critical")

    def test_seconds_formatter_under_one_minute(self) -> None:
        self.assertEqual(reporting.format_duration(45), "45s")

    def test_seconds_formatter_minutes(self) -> None:
        self.assertEqual(reporting.format_duration(125), "2m 5s")

    def test_seconds_formatter_hours(self) -> None:
        self.assertEqual(reporting.format_duration(3725), "1h 2m 5s")

    def test_seconds_formatter_days(self) -> None:
        self.assertEqual(reporting.format_duration(370017), "4d 6h 46m 57s")

    def test_byte_formatter_kb(self) -> None:
        self.assertEqual(reporting.format_bytes(1024), "1.0 KB")

    def test_byte_formatter_mb(self) -> None:
        self.assertEqual(reporting.format_bytes(1048576), "1.0 MB")
        self.assertEqual(reporting.format_bytes(13560519), "12.9 MB")

    def test_byte_formatter_gb(self) -> None:
        self.assertEqual(reporting.format_bytes(1073741824), "1.0 GB")

    def test_healthy_transaction_output_hides_none_fields(self) -> None:
        rendered = reporting.render_health_check_result(_transaction_result())

        self.assertIn("Open transactions: 0", rendered)
        self.assertNotIn("Oldest transaction PID: None", rendered)

    def test_healthy_lock_output_hides_blocker_details(self) -> None:
        rendered = reporting.render_health_check_result(_lock_result())

        self.assertIn("Blocked sessions: 0", rendered)
        self.assertNotIn("Root blocker PID: None", rendered)

    def test_human_readable_output_remains_valid(self) -> None:
        rendered = reporting.render_human_report(_all_results())

        self.assertTrue(rendered.startswith("PostgreSQL Health Check"))
        self.assertIn("Overall Status: HEALTHY", rendered)
        self.assertIn("Checks", rendered)
        self.assertIn("Connection Health", rendered)

    def test_json_returns_valid_json(self) -> None:
        parsed = json.loads(reporting.render_json_report(_all_results()))

        self.assertEqual(parsed["overall_status"], "healthy")
        self.assertIsInstance(parsed["checks"], list)

    def test_json_overall_status_is_correct(self) -> None:
        results = _all_results()
        results[6] = _query_result(status="critical")

        parsed = json.loads(reporting.render_json_report(results))

        self.assertEqual(parsed["overall_status"], "critical")

    def test_json_contains_all_health_checks(self) -> None:
        parsed = json.loads(reporting.render_json_report(_all_results()))

        self.assertEqual(len(parsed["checks"]), 8)
        self.assertEqual(parsed["checks"][-1]["name"], "Replication & WAL Health")

    def test_json_preserves_raw_metrics(self) -> None:
        parsed = json.loads(reporting.render_json_report(_all_results()))
        database_check = parsed["checks"][3]

        self.assertEqual(database_check["metrics"]["temp_bytes"], 13560519)
        self.assertIsInstance(database_check["metrics"]["temp_bytes"], int)

    def test_json_mode_contains_no_cli_header_text_before_json(self) -> None:
        output = StringIO()
        with patch.object(main_module, "get_connection", return_value=_Connection()):
            with patch.object(
                main_module,
                "collect_health_checks",
                return_value=_all_results(),
            ):
                with redirect_stdout(output):
                    main_module.main(["--json"])

        rendered = output.getvalue()
        parsed = json.loads(rendered)
        self.assertEqual(parsed["overall_status"], "healthy")
        self.assertTrue(rendered.lstrip().startswith("{"))
        self.assertNotIn("PostgreSQL Health Check", rendered)
        self.assertNotIn("✅", rendered)

    def test_connection_error_is_human_readable_in_default_mode(self) -> None:
        output = StringIO()
        error = main_module.DatabaseConnectionError("connection refused")

        with patch.object(main_module, "get_connection", side_effect=error):
            with redirect_stdout(output):
                main_module.main([])

        rendered = output.getvalue()
        self.assertIn("❌ Unable to connect:", rendered)
        self.assertIn("connection refused", rendered)

    def test_connection_error_is_structured_in_json_mode(self) -> None:
        output = StringIO()
        error = main_module.DatabaseConnectionError("connection refused")

        with patch.object(main_module, "get_connection", side_effect=error):
            with redirect_stdout(output):
                main_module.main(["--json"])

        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["status"], "error")
        self.assertEqual(parsed["error"], "Unable to connect")
        self.assertEqual(parsed["reason"], "connection refused")


class _Connection:
    """No-op context manager for mocked main tests."""

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def _result(name: str, status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name=name,
        status=status,
        summary="summary",
        metrics={},
        recommendation="recommendation",
    )


def _all_results() -> list[HealthCheckResult]:
    return [
        _connection_result(),
        _transaction_result(),
        _lock_result(),
        _database_result(),
        _table_result(),
        _index_result(),
        _query_result(),
        _replication_result(),
    ]


def _connection_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Connection Health",
        status=status,
        summary="10 of 100 connections are in use.",
        metrics={
            "current_connections": 10,
            "active_connections": 2,
            "idle_connections": 8,
            "idle_in_transaction_connections": 0,
            "oldest_idle_transaction_pid": None,
            "oldest_idle_transaction_seconds": None,
            "max_connections": 100,
            "connection_utilization_percent": 10.0,
        },
        recommendation="Connection capacity is healthy.",
    )


def _transaction_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Transaction Health",
        status=status,
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


def _lock_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Lock Health",
        status=status,
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


def _database_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Database Health",
        status=status,
        summary="Database-level statistics show no immediate health concerns.",
        metrics={
            "database_name": "healthcheck_db",
            "transactions_committed": 100,
            "transactions_rolled_back": 0,
            "rollback_ratio_percent": 0.0,
            "blocks_read": 1,
            "blocks_hit": 999,
            "cache_hit_ratio_percent": 99.9,
            "temp_files": 0,
            "temp_bytes": 13560519,
            "deadlocks": 0,
        },
        recommendation="Database-level statistics show no immediate health concerns.",
    )


def _table_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Table Health",
        status=status,
        summary="No table-maintenance risk detected.",
        metrics={
            "tables_checked": 3,
            "tables_with_dead_tuples": 0,
            "warning_tables": 0,
            "critical_tables": 0,
        },
        recommendation="No table-maintenance risk detected.",
    )


def _index_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Index Health",
        status=status,
        summary="No significant index-usage concerns detected.",
        metrics={
            "indexes_checked": 8,
            "indexes_used": 6,
            "indexes_with_zero_scans": 2,
            "large_zero_scan_indexes": 0,
            "protected_zero_scan_indexes": 1,
        },
        recommendation="No significant index-usage concerns detected.",
    )


def _query_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Query Health",
        status=status,
        summary="No significant query-latency concerns detected.",
        metrics={
            "pg_stat_statements_available": True,
            "queries_checked": 0,
            "total_calls": 0,
            "warning_latency_queries": 0,
            "critical_latency_queries": 0,
        },
        recommendation="No significant query-latency concerns detected.",
    )


def _replication_result(status: str = "healthy") -> HealthCheckResult:
    return HealthCheckResult(
        name="Replication & WAL Health",
        status=status,
        summary="No streaming replica is currently connected.",
        metrics={
            "server_role": "primary",
            "is_in_recovery": False,
            "replicas_connected": 0,
            "warning_replicas": 0,
            "critical_replicas": 0,
            "wal_records": 10,
            "wal_fpi": 1,
            "wal_bytes": 1048576,
            "wal_buffers_full": 0,
        },
        recommendation=(
            "No streaming replica is currently connected. This is expected for "
            "a standalone PostgreSQL environment."
        ),
    )


if __name__ == "__main__":
    unittest.main()
