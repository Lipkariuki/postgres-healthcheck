# PostgreSQL Health Check

A lightweight PostgreSQL diagnostic tool for identifying database health issues and surfacing actionable troubleshooting information.

The project is designed around a common production support problem: **when PostgreSQL appears slow or unhealthy, where do you start?**

Rather than immediately digging through multiple system views manually, PostgreSQL Health Check provides focused checks that can be run against a database to quickly understand its current state.

## Why This Project?

Database incidents often begin with vague symptoms:

* "The application is slow."
* "Requests are timing out."
* "The database has too many connections."
* "Something is consuming all available connections."
* "Postgres looks unhealthy."

The challenge for a support engineer is turning those symptoms into useful evidence.

This project explores how PostgreSQL exposes operational information through its system views and how that information can be turned into practical health checks.

The initial implementation focuses on **connection health**, with additional PostgreSQL diagnostics planned as the project evolves.

## Current Capabilities

### Connection Health

The tool inspects PostgreSQL connection activity and reports information that can help identify connection pressure.

This provides a starting point for investigating problems such as:

* connection exhaustion
* unexpectedly high database activity
* application connection leaks
* idle connection accumulation
* workloads approaching PostgreSQL connection limits

The implementation is intentionally modular so additional diagnostic checks can be added independently.

## Architecture

```text
                     PostgreSQL
                         │
                         │ SQL / system views
                         ▼
                ┌─────────────────┐
                │ Database Layer  │
                │  database.py    │
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
                │   Application   │
                │     main.py     │
                └─────────────────┘
```

The project separates database connectivity, diagnostic logic, and health result models so new checks can be introduced without tightly coupling them to the application entry point.

## Project Structure

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
│   ├── requirements.txt
│   └── .env.example
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

## Getting Started

### Prerequisites

You will need:

* Python 3
* PostgreSQL
* Docker and Docker Compose, if using the included local database environment

## 1. Clone the Repository

```bash
git clone git@github.com:Lipkariuki/postgres-healthcheck.git
cd postgres-healthcheck
```

## 2. Create a Python Virtual Environment

```bash
python3 -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install the Python dependencies:

```bash
pip install -r backend/requirements.txt
```

## 3. Configure the Environment

Copy the example environment configuration:

```bash
cp .env.example .env
```

Update the values in `.env` for your PostgreSQL environment.

Never commit real database credentials to the repository.

## 4. Start PostgreSQL with Docker

The repository includes a Docker Compose configuration for running a local PostgreSQL environment.

```bash
docker compose up -d
```

Check that the container is running:

```bash
docker compose ps
```

To inspect its logs:

```bash
docker compose logs
```

To stop the environment:

```bash
docker compose down
```

## 5. Run the Health Check

From the repository root:

```bash
python3 backend/main.py
```

The application connects to PostgreSQL using the configured environment and executes the available health checks.

## Running Tests

Run the test suite with:

```bash
pytest
```

Or run the connection health tests directly:

```bash
pytest tests/test_connection_health.py -v
```

Tests are used to validate the diagnostic logic independently from manual database investigation.

## PostgreSQL Concepts Explored

This project is also a practical environment for learning PostgreSQL internals and production troubleshooting.

Areas explored include:

**Connections**

Understanding how clients consume PostgreSQL connections and how connection pressure can affect application availability.

**PostgreSQL system views**

Using PostgreSQL's built-in operational information to investigate database behaviour rather than treating the database as a black box.

**Health thresholds**

Turning raw database statistics into understandable states that can help an engineer decide whether further investigation is necessary.

**Troubleshooting methodology**

Moving from:

```text
Application symptom
        ↓
Database evidence
        ↓
Health check
        ↓
Diagnosis
        ↓
Recommended investigation
```

This mirrors the type of reasoning required during production incidents.

## Roadmap

The current connection check is the foundation for a broader PostgreSQL diagnostic toolkit.

Planned areas of exploration include:

* [x] PostgreSQL connectivity
* [x] Connection health checks
* [x] Automated tests
* [x] Docker-based local PostgreSQL environment
* [ ] Long-running query detection
* [ ] Lock and blocking-session detection
* [ ] Database size monitoring
* [ ] Table and index health
* [ ] Cache and memory-related statistics
* [ ] Transaction health
* [ ] Vacuum and dead tuple diagnostics
* [ ] Replication health
* [ ] Structured CLI output
* [ ] Diagnostic recommendations

The goal is not to replace full observability platforms, but to understand and automate the PostgreSQL investigation techniques that engineers use when diagnosing database incidents.

## Example Troubleshooting Scenario

Consider an application that begins returning intermittent database connection errors.

A typical investigation might ask:

1. Can the application reach PostgreSQL?
2. How many connections currently exist?
3. What is the configured connection limit?
4. How close is the database to that limit?
5. Are connections active or idle?
6. Is one application or user responsible for unusual connection usage?

A health check can automate the first layer of this investigation and surface evidence for deeper troubleshooting.

## Security

Database credentials should always be supplied through environment variables.

The repository intentionally includes `.env.example` files containing configuration templates rather than real credentials.

Before committing changes, verify that secrets are not tracked:

```bash
git status
git ls-files .env
```

Production databases should also be accessed using appropriately restricted PostgreSQL roles rather than administrative credentials whenever possible.

## Learning Goals

This project is being built as a hands-on exploration of:

* PostgreSQL administration
* database troubleshooting
* production support engineering
* Python automation
* testing diagnostic logic
* incident investigation
* observability fundamentals

The emphasis is on understanding **why a PostgreSQL system becomes unhealthy and how an engineer can prove the cause using database evidence**.

## Contributing

This project is primarily a learning and experimentation environment, but suggestions and improvements are welcome.

If you find an issue or have an idea for another PostgreSQL health check, feel free to open an issue or submit a pull request.

## License

This project is intended for educational and experimental use.
