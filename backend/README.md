# PostgreSQL Health Check Backend

Simple Python CLI tool that verifies a PostgreSQL connection using environment
variables.

## Requirements

- Python 3.12
- PostgreSQL reachable from your machine

## Setup

```bash
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Update `.env` with your PostgreSQL connection details:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=healthcheck_db
DB_USER=postgres
DB_PASSWORD=postgres
```

## Run

```bash
python backend/main.py
```

Successful connection:

```text
✅ Connected to PostgreSQL
```

Failed connection:

```text
❌ Unable to connect:
<reason>
```
