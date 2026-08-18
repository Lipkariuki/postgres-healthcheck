# PostgreSQL Health Check

A lightweight, support-engineering-focused PostgreSQL diagnostic tool that turns PostgreSQL system statistics into **actionable health findings**.

The project is built around a simple production question:

> **When PostgreSQL appears slow or unhealthy, where should an engineer start investigating?**

Instead of manually querying multiple system views and interpreting raw metrics, PostgreSQL Health Check aims to provide focused diagnostics, explain why a finding matters, and suggest the next investigation step.

---

# Why This Project?

Database incidents rarely begin with a clear root cause.

They usually start with symptoms such as:

* "The application is slow."
* "Requests are timing out."
* "The database has too many connections."
* "PostgreSQL is refusing new clients."
* "The database looks healthy, but users are still experiencing latency."

The challenge for a Support Engineer is turning those symptoms into evidence.

PostgreSQL already exposes a large amount of operational information through views such as:

```sql
pg_stat_activity
pg_stat_database
pg_stat_user_tables
pg_stat_user_indexes
pg_stat_statements
pg_locks
```

The goal of this project is to turn that raw information into a practical troubleshooting workflow.

```text
Application symptom
        │
        ▼
PostgreSQL statistics
        │
        ▼
Health check
        │
        ▼
Finding
        │
        ▼
Recommended investigation
```

---

# Current Capabilities

## Connection Health

The first implemented health check analyzes PostgreSQL connection usage using `pg_stat_activity` and the configured `max_connections`.

It currently reports:

* Current PostgreSQL connections
* Maximum configured connections
* Connection utilization percentage
* Active connections
* Idle connections
* Idle-in-transaction sessions
* Oldest idle-in-transaction session
* Health status
* Actionable recommendations

Example:

```text
✅ Connected to PostgreSQL

Connection Health
Status: healthy
Connections: 11 / 100
Utilization: 11.0%
Active: 1
Idle: 4
Idle in transaction: 1

Recommendation:
Connection capacity is healthy.

Urgent: the oldest idle-in-transaction session has been open for
361801 seconds.

Investigate the session owner and application behavior.

Long-lived open transactions can retain locks, prevent VACUUM from
reclaiming obsolete tuple versions, and contribute to table bloat.
```

This demonstrates an important design principle of the project:

> **A healthy headline metric does not necessarily mean the database has nothing worth investigating.**

Connection utilization may be low while a long-running transaction still presents operational risk.

---

# Health Check Philosophy

The tool follows three principles.

## Detect

Identify potentially important PostgreSQL conditions.

Example:

```text
Idle in transaction: 1
```

## Explain

Describe why the condition matters.

Example:

```text
Long-running transactions may retain locks and prevent VACUUM
from reclaiming obsolete tuples.
```

## Guide

Recommend the next investigation rather than automatically making changes.

Example:

```text
Investigate the owning application and transaction before
considering termination.
```

The tool intentionally avoids destructive automatic remediation.

---

# Connection Health Thresholds

The initial connection-utilization thresholds are:

| Utilization | Status   |
| ----------- | -------- |
| Below 70%   | Healthy  |
| 70% to 90%  | Warning  |
| Above 90%   | Critical |

These are application-level defaults, not universal PostgreSQL rules.

Different environments have different workloads and capacity requirements. Future versions will make health thresholds configurable.

---

# Architecture

```text
                     PostgreSQL
                         │
                         │ SQL / system views
                         ▼
                ┌─────────────────┐
                │ Database Layer  │
                │   database.py   │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │  Health Checks  │
                │                 │
                │ connections.py  │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │ Health Models   │
                │    health.py    │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │      CLI        │
                │     main.py     │
                └─────────────────┘
```

Database connectivity, diagnostic logic, result models, and presentation are kept separate so additional checks can be added without tightly coupling the application.

Each future diagnostic module will follow the same general pattern:

