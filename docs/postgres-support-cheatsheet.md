# PostgreSQL Support Cheatsheet

Concise operational reference for Technical Support Engineers investigating PostgreSQL health signals.

Core rule: **Detect -> Explain -> Investigate.** Do not make destructive changes from one metric.

## 1. Connections

| Concept | What To Check |
| --- | --- |
| Current sessions | `pg_stat_activity` |
| Limit | `SHOW max_connections;` |
| Utilization | `current_connections / max_connections * 100` |
| `active` | Query is currently executing |
| `idle` | Session is connected but not currently running a query |
| `idle in transaction` | Transaction is open but no query is currently running |

Useful SQL:

```sql
SELECT
    COUNT(*) AS current_connections,
    COUNT(*) FILTER (WHERE state = 'active') AS active_connections,
    COUNT(*) FILTER (WHERE state = 'idle') AS idle_connections,
    COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction
FROM pg_stat_activity;

SHOW max_connections;
```

Idle connections are not automatically bad. They may be normal pooled connections waiting for work. Idle-in-transaction sessions deserve investigation because they can hold locks and keep old row versions visible.

Connection pools matter. A spike in sessions often means pool sizing, lifecycle behavior, retry storms, or leaked connections need review. Increasing `max_connections` is not automatically the fix because each backend consumes memory and scheduler resources.

## 2. Transactions

Transactions begin with `BEGIN` and end with `COMMIT` or `ROLLBACK`. `pg_stat_activity.xact_start` shows when the current transaction began.

Useful SQL:

```sql
SELECT
    pid,
    usename,
    application_name,
    state,
    now() - xact_start AS transaction_age,
    wait_event_type,
    wait_event,
    LEFT(query, 150) AS query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND pid <> pg_backend_pid()
ORDER BY xact_start;
```

Long-running transactions matter because PostgreSQL MVCC may need to preserve old row versions while a transaction can still see them. Consequences can include retained locks, delayed VACUUM cleanup, and table bloat.

`idle in transaction` is especially important: the application may have opened a transaction and stopped doing work without committing or rolling back.

Do not terminate a backend as the first action. First identify owner, application, query, transaction age, and business impact. Cancellation or termination may roll back work or disrupt user operations.

## 3. Locks

| Term | Meaning |
| --- | --- |
| Blocked session | Waiting for a lock so its query cannot continue |
| Blocker | Backend holding the conflicting lock |
| Root blocker | The upstream backend responsible for the blocking chain |
| `transactionid` wait | Often waiting on another transaction to finish |

Useful SQL:

```sql
SELECT
    blocked.pid AS blocked_pid,
    blocked.usename AS blocked_user,
    blocked.state AS blocked_state,
    blocked.wait_event_type,
    blocked.wait_event,
    now() - blocked.query_start AS blocked_for,
    LEFT(blocked.query, 150) AS blocked_query,
    blocker.pid AS blocker_pid,
    blocker.usename AS blocker_user,
    blocker.state AS blocker_state,
    now() - blocker.xact_start AS blocker_transaction_age,
    LEFT(blocker.query, 150) AS blocker_query
FROM pg_stat_activity blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocking_pid(pid)
    ON true
JOIN pg_stat_activity blocker
    ON blocker.pid = blocking_pid.pid
WHERE blocked.pid <> pg_backend_pid()
ORDER BY blocked.query_start;
```

Use `pg_locks` when you need lock object detail:

```sql
SELECT
    pid,
    locktype,
    mode,
    granted,
    relation::regclass,
    transactionid
FROM pg_locks
ORDER BY granted, pid;
```

Safe workflow: identify blocked PID -> identify blocker -> inspect blocker transaction age/query/application -> contact owner or application team -> only then consider cancel/terminate if impact justifies it.

## 4. Database Health

`pg_stat_database` gives cumulative database-level counters for the current database.

```sql
SELECT
    datname,
    xact_commit,
    xact_rollback,
    blks_read,
    blks_hit,
    temp_files,
    temp_bytes,
    deadlocks
FROM pg_stat_database
WHERE datname = current_database();
```

Cache hit ratio:

```text
blks_hit / (blks_hit + blks_read) * 100
```

Rollback ratio:

```text
xact_rollback / (xact_commit + xact_rollback) * 100
```

| Metric | Investigation Signal |
| --- | --- |
| Low cache hit ratio | More block requests reached storage instead of buffers |
| Elevated rollback ratio | Application errors, retries, or transaction lifecycle issues |
| `temp_files`, `temp_bytes` | Sort/hash/work operations may exceed available working memory |
| `deadlocks` | Historical deadlocks since stats reset |

Low cache hit ratio is not automatic proof of insufficient memory. Investigate workload behavior, query plans, table/index access patterns, memory configuration, and actual I/O behavior.

Important: these counters are cumulative since statistics were last reset. A historical deadlock count does not prove a deadlock is happening now.

## 5. Table / Vacuum Health

Use `pg_stat_user_tables` for user table maintenance signals.

```sql
SELECT
    schemaname,
    relname,
    n_live_tup,
    n_dead_tup,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_tup_hot_upd,
    last_autovacuum,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
```

Dead tuple ratio:

```text
n_dead_tup / (n_live_tup + n_dead_tup) * 100
```

Dead tuples exist because MVCC keeps old row versions after updates/deletes until they can be cleaned. VACUUM removes dead tuples when safe. Long-running transactions can prevent cleanup.

Context matters:

| Example | Interpretation |
| --- | --- |
| 2 dead tuples out of 3 rows | High ratio, tiny table, usually low operational risk |
| 1M dead tuples out of 2B rows | Large raw count, low ratio, needs size/workload context |

