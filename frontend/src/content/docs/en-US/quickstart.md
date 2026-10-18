This path goes from a local checkout to the first persisted PDF report. Commands match the current repository configuration.

## 1. Prepare

You need:

- Python 3.12+ and `uv`
- Node.js and npm
- PostgreSQL

Create a database, then create `backend/.env` with at least:

~~~dotenv
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=your_database
~~~

A real model call also needs `DEEPSEEK_API_KEY`. If you do not want model calls, use the deterministic mode below.

## 2. Install, migrate, and start the backend

~~~powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
~~~

The backend defaults to `http://127.0.0.1:8000`. The application does not apply migrations automatically on startup.

## 3. Start the frontend

In another terminal:

~~~powershell
cd frontend
npm install
npm run dev
~~~

Open the Vite URL (default `http://localhost:5173`) and choose **Try Us**.

## 4. Complete the first test

1. Create a project with your test API base URL.
2. Paste an OpenAPI JSON document into AI Test Lab.
3. Analyze the spec and generate a test plan.
4. Review the scenarios, steps, assertions, and risk information.
5. Approve the plan. Only an approved plan can create a formal run.
6. Start the run and follow step/assertion/event status.
7. Wait for `passed`, `failed`, or `cancelled`.
8. Open the run report preview and choose **Generate & save PDF**.
9. Open **Test Reports** in the sidebar to view, download, or print it.

## 5. Verify from the command line

Backend tests use the isolated `aiata_c4_test` database:

~~~powershell
cd backend
$env:POSTGRES_DB = 'aiata_c4_test'
uv run pytest tests/ -q
~~~

Frontend:

~~~powershell
cd frontend
npm test
~~~

## Next

- [Projects and API specs](/learn/projects-and-specs)
- [AI Test Lab](/learn/ai-test-lab)
- [PDF reports](/learn/pdf-reports)
- [Troubleshooting](/learn/troubleshooting)