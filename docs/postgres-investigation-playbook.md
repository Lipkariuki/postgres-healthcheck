# PostgreSQL Investigation Playbook

Operational playbook for Technical Support Engineers investigating production PostgreSQL symptoms. This complements [postgres-support-cheatsheet.md](postgres-support-cheatsheet.md), which explains the concepts and metrics.

Do not diagnose PostgreSQL from the customer symptom alone. Start broad, gather evidence, then narrow.

```text
Customer symptom
      ↓
Establish scope and timing
      ↓
Broad health snapshot
      ↓
Identify abnormal signal
      ↓
Inspect relevant PostgreSQL subsystem
      ↓
Form hypothesis
      ↓
Gather supporting evidence
      ↓
Recommend safest appropriate action
      ↓
Verify improvement
```

Core method:

```text
Detect -> Explain -> Investigate -> Remediate carefully -> Verify
```

## 1. General Investigation Workflow

A report like "the database is slow" may mean expensive queries, lock contention, connection exhaustion, application pool behavior, table maintenance lag, excessive workload, replication lag, or infrastructure pressure.

Start with the repository's broad snapshot:

```bash
python3 backend/main.py
```

Use the check results as routing signals, not final diagnoses:

| Signal | Narrow Toward |
| --- | --- |
| Query Health warning/critical | Query patterns, plans, indexes, row estimates |
| Lock Health warning/critical | Blocked sessions, blockers, transaction state |
| Connection Health warning/critical | Pool behavior, session counts, `max_connections` |
| Transaction Health warning/critical | Long-running or idle-in-transaction sessions |
| Table Health warning/critical | Dead tuples, VACUUM, write churn, table size |
| Database Health warning/critical | Cache hits, rollbacks, temp files, deadlocks |
| Replication & WAL warning/critical | Replay lag, WAL pipeline, replica resources |

## 2. Incident: Application Requests Are Slow

### Customer Symptom

Examples: API latency increased, pages take seconds to load, database is reachable, requests eventually complete.

### Initial Investigation

Check Query Health first, then rule out locks, long transactions, connection pressure, and database-level signals. Do not assume "slow" means "missing index."

### Evidence

Use `pg_stat_statements` to compare frequency, average cost, worst case, and cumulative cost:

```text
Calls: 4,812
Mean execution time: 1840 ms
Maximum execution time: 4621 ms
Total execution time: 8,854,080 ms
```

The slow query pattern identifies what needs deeper inspection.

### Narrow Investigation

Where safe:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM orders
WHERE customer_id = 123;
```

`EXPLAIN ANALYZE` executes the statement. Use it carefully, especially with writes.

Inspect:

| Plan Evidence | Why It Matters |
| --- | --- |
| Seq Scan | May scan many rows when a selective index would help |
| Index Scan / Bitmap Scan | Check whether the expected index is used |
| estimated vs actual rows | Bad estimates can lead to poor plans |
| rows removed by filter | Large filtering after scan can indicate missing selectivity |
| buffer hits/reads | Shows memory vs storage access behavior |
| joins, sorts, aggregations | Common sources of expensive execution |

Example evidence:

```text
Seq Scan on orders
Rows Removed by Filter: 7,499,989
Rows returned: 11
Execution Time: ~1.8 seconds
```

### Hypothesis

If millions of rows are scanned to return a tiny result set and no suitable index exists, a missing or ineffective index is a strong hypothesis.

### Safe Recommendation

Do not automatically create an index. Confirm the query is representative, the predicate is common, table size justifies the index, and write/storage cost is acceptable. For production, discuss whether `CREATE INDEX CONCURRENTLY` is appropriate.

### Verify

Rerun the plan and compare access path, buffers, rows processed, and latency.

## 3. Incident: Application Requests Are Hanging

### Customer Symptom

Examples: requests wait 30-60 seconds, requests timeout, other functionality works, database remains reachable.

Differentiate slow execution from waiting:

```text
slow execution != blocked by another backend
```

### Initial Investigation

Check Lock Health, Transaction Health, `pg_stat_activity`, and `pg_blocking_pids()`.

Target chain:

```text
blocked PID -> blocker PID -> root blocking transaction
```

Example:

```text
Blocked sessions: 4
Blocking sessions: 1
Wait event: Lock / transactionid
Root blocker PID: 7991
Blocker state: idle in transaction
Transaction age: 18m
```

### Evidence SQL

```sql
SELECT
    pid,
    usename,
    application_name,
    state,
    xact_start,
    now() - xact_start AS transaction_age,
    wait_event_type,
    wait_event,
    LEFT(query, 150) AS query
