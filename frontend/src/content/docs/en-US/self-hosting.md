## Components

ApiPilot has two local applications:

- `frontend/`: Vue 3 console, served by Vite during development.
- `backend/`: FastAPI service with async SQLAlchemy and PostgreSQL.

Default development addresses:

| Component | Default |
|---|---|
| Frontend | `http://localhost:5173` |
| Backend | `http://127.0.0.1:8000` |

## Database

Create an empty PostgreSQL database first. ApiPilot does not create databases for you and does not run migrations automatically on startup.

Backend connection variables:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

Put real values in `backend/.env` and never commit that file.

## Backend install and start

~~~powershell
cd backend
uv sync
uv run alembic upgrade head
uv run alembic current
uv run uvicorn main:app --reload
~~~

For a new database, run all migrations. For an existing database, back it up and check the current revision before running `upgrade head`.

## Frontend install and start

~~~powershell
cd frontend
npm install
npm run dev
~~~

If the frontend runs on a different origin:

1. Set `VITE_API_BASE_URL` to the backend.
2. Add the exact frontend origin to the backend `CORS_ALLOW_ORIGINS`.
3. Restart the affected process.

## Updating an existing deployment

1. Pull the code and review new migrations.
2. Run `uv sync` and `uv run alembic upgrade head` in the backend.
3. Restart the backend.
4. Run `npm install` and rebuild or restart the frontend.

There is no Docker or CI pipeline yet, so updates are manual.

## Tests

Tests require a separate database. Do not point them at your development data:

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run pytest tests/ -q
~~~

See [Configuration](/learn/configuration) for variables and [Troubleshooting](/learn/troubleshooting) for startup failures.