```text
Run SQL
   │
   ▼
Collect metrics
   │
   ▼
Evaluate health
   │
   ▼
Explain finding
   │
   ▼
Recommend next step
```

---

# Project Structure

```text
postgres-healthcheck/
│
├── backend/
│   ├── checks/
│   │   ├── __init__.py
│   │   └── connections.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── health.py
│   │
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── requirements.txt
│
├── database/
│   └── init.sql
│
├── tests/
│   └── test_connection_health.py
│
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

---

# Local PostgreSQL Lab

The repository includes a Docker-based PostgreSQL environment for safely reproducing database conditions.

This makes it possible to deliberately create scenarios such as:

* Idle-in-transaction sessions
* Long-running transactions
* Lock contention
* Connection pressure
* Slow queries
* Missing indexes
* Sequential scans
* Autovacuum activity

The lab allows each health check to be validated against a real PostgreSQL condition rather than relying only on mocked test data.

```text
Create PostgreSQL condition
            │
            ▼
Observe it manually
            │
            ▼
Run PostgreSQL Health Check
            │
            ▼
Verify detection
```

---

# Getting Started

## Prerequisites

You will need:

* Python 3
* Docker Desktop
* Docker Compose
* Git

A standalone PostgreSQL installation is not required when using the included Docker environment.

---

# 1. Clone the Repository

```bash
git clone https://github.com/Lipkariuki/postgres-healthcheck.git
cd postgres-healthcheck
```

---

# 2. Create a Python Virtual Environment

```bash
python3 -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r backend/requirements.txt
```

---

# 3. Configure the Environment

Copy the example configuration:

```bash
cp .env.example .env
```

The local Docker lab uses values similar to:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=healthcheck_db
DB_USER=postgres
DB_PASSWORD=postgres
```

Never commit real database credentials.

---

# 4. Start PostgreSQL

Start the local environment:

```bash
docker compose up -d
```

Check its status:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs
```

Stop PostgreSQL:

```bash
docker compose down
```

The included initialization SQL creates sample tables used by future health-check scenarios.

---

# 5. Run the Health Check

From the repository root:

```bash
python3 backend/main.py
```

Expected connection output:

```text
✅ Connected to PostgreSQL
```

The available health checks will then run against the configured database.

---

# Running Tests

The current test suite uses Python's built-in `unittest` framework.

Run all tests:

```bash
python3 -m unittest discover -s tests -v
```

Run the connection-health tests directly:

```bash
python3 -m unittest tests.test_connection_health -v
```

Tests validate diagnostic behavior independently of the Docker PostgreSQL environment.

Current test coverage includes:

* Healthy connection utilization
* Warning utilization
* Critical utilization
* Idle-in-transaction detection
* Empty idle-transaction state
* Urgent long-running idle transaction recommendations

---

# PostgreSQL Concepts Used

## `pg_stat_activity`

Used to understand what PostgreSQL sessions are doing right now.

Important states include:

```text
active
idle
idle in transaction
idle in transaction (aborted)
```

The current connection module uses this view to identify active, idle, and open transactional sessions.

---

## `max_connections`

Defines the configured PostgreSQL connection limit.

The tool compares current connections against this value to calculate utilization.

---

## Long-Running Transactions

An idle-in-transaction session may appear harmless because no SQL is currently running.

However, a transaction left open for a long period can:

* Retain locks
* Prevent VACUUM from reclaiming obsolete tuple versions
* Increase table bloat
* Interfere with database maintenance

This is why the tool evaluates more than connection percentage alone.

---

# Development Approach

The project is intentionally being developed one diagnostic module at a time.

Each feature follows this workflow:

```text
Understand the PostgreSQL problem
            │
            ▼
Design the investigation
            │
            ▼
Write and validate the SQL
            │
            ▼
Implement the health check
            │
            ▼
Write automated tests
            │
            ▼
Create the condition in the Docker lab
            │
            ▼