FROM pg_stat_activity
WHERE pid = 7991;
```

### Narrow Investigation

Determine who owns the blocker, what transaction it opened, whether it is legitimate, why it remains open, and what it is blocking.

### Safe Recommendation

Do not immediately terminate the PID. Use:

```text
Find blocker -> understand blocker -> remediate
```

If the transaction is abandoned and intervention is justified, ending it releases locks. Backend termination may roll back work and disrupt users.

### Verify

Confirm the blocker disappeared, blocked sessions resumed, application latency recovered, and transaction lifecycle was corrected.

## 4. Incident: Database Connection Errors

### Customer Symptom

Examples: intermittent connection failures, some requests succeed, new requests fail, PostgreSQL remains reachable.

### Initial Investigation

Compare current connections, `max_connections`, active, idle, and idle-in-transaction counts.

```text
Connections: 96 / 100
Active: 8
Idle: 87
Idle in transaction: 1
```

This differs from 96 connections all doing useful work.

### Evidence SQL

```sql
SELECT
    usename,
    application_name,
    client_addr,
    state,
    COUNT(*) AS connections
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY usename, application_name, client_addr, state
ORDER BY connections DESC;
```

### Narrow Investigation

Inspect pool size, application instance count, connection lifecycle, leaked sessions, idle accumulation, timeout behavior, and pooler availability. Treat `idle in transaction` separately from ordinary `idle`.

In Supabase-related environments, account for Supavisor and the difference between direct and pooled database connections.

### Safe Recommendation

Do not immediately increase `max_connections`. That can postpone connection leaks, oversized pools, or poor lifecycle behavior while adding backend memory and scheduling overhead. Recommend pool/lifecycle correction first when evidence supports it.

### Verify

Observe utilization, error rate, and pool behavior after the application or pool configuration changes.

## 5. Incident: Database Storage Keeps Growing

### Customer Symptom

Examples: storage increases rapidly, little new business data was added, VACUUM completed, physical disk usage did not decrease.

### Initial Investigation

Check table sizes, index sizes, dead tuples, update/delete volume, autovacuum history, long-running transactions, and WAL context.

```text
orders table:   38 GB
orders indexes: 14 GB
Live tuples: 8,000,000
Dead tuples: 2,400,000
Updates: 42,000,000
```

### VACUUM Concept

```text
UPDATE / DELETE
      ↓
obsolete tuple versions
      ↓
VACUUM
      ↓
space becomes reusable
      ↓
table file normally does not shrink
```

Normal VACUUM primarily makes space reusable inside the relation. It does not normally return all reclaimed space to the operating system.

### Evidence SQL

```sql
SELECT
    pg_size_pretty(pg_relation_size('orders')) AS table_size,
    pg_size_pretty(pg_indexes_size('orders')) AS index_size,
    pg_size_pretty(pg_total_relation_size('orders')) AS total_size;
```

```sql
SELECT
    relname,
    n_live_tup,
    n_dead_tup,
    n_tup_upd,
    n_tup_hot_upd,
    last_vacuum,
    last_autovacuum,
    vacuum_count,
    autovacuum_count
FROM pg_stat_user_tables
WHERE relname = 'orders';
```

### Narrow Investigation

Investigate workload churn, autovacuum effectiveness, long-running transactions, dead tuple accumulation, HOT update ratio, index growth, and whether reclaimed space is being reused.

### VACUUM FULL Caution

`VACUUM FULL` can physically rewrite and compact a table, returning space to the operating system. It requires strong locking and can be disruptive for large tables. Do not recommend it automatically from dead tuple percentage.

### Verify

Determine whether growth stabilizes, reclaimed space is reused, autovacuum keeps pace, and physical reclamation is actually required.

## 6. Incident: High Database CPU

### Customer Symptom

Examples: database CPU stays near 90-95%, application still works, some endpoints slow down, memory appears normal.

### Key Distinction

Do not only rank by highest mean execution time. Compare per-execution latency with cumulative workload cost.

```text
Query A:
Calls: 18
Mean: 142 ms
Total: 2,556 ms

