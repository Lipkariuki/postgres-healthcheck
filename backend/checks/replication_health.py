"""Replication and WAL health checks for PostgreSQL."""

from typing import Any

from models.health import HealthCheckResult


SERVER_ROLE_SQL = "SELECT pg_is_in_recovery();"

PRIMARY_REPLICATION_SQL = """
SELECT
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
    replay_lag
FROM pg_stat_replication;
"""

REPLICA_REPLAY_SQL = """
SELECT
    pg_last_wal_receive_lsn(),
    pg_last_wal_replay_lsn(),
    pg_last_xact_replay_timestamp(),
    EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()));
"""

WAL_STATS_SQL = """
SELECT
    wal_records,
    wal_fpi,
    wal_bytes,
    wal_buffers_full,
    wal_write,
    wal_sync
FROM pg_stat_wal;
"""

REPLICATION_LAG_WARNING_SECONDS = 5.0
REPLICATION_LAG_CRITICAL_SECONDS = 30.0


def check_replication_health(connection: Any) -> HealthCheckResult:
    """Check server role, streaming replication lag, and WAL context."""
    with connection.cursor() as cursor:
        cursor.execute(SERVER_ROLE_SQL)
        role_row = cursor.fetchone()
        if role_row is None:
            raise RuntimeError("Unable to determine PostgreSQL recovery state")

        is_in_recovery = bool(role_row[0])
        wal_metrics = _read_wal_metrics(cursor)

        if is_in_recovery:
            cursor.execute(REPLICA_REPLAY_SQL)
            replica_replay_row = cursor.fetchone()
            return _replica_result(replica_replay_row, wal_metrics)

        cursor.execute(PRIMARY_REPLICATION_SQL)
        replication_rows = cursor.fetchall()
        return _primary_result(replication_rows, wal_metrics)


def _read_wal_metrics(cursor: Any) -> dict[str, int]:
    """Return cumulative WAL statistics, treating unavailable values as zero."""
    cursor.execute(WAL_STATS_SQL)
    wal_row = cursor.fetchone()
    if wal_row is None:
        return _empty_wal_metrics()

    return {
        "wal_records": _int_or_zero(wal_row[0]),
        "wal_fpi": _int_or_zero(wal_row[1]),
        "wal_bytes": _int_or_zero(wal_row[2]),
        "wal_buffers_full": _int_or_zero(wal_row[3]),
        "wal_write": _int_or_zero(wal_row[4]),
        "wal_sync": _int_or_zero(wal_row[5]),
    }


def _empty_wal_metrics() -> dict[str, int]:
    """Return zeroed WAL metrics."""
    return {
        "wal_records": 0,
        "wal_fpi": 0,
        "wal_bytes": 0,
        "wal_buffers_full": 0,
        "wal_write": 0,
        "wal_sync": 0,
    }


def _primary_result(
    replication_rows: list[tuple[object, ...]],
    wal_metrics: dict[str, int],
) -> HealthCheckResult:
    """Return a health result for a primary PostgreSQL server."""
    replicas = [_replica_from_row(row) for row in replication_rows]
    warning_replicas = sum(1 for replica in replicas if _has_warning_lag(replica))
    critical_replicas = sum(1 for replica in replicas if _has_critical_lag(replica))
    most_lagging_replica = _most_lagging_replica(replicas)
    status = _status_for(warning_replicas, critical_replicas)

    return HealthCheckResult(
        name="Replication & WAL Health",
        status=status,
        summary=_primary_summary_for(status, len(replicas), most_lagging_replica),
        metrics={
            "server_role": "primary",
            "is_in_recovery": False,
            "replicas_connected": len(replicas),
            "warning_replicas": warning_replicas,
            "critical_replicas": critical_replicas,
            "most_lagging_replica_application": (
                most_lagging_replica["application_name"]
                if most_lagging_replica
                else None
            ),
            "most_lagging_replica_client_addr": (
                most_lagging_replica["client_addr"] if most_lagging_replica else None
            ),
            "most_lagging_replica_state": (
                most_lagging_replica["state"] if most_lagging_replica else None
            ),
            "most_lagging_replica_sync_state": (
                most_lagging_replica["sync_state"] if most_lagging_replica else None
            ),
            "most_lagging_replay_lag_seconds": (
                most_lagging_replica["replay_lag_seconds"]
                if most_lagging_replica
                else None
            ),
            "last_wal_receive_lsn": None,
            "last_wal_replay_lsn": None,
            "last_xact_replay_timestamp": None,
            "replay_delay_seconds": None,
            **wal_metrics,
        },
        recommendation=_primary_recommendation_for(status, len(replicas)),
    )


