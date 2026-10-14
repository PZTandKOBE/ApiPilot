"""End-to-end verification of the Run Executor (Phase 7.3).

The same shape as the other ``verify_*.py`` scripts -- a real PostgreSQL, the real
ASGI app, the real exception handlers, runs created by the real create endpoint --
with one addition the executor needs: a **real HTTP server** for it to call.

Nothing here mocks ``httpx``.  A stdlib ``ThreadingHTTPServer` listens on the
loopback interface, the probe project's environment points at it, and every
request the executor makes is a real TCP request to a real server that records
what it received -- which is how "the step substituted the runtime variable"
and "the step never sent anything" are provable rather than assumed.

Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_run_executor.py

It writes a project of its own (``prj_verify_executor``), reads it, and deletes it
again -- including on failure.  It does not touch any other project's rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_verify_executor"
ENVIRONMENT_PUBLIC_ID = "env_verify_executor"

GUEST_TOKEN = "run-executor-guest-session"
# The fixture inserts the digest the service computes for the token it names:
# the plaintext column is gone (Phase 8.5 Step 2), and these rows are ownership
# anchors for the fixture -- no business route reads an identity yet.
GUEST_TOKEN_HASH = hashlib.sha256(GUEST_TOKEN.encode("utf-8")).hexdigest()

# Every request this suite makes carries the fixture guest's token: the
# business routes verify a guest session (Phase 8.5 Step 3), and a suite that
# sent nothing would be measuring 401s.
GUEST_HEADERS = {"X-Guest-Session": GUEST_TOKEN}
"""Reused from ``seed_dev_data.py``: a project needs an owner and there is no
auth yet.  Created here if the seed has not been run."""

SPEC_TITLE = "Verify Executor API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Executor API","version":"1.0.0"},'
    '"paths":{"/ok":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

ENV_SECRET_NAME = "verify_secret"
ENV_SECRET_VALUE = "s3cr3t-executor-do-not-store"
ENV_TOKEN_NAME = "bearer_token"
ENV_TOKEN_VALUE = "env-bearer-token-value"
EXTRACTED_VALUE = "abc123"
"""The runtime value ``GET /ok`` returns as ``token`` and the extract step lifts."""

"""The bearer rule in the environment stores the *template* ``{{bearer_token}}``,
so ``GET /auth`` answering 200 proves two things at once: the rule built a header,
and the header was resolved from a variable whose value is nowhere in the
database."""

TERMINAL = ("passed", "failed", "cancelled")


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: Any = None) -> None:
        if condition:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail is not None else ""))

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected {expected!r}, got {actual!r}")


# --------------------------------------------------------------------------- #
# The API under test -- a real server on the loopback interface
# --------------------------------------------------------------------------- #

HITS: dict[str, int] = {}
LAST_ORDER_ID: dict[str, str] = {}
METHOD_BODY_LENGTH: dict[str, int] = {}
"""What each verb last arrived with: v1 sends no body, and that is a fact to check."""

SLOW_SECONDS = 2.0
"""Long enough that a cancel lands while the request is in flight."""


class _TargetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - silence the default log
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mutating(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path
        HITS[path] = HITS.get(path, 0) + 1
        METHOD_BODY_LENGTH[method] = len(body)
        self._send(200, {"method": method, "bodyLength": len(body)})

    def do_POST(self) -> None:  # noqa: N802 - the name is the stdlib's
        self._mutating("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._mutating("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._mutating("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._mutating("DELETE")

    def do_GET(self) -> None:  # noqa: N802 - the name is the stdlib's
        path = urlsplit(self.path).path
        HITS[path] = HITS.get(path, 0) + 1

        if path == "/ok":
            self._send(200, {"token": EXTRACTED_VALUE, "data": {"token": "nested-token"}})
        elif path == "/server-error":
            self._send(500, {"error": "boom"})
        elif path.startswith("/orders/"):
            LAST_ORDER_ID["value"] = path.rsplit("/", 1)[-1]
            self._send(200, {"order_id": LAST_ORDER_ID["value"], "status": "open"})
        elif path == "/auth":
            sent = self.headers.get("Authorization", "")
            if sent == "Bearer " + ENV_TOKEN_VALUE:
                self._send(200, {"authenticated": True})
            else:
                self._send(401, {"authenticated": False})
        elif path == "/slow":
            time.sleep(SLOW_SECONDS)
            self._send(200, {"slept": True})
        else:
            self._send(404, {"error": "not found"})


def start_target_server() -> tuple[ThreadingHTTPServer, str]:
    """A real HTTP server, on a port the OS picked for us."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = ThreadingHTTPServer(("127.0.0.1", port), _TargetHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    return server, "http://127.0.0.1:" + str(port)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