Verify end-to-end detection
```

The objective is not simply to build a dashboard.

The objective is to encode a repeatable **Support Engineer troubleshooting methodology**.

---

# Roadmap

## Foundation

* [x] PostgreSQL connectivity
* [x] Environment configuration
* [x] Docker-based PostgreSQL lab
* [x] Shared health-result model
* [x] Automated tests

## Connection Diagnostics

* [x] Current connection count
* [x] `max_connections` utilization
* [x] Active connection count
* [x] Idle connection count
* [x] Idle-in-transaction detection
* [x] Oldest idle transaction detection
* [x] Actionable connection recommendations
* [ ] Connection usage by application
* [ ] Connection usage by database user
* [ ] Connection-pool awareness

## Transaction & Lock Health

* [ ] Long-running transaction detection
* [ ] Blocking session detection
* [ ] Lock contention analysis
* [ ] Deadlock-related diagnostics

## Database Health

* [ ] Cache hit ratio
* [ ] Commit / rollback analysis
* [ ] Temporary file usage
* [ ] Database-size overview

## Table & Maintenance Health

* [ ] Live and dead tuple analysis
* [ ] Autovacuum health
* [ ] Vacuum progress
* [ ] Analyze freshness
* [ ] Table-size analysis
* [ ] Bloat indicators

## Index Health

* [ ] Index usage
* [ ] Large unused-index review
* [ ] Index-size analysis
* [ ] Sequential vs index scan analysis

## Query Performance

* [ ] `pg_stat_statements` integration
* [ ] Top cumulative query time
* [ ] Mean and maximum execution-time analysis
* [ ] Query-plan investigation guidance

## WAL & Replication

* [ ] WAL health
* [ ] WAL growth indicators
* [ ] Replication status
* [ ] Replica lag analysis
* [ ] Replication-slot health

## User Experience

* [ ] Structured JSON output
* [ ] Configurable thresholds
* [ ] Rich CLI output
* [ ] Exportable diagnostic report
* [ ] Web dashboard

---

# Example Troubleshooting Workflow

A customer reports:

> "The application cannot consistently connect to PostgreSQL."

A Support Engineer may ask:

```text
Can PostgreSQL be reached?
        │
        ▼
How many connections exist?
        │
        ▼
What is max_connections?
        │
        ▼
How close are we to the limit?
        │
        ▼
Are sessions active or idle?
        │
        ▼
Are transactions being left open?
        │
        ▼
Is connection pooling being used?
        │
        ▼
Which application owns the sessions?
```

PostgreSQL Health Check aims to automate the first layer of that investigation and surface the evidence required for deeper troubleshooting.

---

# Security

Database credentials should always be supplied through environment variables.

The repository contains:

```text
.env.example
```

for configuration examples.

The real:

```text
.env
```

must remain untracked.

Before committing changes, verify:

```bash
git status
git ls-files .env
```

The second command should return no tracked `.env` file.

For production environments, use an appropriately restricted PostgreSQL monitoring role whenever possible rather than administrative credentials.

The tool is designed to **observe and recommend**, not automatically modify production databases.

---

# Project Goals

This project is designed to demonstrate and deepen practical experience in:

* PostgreSQL internals
* Database troubleshooting
* Production Support Engineering
* Query-performance investigation
* Python automation
* Testing diagnostic logic
* Incident investigation
* Observability fundamentals
* Developer tooling

The central principle is:

> **Do not guess why PostgreSQL is unhealthy. Gather evidence, understand the condition, and recommend the next investigation step.**

---

# Contributing

Suggestions, bug reports, and ideas for additional PostgreSQL health checks are welcome.

If you have an investigation pattern that could be useful to other Support Engineers, feel free to open an issue or submit a pull request.

---

# Project Status

🚧 **Active development**

The current release establishes the diagnostic architecture and implements connection-health analysis.

Additional PostgreSQL health checks are being added incrementally and validated against reproducible scenarios in the included Docker lab.
