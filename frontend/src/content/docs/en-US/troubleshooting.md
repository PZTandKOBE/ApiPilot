## Startup failure or blank page

Check:

1. The backend is running, default `http://127.0.0.1:8000`.
2. Browser console/network shows no CORS error.
3. `VITE_API_BASE_URL` points at the actual backend.
4. Backend `CORS_ALLOW_ORIGINS` includes the actual frontend origin.

Restart the affected process after changing environment variables.

## The database table does not exist

A typical error:

~~~text
UndefinedTableError: relation "run_reports" does not exist
~~~

The application database is missing the latest migration. From `backend/`:

~~~powershell
uv run alembic current
uv run alembic upgrade head
~~~

Do not create the table manually to bypass Alembic. Confirm `alembic current` matches `alembic heads`.

## Model call failure

- Confirm `DEEPSEEK_API_KEY` is set (never print or commit it).
- Check `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL`.
- For local validation without a model:

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

- Check network/proxy access to the provider.

## Plan generation failure

- A normal first-time generation refuses when a plan already exists; use the UI’s explicit regeneration flow.
- Check the spec is valid JSON and contains enough endpoint information.
- Inspect the task error; do not mask a reproducible failure by resubmitting.

## Run failure

- Read the first failed step and its assertion.
- Check the target API is reachable and the Base URL is correct.
- Check whether extract variables were produced; a missing variable fails before the request.
- Request/response bodies are not normally persisted, so history only shows saved evidence.

## PDF save failure

- Confirm the run is terminal; a running run is refused.
- Confirm the migration is applied to the actual application database.
- Read the backend error; a failed generation must not leave a successful report.
- Do not patch `run_reports` rows manually.

## Typecheck failure

The frontend has a known existing type error:

~~~text
ConsoleLayout.vue(114,10): TS18047
~~~

It is separate from test failures. `npm test` can still validate behavior.

## Still stuck

Collect the command, exit code, error envelope/stack (without secrets), database revision, and reproduction steps. Never commit `.env`.