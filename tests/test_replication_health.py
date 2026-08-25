"""Unit tests for PostgreSQL replication and WAL health checks."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

replication_health_module = importlib.import_module("checks.replication_health")
check_replication_health = replication_health_module.check_replication_health


class CursorContext:
    """Small context manager wrapper for a mocked cursor."""

    def __init__(self, cursor: Mock) -> None:
        self.cursor = cursor

    def __enter__(self) -> Mock:
        return self.cursor

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class ReplicationHealthTests(unittest.TestCase):
    """Tests for replication lag and WAL health checks."""

    def test_standalone_primary_with_zero_replicas(self) -> None:
        result = check_replication_health(_mock_primary_connection([]))

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["server_role"], "primary")
        self.assertFalse(result.metrics["is_in_recovery"])
        self.assertEqual(result.metrics["replicas_connected"], 0)
        self.assertIn("standalone PostgreSQL environment", result.recommendation)

    def test_primary_with_one_healthy_replica(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=4.0)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["replicas_connected"], 1)
        self.assertEqual(result.metrics["warning_replicas"], 0)
        self.assertEqual(result.metrics["critical_replicas"], 0)

    def test_primary_replica_lag_exactly_five_seconds_is_warning(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=5.0)])
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["warning_replicas"], 1)

    def test_primary_replica_lag_between_five_and_thirty_seconds_is_warning(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=12.0)])
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("Replication lag is present", result.recommendation)

    def test_primary_replica_lag_exactly_thirty_seconds_is_critical(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=30.0)])
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["critical_replicas"], 1)

    def test_primary_with_critical_replica_lag(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=45.0)])
        )

        self.assertEqual(result.status, "critical")
        self.assertIn("storage performance", result.recommendation)

    def test_multiple_replicas_select_most_lagging(self) -> None:
        result = check_replication_health(
            _mock_primary_connection(
                [
                    _replica_row(application_name="replica-a", replay_lag=6.0),
                    _replica_row(application_name="replica-b", replay_lag=22.0),
                ]
            )
        )

        self.assertEqual(
            result.metrics["most_lagging_replica_application"],
            "replica-b",
        )
        self.assertEqual(result.metrics["most_lagging_replay_lag_seconds"], 22.0)

    def test_replica_server_detected(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(_replay_row(replay_delay=1.0))
        )

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.metrics["server_role"], "replica")
        self.assertTrue(result.metrics["is_in_recovery"])
        self.assertEqual(result.metrics["replay_delay_seconds"], 1.0)

    def test_replica_replay_delay_healthy(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(_replay_row(replay_delay=4.0))
        )

        self.assertEqual(result.status, "healthy")

    def test_replica_replay_delay_warning(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(_replay_row(replay_delay=5.0))
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.metrics["warning_replicas"], 1)

    def test_replica_replay_delay_critical(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(_replay_row(replay_delay=30.0))
        )

        self.assertEqual(result.status, "critical")
        self.assertEqual(result.metrics["critical_replicas"], 1)

    def test_null_replay_lag(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=None)])
        )

        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.metrics["most_lagging_replay_lag_seconds"])

    def test_null_replay_timestamp(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(
                _replay_row(last_replay_timestamp=None, replay_delay=None)
            )
        )

        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.metrics["last_xact_replay_timestamp"])
        self.assertIsNone(result.metrics["replay_delay_seconds"])

    def test_wal_statistics_returned(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([], wal_row=(10, 2, 4096, 1, 3, 4))
        )

        self.assertEqual(result.metrics["wal_records"], 10)
        self.assertEqual(result.metrics["wal_fpi"], 2)
        self.assertEqual(result.metrics["wal_bytes"], 4096)
        self.assertEqual(result.metrics["wal_buffers_full"], 1)
        self.assertEqual(result.metrics["wal_write"], 3)
        self.assertEqual(result.metrics["wal_sync"], 4)

    def test_wal_counters_zero_safe(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([], wal_row=(None, None, None, None, None, None))
        )

        self.assertEqual(result.metrics["wal_records"], 0)
        self.assertEqual(result.metrics["wal_bytes"], 0)
        self.assertEqual(result.metrics["wal_sync"], 0)

    def test_query_is_read_only(self) -> None:
        connection = _mock_primary_connection([])

        check_replication_health(connection)

        executed_sql = _executed_sql(connection)
        self.assertIn("SELECT pg_is_in_recovery()", executed_sql)
        self.assertIn("FROM pg_stat_replication", executed_sql)
        self.assertIn("FROM pg_stat_wal", executed_sql)
        self.assertNotIn("UPDATE ", executed_sql.upper())
        self.assertNotIn("DELETE ", executed_sql.upper())
        self.assertNotIn("INSERT ", executed_sql.upper())

    def test_no_statistics_reset(self) -> None:
        connection = _mock_primary_connection([])

        check_replication_health(connection)

        self.assertNotIn("PG_STAT_RESET", _executed_sql(connection).upper())

    def test_no_replication_restart(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=45.0)])
        )

        self.assertNotIn("restart", result.recommendation.lower())

    def test_no_slot_modification(self) -> None:
        result = check_replication_health(
            _mock_primary_connection([_replica_row(replay_lag=45.0)])
        )

        self.assertNotIn("modify slots", result.recommendation.lower())
        self.assertNotIn("drop slot", result.recommendation.lower())

    def test_no_automatic_remediation(self) -> None:
        result = check_replication_health(
            _mock_replica_connection(_replay_row(replay_delay=45.0))
        )

        self.assertIn("Do not restart replication", result.recommendation)
        self.assertIn("modify slots automatically", result.recommendation)
        self.assertNotIn("terminate", result.recommendation.lower())


def _mock_primary_connection(
    replication_rows: list[tuple[object, ...]],
    wal_row: tuple[object, ...] = (100, 10, 2048, 0, 5, 1),
) -> Mock:
    cursor = Mock()
    cursor.fetchone.side_effect = [(False,), wal_row]
    cursor.fetchall.return_value = replication_rows

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _mock_replica_connection(
    replay_row: tuple[object, ...],
    wal_row: tuple[object, ...] = (100, 10, 2048, 0, 5, 1),
) -> Mock:
    cursor = Mock()
    cursor.fetchone.side_effect = [(True,), wal_row, replay_row]

    connection = Mock()
    connection.cursor.return_value = CursorContext(cursor)
    return connection


def _replica_row(
    pid: int = 1234,
    application_name: str | None = "replica-a",
    client_addr: str | None = "127.0.0.1",
    state: str | None = "streaming",
    sync_state: str | None = "async",
    sent_lsn: str | None = "0/3000000",
    write_lsn: str | None = "0/3000000",
    flush_lsn: str | None = "0/3000000",
    replay_lsn: str | None = "0/3000000",
    write_lag: float | None = 1.0,
    flush_lag: float | None = 1.0,
    replay_lag: float | None = 1.0,
) -> tuple[object, ...]:
    return (
        pid,
        application_name,
        client_addr,
        state,
        sync_state,
        sent_lsn,
        write_lsn,
        flush_lsn,
        replay_lsn,
        write_lag,
        flush_lag,
        replay_lag,
    )


def _replay_row(
    receive_lsn: str | None = "0/3000000",
    replay_lsn: str | None = "0/3000000",
    last_replay_timestamp: str | None = "2026-08-25 10:00:00+03",
    replay_delay: float | None = 1.0,
) -> tuple[object, ...]:
    return (
        receive_lsn,
        replay_lsn,
        last_replay_timestamp,
        replay_delay,
    )


def _executed_sql(connection: Mock) -> str:
    cursor = connection.cursor.return_value.cursor
    return " ".join(call.args[0] for call in cursor.execute.call_args_list)


if __name__ == "__main__":
    unittest.main()