def _replica_result(
    replica_replay_row: tuple[object, ...] | None,
    wal_metrics: dict[str, int],
) -> HealthCheckResult:
    """Return a health result for a standby PostgreSQL server."""
    replay = _replay_from_row(replica_replay_row)
    replay_delay_seconds = replay["replay_delay_seconds"]
    warning_replicas = 1 if _is_warning_lag(replay_delay_seconds) else 0
    critical_replicas = 1 if _is_critical_lag(replay_delay_seconds) else 0
    status = _status_for(warning_replicas, critical_replicas)

    return HealthCheckResult(
        name="Replication & WAL Health",
        status=status,
        summary=_replica_summary_for(status, replay_delay_seconds),
        metrics={
            "server_role": "replica",
            "is_in_recovery": True,
            "replicas_connected": None,
            "warning_replicas": warning_replicas,
            "critical_replicas": critical_replicas,
            "most_lagging_replica_application": None,
            "most_lagging_replica_client_addr": None,
            "most_lagging_replica_state": None,
            "most_lagging_replica_sync_state": None,
            "most_lagging_replay_lag_seconds": None,
            "last_wal_receive_lsn": replay["last_wal_receive_lsn"],
            "last_wal_replay_lsn": replay["last_wal_replay_lsn"],
            "last_xact_replay_timestamp": replay["last_xact_replay_timestamp"],
            "replay_delay_seconds": replay_delay_seconds,
            **wal_metrics,
        },
        recommendation=_replica_recommendation_for(status, replay_delay_seconds),
    )


def _replica_from_row(row: Any) -> dict[str, object]:
    """Return normalized primary-side replication row data."""
    return {
        "pid": _int_or_zero(row[0]),
        "application_name": row[1],
        "client_addr": str(row[2]) if row[2] is not None else None,
        "state": row[3],
        "sync_state": row[4],
        "sent_lsn": row[5],
        "write_lsn": row[6],
        "flush_lsn": row[7],
        "replay_lsn": row[8],
        "write_lag_seconds": _interval_seconds(row[9]),
        "flush_lag_seconds": _interval_seconds(row[10]),
        "replay_lag_seconds": _interval_seconds(row[11]),
    }


def _replay_from_row(row: tuple[object, ...] | None) -> dict[str, object]:
    """Return normalized replica-side replay data."""
    if row is None:
        return {
            "last_wal_receive_lsn": None,
            "last_wal_replay_lsn": None,
            "last_xact_replay_timestamp": None,
            "replay_delay_seconds": None,
        }

    return {
        "last_wal_receive_lsn": row[0],
        "last_wal_replay_lsn": row[1],
        "last_xact_replay_timestamp": row[2],
        "replay_delay_seconds": _float_or_none(row[3]),
    }


def _int_or_zero(value: object) -> int:
    """Return an integer metric value, treating NULL as zero."""
    if value is None:
        return 0
    return int(value)


def _float_or_none(value: object) -> float | None:
    """Return a float metric value, preserving NULL as None."""
    if value is None:
        return None
    return float(value)


def _interval_seconds(value: object) -> float | None:
    """Return interval-like values as seconds, preserving NULL."""
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return float(value)


def _has_warning_lag(replica: dict[str, object]) -> bool:
    """Return whether a connected replica has warning-level replay lag."""
    return _is_warning_lag(replica["replay_lag_seconds"])


def _has_critical_lag(replica: dict[str, object]) -> bool:
    """Return whether a connected replica has critical-level replay lag."""
    return _is_critical_lag(replica["replay_lag_seconds"])