async def ensure_fixture(base_url: str) -> None:
    """The probe project, its environment, its variables and one auth rule.

    Written with raw statements, like every other probe: the point is to put rows
    in place, not to exercise a mapper.  The runs themselves are created through
    the real endpoint, because that is what schedules the executor.
    """
    await cleanup_fixture()

    async with engine.begin() as connection:
        guest_id = (
            await connection.execute(
                text("SELECT id FROM guest_sessions WHERE token_hash = :digest"),
                {"digest": GUEST_TOKEN_HASH},
            )
        ).scalar_one_or_none()

        if guest_id is None:
            guest_id = (
                await connection.execute(
                    text(
                        "INSERT INTO guest_sessions (id, token_hash, expires_at, last_seen_at) "
                        "VALUES (:id, :digest, now() + interval '30 days', now()) RETURNING id"
                    ),
                    {"id": uuid.uuid4(), "digest": GUEST_TOKEN_HASH},
                )
            ).scalar_one()

        project_id = (
            await connection.execute(
                text(
                    "INSERT INTO projects (id, guest_session_id, public_id, name) "
                    "VALUES (:id, :guest, :public_id, :name) RETURNING id"
                ),
                {
                    "id": uuid.uuid4(),
                    "guest": guest_id,
                    "public_id": PROJECT_PUBLIC_ID,
                    "name": "Verify run executor",
                },
            )
        ).scalar_one()

        environment_id = (
            await connection.execute(
                text(
                    "INSERT INTO environments "
                    "(id, project_id, public_id, name, kind, base_url, is_default) "
                    "VALUES (:id, :project, :public_id, :name, 'staging', :base_url, true) "
                    "RETURNING id"
                ),
                {
                    "id": uuid.uuid4(),
                    "project": project_id,
                    "public_id": ENVIRONMENT_PUBLIC_ID,
                    "name": "Executor target",
                    "base_url": base_url,
                },
            )
        ).scalar_one()

        for key, value, is_secret in (
            (ENV_SECRET_NAME, ENV_SECRET_VALUE, True),
            (ENV_TOKEN_NAME, ENV_TOKEN_VALUE, True),
        ):
            await connection.execute(
                text(
                    "INSERT INTO environment_variables "
                    "(id, environment_id, key, value_encrypted, is_secret, enabled) "
                    "VALUES (:id, :environment, :key, :value, :secret, true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "environment": environment_id,
                    "key": key,
                    "value": value,
                    "secret": is_secret,
                },
            )

        await connection.execute(
            text(
                "INSERT INTO environment_auths "
                "(id, environment_id, name, auth_type, config, is_default, is_enabled) "
                "VALUES (:id, :environment, :name, 'bearer', CAST(:config AS jsonb), true, true)"
            ),
            {
                "id": uuid.uuid4(),
                "environment": environment_id,
                "name": "Default bearer",
                "config": json.dumps(
                    {"type": "bearer", "bearerToken": "{{" + ENV_TOKEN_NAME + "}}"}
                ),
            },
        )


async def cleanup_fixture() -> None:
    """Remove the probe project and everything under it, in dependency order."""
    async with engine.begin() as connection:
        project_id = (
            await connection.execute(
                text("SELECT id FROM projects WHERE public_id = :public_id"),
                {"public_id": PROJECT_PUBLIC_ID},
            )
        ).scalar_one_or_none()

        if project_id is None:
            return

        for statement in (
            "DELETE FROM test_runs WHERE project_id = :project",
            "DELETE FROM test_plans WHERE project_id = :project",
            "DELETE FROM api_specs WHERE project_id = :project",
            "DELETE FROM environments WHERE project_id = :project",
            "DELETE FROM projects WHERE id = :project",
        ):
            await connection.execute(text(statement), {"project": project_id})


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


def step(
    *,
    key: str,
    index: int,
    kind: str = "request",
    method: str | None = "GET",
    path: str | None = "/ok",
    produces: str | None = None,
) -> dict[str, Any]:
    return {
        "id": key,
        "index": index,
        "kind": kind,
        "description": {"text": f"Step {key}"},
        "endpointId": f"ep_{key}",
        "method": method,
        "path": path,
        "produces": produces,
        "consumes": [],
    }


def assertion(
    *,
    key: str,
    kind: str = "status",
    target: str = "status",
    expected: str = "200",
) -> dict[str, Any]:
    return {
        "id": key,
        "kind": kind,
        "target": target,
        "expected": expected,
        "description": {"text": f"Assertion {key}"},
    }


def scenario(
    *,
    key: str,
    index: int,
    steps: list[dict[str, Any]] | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": key,
        "index": index,
        "name": {"text": f"Scenario {key}"},
        "description": {"text": "Verify"},
        "riskLevel": "low",
        "expected": {"text": "It works"},
        "steps": steps if steps is not None else [step(key=f"{key}__step_0", index=0)],
        "assertions": assertions if assertions is not None else [],
    }


