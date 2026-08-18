# PostgreSQL Health Check

Local PostgreSQL lab and Python health check tool for developing database
diagnostics.

## Prerequisites

- Docker Desktop installed
- Docker Compose available
- Python 3.12

## Setup Python

```bash
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

## Start Database

```bash
docker compose up -d
```

PostgreSQL runs in a container named `pg-health-lab` on port `5432`.

## Stop Database

```bash
docker compose down
```

Database data is persisted in the Docker volume `pg_health_lab_data`.

## Verify Container

```bash
docker ps
```

The container should show as healthy after PostgreSQL is ready.

## Connect Using psql

```bash
psql "host=localhost port=5432 dbname=healthcheck_db user=postgres password=postgres"
```

If you prefer connecting through the running container:

```bash
docker exec -it pg-health-lab psql -U postgres -d healthcheck_db
```

## Connect Using DBeaver

- Host: `localhost`
- Port: `5432`
- Database: `healthcheck_db`
- Username: `postgres`
- Password: `postgres`

## Verify Python Connection

```bash
source backend/.venv/bin/activate
python backend/main.py
```

Expected output:

```text
✅ Connected to PostgreSQL
```