`last_autovacuum = NULL` does not prove autovacuum is broken. Small or new tables may not have crossed thresholds. A recent autovacuum also does not prove health if dead tuples remain high.

Approximate autovacuum trigger concept:

```text
autovacuum_vacuum_threshold +
autovacuum_vacuum_scale_factor * table tuples
```

Exact behavior depends on PostgreSQL version, table settings, global configuration, and workload.

HOT updates (`n_tup_hot_upd`) avoid some index churn when PostgreSQL can update a row without changing indexed columns and there is room on the page.

## 6. Index Health

Use `pg_stat_user_indexes` with catalog metadata.

```sql
SELECT
    s.schemaname,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    pg_relation_size(s.indexrelid) AS index_size_bytes,
    i.indisprimary AS is_primary,
    i.indisunique AS is_unique
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

Mental model:

| Signal | Priority |
| --- | --- |
| Large + zero scans + non-protected | Investigate |
| Small + zero scans | Usually low priority |
| PRIMARY/UNIQUE + zero scans | May still be essential for correctness |

Indexes improve reads for some queries but add write-maintenance and storage cost. `idx_scan = 0` does not mean `DROP INDEX`. The index may support rare critical queries, scheduled jobs, constraints, or stats may have been reset recently.

## 7. Query Performance

Use `pg_stat_statements` when enabled.

```sql
SELECT
    LEFT(query, 300) AS query,
    calls,
    total_exec_time,
    mean_exec_time,
    max_exec_time,
    rows
FROM pg_stat_statements
WHERE query NOT ILIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC;
```

Metric meanings:

| Metric | Meaning |
| --- | --- |
| `calls` | Execution frequency |
| `mean_exec_time` | Typical per-execution cost |
| `max_exec_time` | Worst recorded execution |
| `total_exec_time` | Cumulative database execution cost |
| normalized query text | Similar query shapes grouped together |

High calls + low mean can be normal and cheap. Low calls + high mean may indicate a rare but expensive workflow. Total execution time shows cumulative cost, but every workload has a top query.

`EXPLAIN` shows the plan without running the statement. `EXPLAIN ANALYZE` executes the statement and reports actual timing. Use `EXPLAIN ANALYZE` carefully, especially with writes; wrap write investigations in a transaction and roll back only when appropriate and approved.

## 8. WAL

Write-Ahead Logging (WAL) records changes before data pages are written. It supports durability, crash recovery, replication, and point-in-time recovery.

```sql
SELECT
    wal_records,
    wal_fpi,
    wal_bytes,
    wal_buffers_full,
    wal_write,
    wal_sync
FROM pg_stat_wal;
```

| Metric | Meaning |
| --- | --- |
| `wal_records` | WAL records generated |
| `wal_bytes` | WAL volume generated |
| `wal_fpi` | Full-page images written |
| `wal_buffers_full` | WAL buffers filled before being written |

WAL counters are cumulative. High `wal_bytes` alone is not proof of a problem. WAL volume depends on write workload, checkpoints, full-page images, bulk operations, replication, and backup/recovery behavior.

## 9. Replication

Role detection:

```sql
SELECT pg_is_in_recovery();
```

| Result | Role |
| --- | --- |
| `false` | Primary / writable server |
| `true` | Standby / replica |

Primary-side replication:

```sql
SELECT
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
```

Concepts:

| Stage | Meaning |
| --- | --- |
| sent | WAL sent from primary |
| write | Replica wrote WAL locally |
| flush | Replica flushed WAL to durable storage |
| replay | Replica applied WAL changes |

Asynchronous replication can lag without blocking primary commits. Synchronous replication can wait for configured replica acknowledgement, trading latency for stronger durability semantics.

Zero replicas can be perfectly healthy for a standalone deployment. Common lag causes include network latency, replica CPU/I/O pressure, long-running replay activity, high WAL generation rate, and replication slot retention behavior.

Replica-side checks:

```sql
SELECT
    pg_last_wal_receive_lsn(),
    pg_last_wal_replay_lsn(),
    pg_last_xact_replay_timestamp(),
    now() - pg_last_xact_replay_timestamp() AS replay_delay;
```

## 10. Extensions

Two separate concepts:

| Concept | Scope | Example |
| --- | --- | --- |
| `shared_preload_libraries` | Server-level library loading where required | load `pg_stat_statements` at server start |
| `CREATE EXTENSION` | Database-level extension objects | enable `pg_stat_statements` views/functions in one database |

For `pg_stat_statements`, the library usually must be preloaded, then the extension must exist in the database being inspected.

```sql
SHOW shared_preload_libraries;

SELECT extname
FROM pg_extension
WHERE extname = 'pg_stat_statements';
```

## 11. Support Engineer Golden Rules

| Rule | Meaning |
| --- | --- |
| Metric != diagnosis | A number starts investigation; it does not finish it |
| Cumulative statistic != current incident | Check whether counters are historical |
| Correlation != causation | Related timing is not proof |
| High value != automatically unhealthy | Context, size, workload, and time window matter |
| Zero value != automatically healthy | Missing stats or reset counters can hide issues |
| Detect -> Explain -> Investigate | State what was found, why it matters, and what to check next |

Never recommend destructive remediation solely from one metric.

## 12. Quick Incident Map

| Symptom | First Places To Investigate |
| --- | --- |
| Application hanging | Locks, transactions, connections |
| Connection errors | `pg_stat_activity`, `max_connections`, pool settings |
| Slow requests | `pg_stat_statements`, `EXPLAIN`, plans |
| Storage growth | Dead tuples, indexes, WAL, table sizes |
| High DB CPU | Query workload, plans, call volume, expensive queries |
| Replica behind | `pg_stat_replication`, replay lag, WAL generation, replica resources |