def plan_payload(plan_id: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": plan_id,
        "projectId": PROJECT_PUBLIC_ID,
        "specId": SPEC_ID,
        "name": {"text": "Verify executor plan"},
        "goal": {"text": "Execute deterministically"},
        "riskLevel": "medium",
        "status": "approved",
        "scenarios": scenarios,
        "source": "generated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "rejectedAt": None,
        "rejectionReason": None,
    }


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #


async def create_run(
    client: httpx.AsyncClient,
    plan_id: str,
    scenarios: list[dict[str, Any]],
    base_url: str,
) -> str:
    response = await client.post(
        f"/api/projects/{PROJECT_PUBLIC_ID}/runs",
        json={
            "projectId": PROJECT_PUBLIC_ID,
            "planId": plan_id,
            "plan": plan_payload(plan_id, scenarios),
            "specId": SPEC_ID,
            "specDocument": SPEC_DOCUMENT,
            "environmentId": ENVIRONMENT_PUBLIC_ID,
            "variables": {ENV_SECRET_NAME: ENV_SECRET_VALUE},
            "baseUrl": base_url,
        },
    )
    if response.status_code != 201:
        raise AssertionError(f"create returned {response.status_code}: {response.text[:400]}")

    return response.json()["id"]


async def wait_for_terminal(
    client: httpx.AsyncClient, run_id: str, *, timeout: float = 30.0
) -> dict[str, Any]:
    """Poll the run until the executor has finished with it."""
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {}

    while time.monotonic() < deadline:
        body = (await client.get(f"/api/runs/{run_id}")).json()["run"]
        if body["status"] in TERMINAL:
            return body
        await asyncio.sleep(0.1)

    return body