def _is_warning_lag(lag_seconds: object) -> bool:
    """Return whether lag crosses the warning threshold only."""
    return (
        lag_seconds is not None
        and REPLICATION_LAG_WARNING_SECONDS <= float(lag_seconds)
        < REPLICATION_LAG_CRITICAL_SECONDS
    )


def _is_critical_lag(lag_seconds: object) -> bool:
    """Return whether lag crosses the critical threshold."""
    return (
        lag_seconds is not None
        and float(lag_seconds) >= REPLICATION_LAG_CRITICAL_SECONDS
    )


def _most_lagging_replica(
    replicas: list[dict[str, object]],
) -> dict[str, object] | None:
    """Return the connected replica with the highest known replay lag."""
    replicas_with_lag = [
        replica for replica in replicas if replica["replay_lag_seconds"] is not None
    ]
    if not replicas_with_lag:
        return replicas[0] if replicas else None
    return max(
        replicas_with_lag,
        key=lambda replica: float(replica["replay_lag_seconds"]),
    )


def _status_for(warning_replicas: int, critical_replicas: int) -> str:
    """Return health status from replication lag signals."""
    if critical_replicas > 0:
        return "critical"
    if warning_replicas > 0:
        return "warning"
    return "healthy"


def _primary_summary_for(
    status: str,
    replicas_connected: int,
    most_lagging_replica: dict[str, object] | None,
) -> str:
    """Return a concise primary-side replication summary."""
    if replicas_connected == 0:
        return "No streaming replica is currently connected."
    if status == "healthy":
        return (
            f"{replicas_connected} streaming replica(s) connected with healthy "
            "replay lag."
        )
    if most_lagging_replica is None:
        return "Streaming replica lag was detected."
    return (
        "Most lagging replica replay lag is "
        f"{most_lagging_replica['replay_lag_seconds']:.2f} seconds."
    )


def _replica_summary_for(status: str, replay_delay_seconds: object) -> str:
    """Return a concise replica-side replay summary."""
    if replay_delay_seconds is None:
        return "Replica replay delay is unavailable."
    if status == "healthy":
        return (
            "Replica replay delay is "
            f"{float(replay_delay_seconds):.2f} seconds."
        )
    return (
        "Replica replay delay has crossed a diagnostic threshold at "
        f"{float(replay_delay_seconds):.2f} seconds."
    )


def _primary_recommendation_for(status: str, replicas_connected: int) -> str:
    """Return an actionable primary-side replication recommendation."""
    wal_context = (
        "WAL counters are cumulative and provide context only; WAL volume "
        "depends on write workload, checkpoints, full-page images, bulk "
        "operations, replication, and backup or recovery behavior."
    )
    if replicas_connected == 0:
        return (
            "No streaming replica is currently connected. This is expected for "
            f"a standalone PostgreSQL environment. {wal_context}"
        )
    if status == "healthy":
        return (
            "Connected replica replay lag is below the default diagnostic "
            f"threshold. {wal_context}"
        )
    return (
        "Replication lag is present. Investigate network latency, replica "
        "resource pressure, long-running replay activity, storage performance, "
        "WAL generation rate, and replication slot behavior where relevant. "
        f"{wal_context}"
    )


def _replica_recommendation_for(
    status: str,
    replay_delay_seconds: object,
) -> str:
    """Return an actionable replica-side replay recommendation."""
    if replay_delay_seconds is None:
        return (
            "Replica replay timestamp is unavailable, so replay delay cannot be "
            "calculated. Verify replication state and WAL receiver activity. "
            "No automatic remediation was performed."
        )
    if status == "healthy":
        return (
            "Replica replay delay is below the default diagnostic threshold. "
            "WAL counters are cumulative and provide context only."
        )
    return (
        "Replica replay delay is elevated. Investigate network latency, replica "
        "resource pressure, long-running replay activity, storage performance, "
        "WAL generation rate, and replication slot behavior where relevant. "
        "Do not restart replication or modify slots automatically."
    )
