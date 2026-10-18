## Where configuration lives

The backend reads `backend/.env`. Alembic imports the same database configuration, so there is no second connection string to maintain.

The frontend uses Vite environment variables. You can put them in `frontend/.env` or in the shell.

Never commit real keys, database passwords, or tokens.

## Database variables

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_HOST` | `127.0.0.1` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | none | Database user |
| `POSTGRES_PASSWORD` | none | Database password |
| `POSTGRES_DB` | none | Target database |

These names come from `backend/src/backend/db/database.py`.

## Model variables

Real model calls are optional:

| Variable | Default | Purpose |
|---|---|---|
| `DEEPSEEK_API_KEY` | none | API key; never commit |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Model endpoint |
| `DEEPSEEK_MODEL` | client default | Model name |

For a fully offline, deterministic path:

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

The default automated test suite does not call the live model; live tests are opt-in.

## Frontend and CORS

The frontend calls `http://127.0.0.1:8000` by default. The backend allows these development origins by default:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

If you use another port:

~~~dotenv
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
~~~

~~~powershell
$env:CORS_ALLOW_ORIGINS = 'http://localhost:5174'
~~~

Restart the affected process after changing environment variables.

## Report configuration

PDF reports use the PostgreSQL table `run_reports`, created by migration `c33a1b2c3d4e`. PDF bytes are stored in the database, not in a local file directory.

## Test environment

Backend test fixtures force the `aiata_c4_test` database. Make sure that database exists and is migrated, and never point it at development data.