async def detail(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    return (await client.get(f"/api/runs/{run_id}")).json()


async def events(client: httpx.AsyncClient, run_id: str) -> list[dict[str, Any]]:
    return (await client.get(f"/api/runs/{run_id}/events")).json()


# --------------------------------------------------------------------------- #
# Direct SQL: what the API does not expose
# --------------------------------------------------------------------------- #


async def step_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT s.step_key, s.status, s.step_type, s.duration_ms, s.error_code, "
                    "s.error_message, s.started_at, s.finished_at, c.scenario_key "
                    "FROM run_steps s JOIN run_scenarios c ON c.id = s.run_scenario_id "
                    "WHERE c.run_id = :id ORDER BY c.sort_order, s.sort_order, s.step_key"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def assertion_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT a.assertion_key, a.status, a.actual_value, a.expected_value, "
                    "a.error_message, c.scenario_key "
                    "FROM run_assertions a JOIN run_scenarios c ON c.id = a.run_scenario_id "
                    "WHERE c.run_id = :id ORDER BY c.sort_order, a.assertion_key"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def scenario_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scenario_key, status, started_at, finished_at FROM run_scenarios "
                    "WHERE run_id = :id ORDER BY sort_order, scenario_key"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def evidence_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT evidence_type, label, value FROM run_evidence "
                    "WHERE run_id = :id ORDER BY created_at, id"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def stored_text(run_id: str) -> str:
    """Every character this run stored, for the sentinel scan.

    Everything a value could hide in: the run row, the tree, the evidence and the
    event payloads -- concatenated as JSON so a substring search is a real
    answer rather than a list of columns somebody remembered to check.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT jsonb_build_object(
                        'run', (SELECT to_jsonb(r) FROM test_runs r WHERE r.id = :run),
                        'scenarios', (SELECT coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb)
                                      FROM run_scenarios c WHERE c.run_id = :run),
                        'steps', (SELECT coalesce(jsonb_agg(to_jsonb(s)), '[]'::jsonb)
                                  FROM run_steps s WHERE s.run_scenario_id IN
                                  (SELECT id FROM run_scenarios WHERE run_id = :run)),
                        'assertions', (SELECT coalesce(jsonb_agg(to_jsonb(a)), '[]'::jsonb)
                                       FROM run_assertions a WHERE a.run_scenario_id IN
                                       (SELECT id FROM run_scenarios WHERE run_id = :run)),
                        'evidence', (SELECT coalesce(jsonb_agg(to_jsonb(e)), '[]'::jsonb)
                                     FROM run_evidence e WHERE e.run_id = :run),
                        'events', (SELECT coalesce(jsonb_agg(to_jsonb(v)), '[]'::jsonb)
                                   FROM run_events v WHERE v.run_id = :run)
                    )::text AS stored
                    """
                ),
                {"run": uuid.UUID(run_id)},
            )
        ).scalar_one()

    return str(row)


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def payload_of(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("payload") or {}


def names_of(rows: list[dict[str, Any]]) -> list[str]:
    return [row["eventType"] for row in rows]


async def check_basic(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 1 -- a request that passes, carrying the environment's auth."""
    before = HITS.get("/auth", 0)

    run_id = await create_run(
        client,
        "plan_exec_basic",
        [
            scenario(
                key="scn_basic",
                index=0,
                steps=[step(key="scn_basic__step_0", index=0, path="/auth")],
                assertions=[assertion(key="scn_basic__a0", expected="200")],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case1: a request answered 200 passes the run", run["status"], "passed")
    report.check(
        "case1: the run recorded both ends of its life",
        run["startedAt"] is not None and run["finishedAt"] is not None,
        run,
    )
    report.check(
        "case1: durationMs is a measured, non-negative number",
        isinstance(run["durationMs"], int) and run["durationMs"] >= 0,
        run["durationMs"],
    )
    report.equal("case1: the request really went out", HITS.get("/auth", 0) - before, 1)
    report.equal(
        "case1: the summary counts what ran",
        {
            "scenarios": run["summary"]["scenarios"],
            "steps": run["summary"]["steps"],
            "assertions": run["summary"]["assertions"],
            "passedSteps": run["summary"]["passedSteps"],
            "passedAssertions": run["summary"]["passedAssertions"],
        },
        {"scenarios": 1, "steps": 1, "assertions": 1, "passedSteps": 1, "passedAssertions": 1},
    )

    steps = await step_rows(run_id)
    report.equal("case1: the step row is passed", [row["status"] for row in steps], ["passed"])
    report.check(
        "case1: the step carries a duration and both timestamps",
        steps[0]["duration_ms"] is not None
        and steps[0]["started_at"] is not None
        and steps[0]["finished_at"] is not None,
        steps[0],
    )
    report.check("case1: a passing step has no error code", steps[0]["error_code"] is None)

    scenarios = await scenario_rows(run_id)
    report.equal("case1: the scenario row is passed", [row["status"] for row in scenarios], ["passed"])
    report.check(
        "case1: the scenario carries both timestamps",
        scenarios[0]["started_at"] is not None and scenarios[0]["finished_at"] is not None,
    )

    assertions = await assertion_rows(run_id)
    report.equal("case1: the assertion row is passed", [row["status"] for row in assertions], ["passed"])
    report.equal("case1: the assertion recorded what it saw", assertions[0]["actual_value"], "200")

    evidence = await evidence_rows(run_id)
    report.equal(
        "case1: the step left endpoint evidence",
        [(row["evidence_type"], row["label"]["key"], row["value"]) for row in evidence],
        [("endpoint", "console.runs.evidence.endpoint", "GET /auth")],
    )

    rows = await events(client, run_id)
    report.equal(
        "case1: the event sequence",
        names_of(rows),
        ["run.started", "step.started", "assertion.completed", "step.completed", "run.completed"],
    )
    report.equal(
        "case1: seq is dense from 1",
        [row["seq"] for row in rows],
        list(range(1, len(rows) + 1)),
    )
    report.check(
        "case1: run.started announces the instant the row carries",
        payload_of(rows[0]).get("startedAt") is not None,
        rows[0],
    )
    report.check(
        "case1: step.completed carries its duration and its evidence",
        payload_of(rows[3]).get("durationMs") is not None
        and payload_of(rows[3]).get("evidence") == [
            {"label": {"key": "console.runs.evidence.endpoint"}, "params": {}, "value": "GET /auth"}
        ]
        or payload_of(rows[3]).get("evidence")
        == [{"label": {"key": "console.runs.evidence.endpoint"}, "value": "GET /auth"}],
        payload_of(rows[3]),
    )
    report.equal(
        "case1: assertion.completed carries the verdict",
        {
            "assertionId": payload_of(rows[2]).get("assertionId"),
            "status": payload_of(rows[2]).get("status"),
            "expected": payload_of(rows[2]).get("expected"),
            "actual": payload_of(rows[2]).get("actual"),
            "stepId": payload_of(rows[2]).get("stepId"),
        },
        {
            "assertionId": "scn_basic__a0",
            "status": "passed",
            "expected": "200",
            "actual": "200",
            "stepId": "scn_basic__step_0",
        },
    )
    report.check(
        "case1: run.completed closes the stream",
        payload_of(rows[4]).get("finishedAt") is not None
        and isinstance(payload_of(rows[4]).get("durationMs"), int),
        payload_of(rows[4]),
    )

    snapshot = await detail(client, run_id)
    report.equal("case1: lastSeq matches the stream", snapshot["lastSeq"], len(rows))

    return run_id


async def check_assertion_failure(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 3 -- a failing assertion fails the step and the run, and its neighbours still run."""
    run_id = await create_run(
        client,
        "plan_exec_assertion",
        [
            scenario(
                key="scn_assert",
                index=0,
                steps=[step(key="scn_assert__step_0", index=0, path="/ok")],
                assertions=[
                    assertion(key="scn_assert__a0", expected="201"),
                    assertion(key="scn_assert__a1", expected="200"),
                ],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case3: a failing assertion fails the run", run["status"], "failed")
    report.check("case3: the run says why", run["failure"] is not None, run["failure"])
    report.equal(
        "case3: the run failure names a status the console can render",
        (run["failure"] or {}).get("message"),
        {"text": "assertion-failed"},
    )
    report.equal(
        "case3: the summary counts both outcomes",
        {
            "passedAssertions": run["summary"]["passedAssertions"],
            "failedAssertions": run["summary"]["failedAssertions"],
            "failedSteps": run["summary"]["failedSteps"],
        },
        {"passedAssertions": 1, "failedAssertions": 1, "failedSteps": 1},
    )

    assertions = await assertion_rows(run_id)
    report.equal(
        "case3: every assertion ran, in key order",
        [(row["assertion_key"], row["status"], row["actual_value"]) for row in assertions],
        [
            ("scn_assert__a0", "failed", "200"),
            ("scn_assert__a1", "passed", "200"),
        ],
    )

    steps = await step_rows(run_id)
    report.equal(
        "case3: the step that carried them failed",
        (steps[0]["status"], steps[0]["error_code"]),
        ("failed", "assertion-failed"),
    )

    rows = await events(client, run_id)
    report.equal(
        "case3: the event sequence",
        names_of(rows),
        [
            "run.started",
            "step.started",
            "assertion.completed",
            "assertion.completed",
            "step.failed",
            "run.failed",
        ],
    )
    report.equal(
        "case3: the step failure travels in the frame's own shape",
        payload_of(rows[4]).get("failure"),
        {"message": {"text": "assertion-failed"}, "detail": "one or more assertions failed"},
    )
    report.check(
        "case3: run.failed carries the step it died on",
        payload_of(rows[5]).get("failedStepId") == "scn_assert__step_0",
        payload_of(rows[5]),
    )

    return run_id


async def check_scenarios(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 4 -- a failed scenario stops, the next one still runs, and the order is the plan's."""
    before = HITS.get("/ok", 0)

    run_id = await create_run(
        client,
        "plan_exec_scenarios",
        [
            # Submitted second, sorts first: the executor orders by sort_order,
            # not by the order the payload happens to carry.
            scenario(
                key="scn_second",
                index=1,
                steps=[step(key="scn_second__step_0", index=0, path="/ok")],
                assertions=[assertion(key="scn_second__a0", expected="200")],
            ),
            scenario(
                key="scn_first",
                index=0,
                steps=[
                    step(key="scn_first__step_0", index=0, path="/orders/{{nobody_defined_this}}"),
                    step(key="scn_first__step_1", index=1, path="/ok"),
                ],
                assertions=[assertion(key="scn_first__a0", expected="200")],
            ),
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case4: a failed scenario fails the run", run["status"], "failed")
    report.equal(
        "case4: both scenarios are recorded",
        [(row["scenario_key"], row["status"]) for row in await scenario_rows(run_id)],
        [("scn_first", "failed"), ("scn_second", "passed")],
    )
    report.equal(
        "case4: the failing scenario's later step never ran",
        [
            (row["scenario_key"], row["step_key"], row["status"])
            for row in await step_rows(run_id)
        ],
        [
            ("scn_first", "scn_first__step_0", "failed"),
            ("scn_first", "scn_first__step_1", "skipped"),
            ("scn_second", "scn_second__step_0", "passed"),
        ],
    )
    report.equal(
        "case4: only the surviving scenario reached the API",
        HITS.get("/ok", 0) - before,
        1,
    )
    report.equal(
        "case4: the steps arrive scenario by scenario, in sort order",
        [payload_of(row).get("scenarioId") for row in await events(client, run_id) if row["eventType"] == "step.started"],
        ["scn_first", "scn_second"],
    )

    return run_id


async def check_runtime_variable(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 5 -- an extract step feeds the step after it, in memory only."""
    LAST_ORDER_ID.pop("value", None)

    run_id = await create_run(
        client,
        "plan_exec_runtime",
        [
            scenario(
                key="scn_runtime",
                index=0,
                steps=[
                    step(key="scn_runtime__step_0", index=0, path="/ok"),
                    step(
                        key="scn_runtime__step_1",
                        index=1,
                        kind="extract",
                        method=None,
                        path=None,
                        produces="token",
                    ),
                    step(key="scn_runtime__step_2", index=2, path="/orders/{{token}}"),
                ],
                assertions=[assertion(key="scn_runtime__a0", expected="200")],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case5: the run passes", run["status"], "passed")
    report.equal(
        "case5: the extracted value reached the API",
        LAST_ORDER_ID.get("value"),
        EXTRACTED_VALUE,
    )
    report.equal(
        "case5: ...on the path the template asked for",
        HITS.get("/orders/" + EXTRACTED_VALUE, 0),
        1,
    )

    steps = await step_rows(run_id)
    report.equal(
        "case5: every step in the scenario ran",
        [(row["step_key"], row["status"]) for row in steps],
        [
            ("scn_runtime__step_0", "passed"),
            ("scn_runtime__step_1", "passed"),
            ("scn_runtime__step_2", "passed"),
        ],
    )

    evidence = await evidence_rows(run_id)
    report.check(
        "case5: the extract evidence names the variable, never its value",
        any(
            row["label"]["key"] == "console.runs.evidence.extracted" and row["value"] == "token"
            for row in evidence
        ),
        evidence,
    )
    report.check(
        "case5: the request evidence keeps the template",
        any(row["value"] == "GET /orders/{{token}}" for row in evidence),
        evidence,
    )
    report.check(
        "case5: the runtime value was never written down",
        EXTRACTED_VALUE not in await stored_text(run_id),
    )

    return run_id


async def check_missing_variable(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 6 -- a template with no value fails the step without sending anything."""
    before = dict(HITS)

    run_id = await create_run(
        client,
        "plan_exec_missing",
        [
            scenario(
                key="scn_missing",
                index=0,
                steps=[step(key="scn_missing__step_0", index=0, path="/orders/{{missing_id}}")],
                assertions=[assertion(key="scn_missing__a0", expected="200")],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case6: a step with no value fails the run", run["status"], "failed")

    steps = await step_rows(run_id)
    report.equal(
        "case6: the step says what was missing",
        (steps[0]["status"], steps[0]["error_code"]),
        ("failed", "missing-runtime-variable"),
    )
    report.check(
        "case6: the failure names the variable, and says nothing else",
        steps[0]["error_message"] == "this run has no value for: missing_id",
        steps[0]["error_message"],
    )
    report.equal(
        "case6: nothing was sent to the API",
        [key for key in HITS if key.startswith("/orders/") and HITS[key] != before.get(key, 0)],
        [],
    )
    report.equal(
        "case6: the assertions were left unjudged",
        [(row["status"], row["actual_value"]) for row in await assertion_rows(run_id)],
        [("skipped", None)],
    )
    report.equal(
        "case6: the event sequence stops at the failure",
        names_of(await events(client, run_id)),
        ["run.started", "step.started", "step.failed", "run.failed"],
    )

    return run_id


async def check_http_500(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 7 -- an error status is a response, and an assertion may expect it."""
    run_id = await create_run(
        client,
        "plan_exec_500",
        [
            scenario(
                key="scn_500",
                index=0,
                steps=[step(key="scn_500__step_0", index=0, path="/server-error")],
                assertions=[assertion(key="scn_500__a0", expected="500")],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("case7: an expected 500 passes the run", run["status"], "passed")
    report.equal(
        "case7: the assertion compared the status it got",
        [(row["status"], row["actual_value"]) for row in await assertion_rows(run_id)],
        [("passed", "500")],
    )
    report.equal(
        "case7: the step is passed, not a transport failure",
        [(row["status"], row["error_code"]) for row in await step_rows(run_id)],
        [("passed", None)],
    )

    return run_id


async def check_cancel_while_running(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """Case 4 (cancel) -- a cancel in flight stops the next scenario and is never overwritten."""
    before = HITS.get("/ok", 0)

    run_id = await create_run(
        client,
        "plan_exec_cancel",
        [
            scenario(
                key="scn_slow",
                index=0,
                steps=[step(key="scn_slow__step_0", index=0, path="/slow")],
                assertions=[assertion(key="scn_slow__a0", expected="200")],
            ),
            scenario(
                key="scn_never",
                index=1,
                steps=[step(key="scn_never__step_0", index=0, path="/ok")],
                assertions=[assertion(key="scn_never__a0", expected="200")],
            ),
        ],
        base_url,
    )

    # Wait until the slow call is really in flight -- a cancel that lands before
    # the request leaves is a different case, checked separately.
    deadline = time.monotonic() + 10.0
    while HITS.get("/slow", 0) == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    report.check("cancel: the slow call is in flight before the cancel", HITS.get("/slow", 0) >= 1, HITS.get("/slow", 0))

    cancelled = await client.post(f"/api/runs/{run_id}/cancel")
    report.equal("cancel: the request is accepted", cancelled.status_code, 200)
    report.equal("cancel: the run is cancelled", cancelled.json()["status"], "cancelled")

    # The step in flight finishes (cooperatively), then the executor notices.
    await asyncio.sleep(SLOW_SECONDS + 1.5)

    run = (await client.get(f"/api/runs/{run_id}")).json()["run"]
    report.equal("cancel: the run stays cancelled", run["status"], "cancelled")

    rows = await events(client, run_id)
    names = names_of(rows)
    report.check("cancel: the cancellation is on the stream", "run.cancelled" in names, names)
    report.check("cancel: a cancelled run is never reported as finished", "run.completed" not in names and "run.failed" not in names, names)
    report.check(
        "cancel: the step that was in flight is recorded honestly",
        ("scn_slow", "scn_slow__step_0", "passed")
        in [(r["scenario_key"], r["step_key"], r["status"]) for r in await step_rows(run_id)],
        {"steps": await step_rows(run_id), "events": names, "slow_hits": HITS.get("/slow", 0)},
    )
    report.equal(
        "cancel: the scenario that never started is skipped",
        [(row["scenario_key"], row["status"]) for row in await scenario_rows(run_id)],
        [("scn_slow", "passed"), ("scn_never", "skipped")],
    )
    report.equal(
        "cancel: the step that never started is skipped",
        [(row["scenario_key"], row["step_key"], row["status"]) for row in await step_rows(run_id)],
        [
            ("scn_slow", "scn_slow__step_0", "passed"),
            ("scn_never", "scn_never__step_0", "skipped"),
        ],
    )
    report.equal("cancel: the second scenario never reached the API", HITS.get("/ok", 0) - before, 0)
    report.check(
        "cancel: no step of it was ever announced",
        "scn_never__step_0" not in [payload_of(row).get("stepId") for row in rows if row["eventType"] == "step.started"],
        names,
    )
    seqs = [row["seq"] for row in rows]
    report.equal("cancel: seq stayed dense under two writers", seqs, list(range(1, len(seqs) + 1)))
    report.equal("cancel: no seq was reused", len(set(seqs)), len(seqs))

    return run_id


async def check_cancel_before_start(
    client: httpx.AsyncClient, report: Report, base_url: str
) -> str:
    """A run cancelled before its executor starts is never announced as started.

    The race is made deterministic on purpose: the executor's entry point is
    delayed for a second, which is a second the cancel has all to itself.  The
    delay is a test's instrument, not a production behaviour -- the real
    function is put back immediately.
    """
    from backend.services import run_executor

    original = run_executor.execute_run

    async def delayed(run_id: uuid.UUID) -> None:
        await asyncio.sleep(1.0)
        await original(run_id)

    run_executor.execute_run = delayed  # type: ignore[assignment]

    try:
        run_id = await create_run(
            client,
            "plan_exec_cancel_before",
            [
                scenario(
                    key="scn_late",
                    index=0,
                    steps=[step(key="scn_late__step_0", index=0, path="/ok")],
                    assertions=[assertion(key="scn_late__a0", expected="200")],
                )
            ],
            base_url,
        )

        cancelled = await client.post(f"/api/runs/{run_id}/cancel")
        report.equal("cancel-before-start: the cancel is accepted", cancelled.status_code, 200)

        await asyncio.sleep(2.0)
    finally:
        run_executor.execute_run = original  # type: ignore[assignment]

    run = (await client.get(f"/api/runs/{run_id}")).json()["run"]
    report.equal("cancel-before-start: the run is cancelled", run["status"], "cancelled")

    rows = await events(client, run_id)
    report.equal(
        "cancel-before-start: the executor announced nothing",
        names_of(rows),
        ["run.cancelled"],
    )

    # And asking it to run again changes nothing: the status is not "queued".
    await run_executor.execute_run(uuid.UUID(run_id))
    report.equal(
        "cancel-before-start: a second executor is a no-op",
        names_of(await events(client, run_id)),
        ["run.cancelled"],
    )

    report.equal(
        "cancel-before-start: every step is skipped",
        [(row["step_key"], row["status"]) for row in await step_rows(run_id)],
        [("scn_late__step_0", "skipped")],
    )

    return run_id


async def check_methods(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """The four mutating verbs the plan can name, each really sent.

    No body goes with any of them: a request body has no source in a test plan
    yet (a step carries a method and a path), and inventing one from the OpenAPI
    document is a later phase.  The check is that the verbs arrive -- and that
    nothing pretends a payload went with them.
    """
    verbs = ["POST", "PUT", "PATCH", "DELETE"]

    run_id = await create_run(
        client,
        "plan_exec_methods",
        [
            scenario(
                key="scn_methods",
                index=0,
                steps=[
                    step(
                        key=f"scn_methods__step_{index}",
                        index=index,
                        method=verb,
                        path="/mutate",
                    )
                    for index, verb in enumerate(verbs)
                ],
                assertions=[assertion(key="scn_methods__a0", expected="200")],
            )
        ],
        base_url,
    )

    run = await wait_for_terminal(client, run_id)

    report.equal("methods: every mutating verb is accepted by the API under test", run["status"], "passed")
    report.equal(
        "methods: each of the four arrived, with no body",
        {verb: METHOD_BODY_LENGTH.get(verb) for verb in verbs},
        {verb: 0 for verb in verbs},
    )
    report.equal(
        "methods: the scenario's steps all passed",
        [row["status"] for row in await step_rows(run_id)],
        ["passed"] * len(verbs),
    )

    return run_id


# --------------------------------------------------------------------------- #
# The stream, read the way a browser reads it
# --------------------------------------------------------------------------- #


async def read_stream(
    app: Any, run_id: str, *, timeout: float = 15.0
) -> tuple[int, dict[str, str], list[tuple[int | None, str | None, Any]]]:
    """Every frame of a run's stream, read over the ASGI protocol.

    ``httpx.ASGITransport`` collects a response body before handing it back, which
    is the wrong shape for a stream that ends when a run does -- so this speaks
    the protocol directly, with the same messages uvicorn exchanges.
    """
    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    state: dict[str, Any] = {"sent": False, "status": 0, "headers": {}}
    chunks: list[str] = []
    finished = asyncio.Event()

    async def receive() -> dict[str, Any]:
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": b"", "more_body": False}

        return await incoming.get()

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
            state["headers"] = {
                key.decode().lower(): value.decode()
                for key, value in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b"").decode("utf-8"))
            if not message.get("more_body", False):
                finished.set()

    target = "/api/runs/" + run_id + "/events/stream"

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": target,
        "raw_path": target.encode(),
        "query_string": b"",
        "root_path": "",
        # The credential every real stream request carries (Phase 8.5 Step 3): a
        # raw ASGI scope bypasses the client defaults, and a stream opened without
        # it is a 401 rather than a stream.
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in GUEST_HEADERS.items()
        ],
        "server": ("verify", 80),
        "client": ("127.0.0.1", 12345),
    }

    task = asyncio.create_task(app(scope, receive, send))

    try:
        await asyncio.wait_for(finished.wait(), timeout=timeout)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    frames: list[tuple[int | None, str | None, Any]] = []

    for block in "".join(chunks).split("\n\n"):
        if block.strip() == "":
            continue

        event_id: int | None = None
        name: str | None = None
        data: list[str] = []

        for line in block.split("\n"):
            if line.startswith("id:"):
                event_id = int(line[3:].strip())
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())

        frames.append((event_id, name, json.loads("".join(data)) if data else None))

    return state["status"], state["headers"], frames


async def check_stream(
    app: Any, client: httpx.AsyncClient, report: Report, run_id: str
) -> None:
    """The executor's events, over the stream the console actually subscribes to."""
    status, headers, frames = await read_stream(app, run_id)
    replayed = await events(client, run_id)

    report.equal("sse: the stream answers 200", status, 200)
    report.equal(
        "sse: it is an event stream",
        headers.get("content-type"),
        "text/event-stream; charset=utf-8",
    )
    report.equal(
        "sse: the frames are the events the run stored, in order",
        [frame[1] for frame in frames],
        names_of(replayed),
    )
    report.equal(
        "sse: every frame's id is its seq",
        [frame[0] for frame in frames],
        [row["seq"] for row in replayed],
    )
    report.check(
        "sse: the frames carry their payloads",
        all(frame[2] is not None for frame in frames),
        frames[:1],
    )
    report.check(
        "sse: the stream ends on a terminal event",
        bool(frames) and frames[-1][1] in ("run.completed", "run.failed", "run.cancelled"),
        frames[-1:] or None,
    )


async def check_security(client: httpx.AsyncClient, report: Report, run_ids: list[str]) -> None:
    """The sentinel scan: nothing secret reached a row or a response.

    Four values could leak if anything were careless -- the environment's unused
    secret, the bearer token the auth rule resolved, the runtime value an extract
    step lifted, and the header that carried the token -- and all four are
    searched for in every row of every probe run, and in what the API returns.
    """
    stored = " ".join([await stored_text(run_id) for run_id in run_ids])
    responses = " ".join(
        [
            json.dumps(await detail(client, run_id)) + json.dumps(await events(client, run_id))
            for run_id in run_ids
        ]
    )

    for label, value in (
        ("the environment's unused secret", ENV_SECRET_VALUE),
        ("the bearer token's value", ENV_TOKEN_VALUE),
        ("the extracted runtime value", EXTRACTED_VALUE),
    ):
        report.check(f"security: {label} is in no stored row", value not in stored)
        report.check(f"security: {label} is in no API response", value not in responses)

    report.check(
        "security: no Authorization header was written down",
        "Authorization" not in stored and "Bearer " not in stored,
    )
    report.check(
        "security: no resolved request path was written down",
        "/orders/" + EXTRACTED_VALUE not in stored,
        "a substituted URL reached a row",
    )
    report.check(
        "security: the frozen base URL is still recorded, as the run's own field",
        "127.0.0.1" in stored,
        "the run lost the environment it ran against",
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()

    print("verifying the run executor\n")

    server, base_url = start_target_server()

    try:
        await ensure_fixture(base_url)

        app = create_app()
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
            run_ids = [
                await check_basic(client, report, base_url),
                await check_assertion_failure(client, report, base_url),
                await check_scenarios(client, report, base_url),
                await check_runtime_variable(client, report, base_url),
                await check_missing_variable(client, report, base_url),
                await check_http_500(client, report, base_url),
                await check_methods(client, report, base_url),
                await check_cancel_while_running(client, report, base_url),
                await check_cancel_before_start(client, report, base_url),
            ]

            await check_stream(app, client, report, run_ids[0])
            await check_security(client, report, run_ids)
    finally:
        await cleanup_fixture()
        await engine.dispose()
        server.shutdown()
        server.server_close()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
