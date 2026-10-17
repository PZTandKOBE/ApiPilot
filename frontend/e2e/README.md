# Browser E2E (Phase 10.2)

A real Chrome, a real Vite dev server and a real FastAPI backend, driven over the
Chrome DevTools Protocol. No browser-automation dependency is installed: Node 24
ships `fetch` and a global `WebSocket`, which is all the protocol needs.

## Run

```powershell
cd frontend
node e2e/run-core-flow.mjs
```

Requires, and checks for:
- Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe` (override with `E2E_CHROME`).
- `backend/.venv/Scripts/python.exe` (override with `E2E_PYTHON`).
- A PostgreSQL database named `aiata_c4_test`; the backend child is started with
  `POSTGRES_DB=aiata_c4_test`, and the script refuses to run if `current_database()`
  says anything else.

Ports are allocated by the OS, so the run never collides with a dev server you
already have open. The frontend origin is passed to the backend as
`CORS_ALLOW_ORIGINS` — required, because the browser must be able to read the
guest-session response.

## What it drives

1. Guest session bootstrap (the browser must be able to *read* the 201).
2. Project creation, with the base URL pointing at the in-process target API.
3. The AI Test Lab: the synthetic Orders OpenAPI document is pasted into the
   product's own paste box and analysed.

## Boundaries

- The target API is a Node `http` server inside this process: it records every
  request and can park one, which is what makes "the run was still active when the
  browser had events" a fact rather than a claim.
- The planner runs with `AGENT_ANALYZER=deterministic` and `AGENT_PLANNER=deterministic`.
  No API key, no network, no model spend.
- Cleanup happens in a `finally`: servers closed, children terminated (SIGTERM,
  then SIGKILL only as a logged fallback), Chrome profile removed, and the rows this
  run created deleted from `aiata_c4_test` only.