Query B:
Calls: 1,620,000
Mean: 0.74 ms
Total: 1,198,800 ms
```

Query A is individually slower. Query B consumed far more cumulative execution time and may matter more for sustained CPU.

### Narrow Investigation

Use `pg_stat_statements` to inspect calls, `total_exec_time`, `mean_exec_time`, and `max_exec_time`.

Ask:

| Question | Possible Direction |
| --- | --- |
| Why is it called so frequently? | N+1 query pattern, polling, chatty API |
| Can results be cached? | Application/cache-layer change |
| Can operations be batched? | Reduce repeated SQL calls |
| Is the plan efficient? | Indexes, joins, predicates, estimates |
| Are stats fresh? | Analyze/autovacuum/table stats |

### Safe Recommendation

Do not optimize solely by `mean_exec_time`. A fast query multiplied by enormous frequency can cost more than a slow query called rarely.

### Verify

Compare call volume, total execution time, latency, and CPU after the change.

## 7. Incident: Replica Is Serving Stale Data

### Customer Symptom

Examples: writes succeed on primary, replica reads are stale, replication is connected, lag increased suddenly.

### Initial Investigation

Check server role, replica state, sync state, sent/write/flush/replay LSNs, replay lag, and recent WAL generation.

```text
Server role: primary
Replicas connected: 1
State: streaming
Sync state: async
Replay lag: 46s
```

### Replication Pipeline

```text
Primary generates WAL
        ↓
sent_lsn
        ↓
write_lsn
        ↓
flush_lsn
        ↓
replay_lsn
        ↓
change visible on replica
```

Conceptual clues:

| Observation | Investigate |
| --- | --- |
| `sent_lsn` far ahead of `write_lsn` | network or receiving side |
| `flush_lsn` far ahead of `replay_lsn` | replay is falling behind |
| high recent WAL generation | write workload, batch jobs, maintenance |

Do not treat a large cumulative `wal_bytes` value as proof of the incident. The important question is whether WAL generation rate changed.

### Safe Recommendation

Do not automatically restart replication. Identify which stage is behind first. Investigate network latency, replica CPU, replica storage I/O, WAL generation rate, competing workload, and replication slot behavior.

### Verify

Confirm replay lag decreases and the replica catches up.

## 8. Symptom-To-Subsystem Quick Map

| Customer Symptom | First PostgreSQL Areas |
| --- | --- |
| Requests slow | Query Health, `pg_stat_statements`, execution plans |
| Requests hanging | Locks, transactions, `pg_stat_activity` |
| Connection errors | Connections, `max_connections`, application pools |
| Storage growing | Tables, dead tuples, VACUUM, indexes |
| High CPU | Query frequency, cumulative execution cost, plans |
| Stale replica | Replication lag, WAL pipeline, replica resources |

This is a starting map, not proof of root cause.

## 9. Evidence To Capture Before Escalation

Capture what applies:

| Evidence | Examples |
| --- | --- |
| Customer symptom | exact error, latency, stale reads, timeout |
| Timing | start time, ongoing or resolved, recurrence |
| Scope | affected endpoints, tenants, workloads |
| Environment | PostgreSQL version, primary/replica role |
| Health snapshot | output from `python3 backend/main.py` |
| Sessions | PID, `application_name`, user, client address |
| Transactions | age, state, query, idle-in-transaction status |
| Locks | blocked PID, blocker PID, wait event |
| Queries | query pattern, calls, mean/max/total execution time |
| Plans | access path, estimates vs actual, buffers |
| Storage | table/index size, dead tuple stats, update volume |
| Connections | current/max, active/idle, pool settings |
| Replication | state, sync state, LSN positions, replay lag |
| Change context | deployments, migrations, batch jobs, traffic spikes |

Escalate with evidence, not "Postgres seems slow."

## 10. Final Support Principles

1. Start broad, then narrow.
2. Customer symptoms are not diagnoses.
3. A metric needs workload and time context.
4. Cumulative statistics do not prove a current incident.
5. Identify blockers before terminating sessions.
6. Understand query workload before adding indexes.
7. Understand connection lifecycle before increasing `max_connections`.
8. Understand VACUUM semantics before recommending `VACUUM FULL`.
9. Understand where replication is lagging before restarting anything.
10. Verify the result after remediation.

Prominent rule:

```text
Detect
→ Explain
→ Investigate
→ Remediate carefully
→ Verify
```
