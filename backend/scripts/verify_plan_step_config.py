"""End-to-end verification of the request target a persisted plan carries.

Phase 8.2 Step 1 closed the gap the pipeline contract calls **G1**: a plan-side
step could not state the request it stands for.  `test_steps` has no method and
no path column -- by design, because a plan step is an operation, not an HTTP
request -- so the pair travels in `test_steps.config`, and the run snapshot
reads it back when the create payload does not carry it.

The chain this script verifies, end to end and in order:

    plan payload -> test_steps.config -> run snapshot -> run_steps.method/path
                 -> the executor actually calling that method and path

The last arrow is the point.  A helper that round-trips a dictionary proves
nothing about whether the executor can still make a request; here a **real HTTP
server** on the loopback interface records every method and path it receives, so
"the run's steps were recovered from the stored plan" is a fact about bytes that
arrived on a socket.

Same shape as the other `verify_*.py` scripts: real PostgreSQL, the real ASGI
app, the real exception handlers, runs created through the real create endpoint.
Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_plan_step_config.py

It writes a project of its own (`prj_verify_step_config`) and deletes it again
-- including on failure.  It does not touch any other project's rows.

One approximation is deliberate and worth naming.  `POST .../runs` still
requires the whole `plan` object, so the "the server already holds the plan"
case is expressed the only way the current contract allows: the same plan, sent
twice under the same `planId`, with the request targets **absent** the second
time.  What the second create no longer carries is exactly the field the server
must now be able to supply from its own rows.
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

PROJECT_PUBLIC_ID = "prj_verify_step_config"
ENVIRONMENT_PUBLIC_ID = "env_verify_step_config"

GUEST_TOKEN = "plan-step-config-guest-session"
# The fixture inserts the digest the service computes for the token it names:
# the plaintext column is gone (Phase 8.5 Step 2), and these rows are ownership
# anchors for the fixture -- no business route reads an identity yet.
GUEST_TOKEN_HASH = hashlib.sha256(GUEST_TOKEN.encode("utf-8")).hexdigest()

# Every request this suite makes carries the fixture guest's token: the
# business routes verify a guest session (Phase 8.5 Step 3), and a suite that
# sent nothing would be measuring 401s.
GUEST_HEADERS = {"X-Guest-Session": GUEST_TOKEN}
"""Reused from `seed_dev_data.py`: a project needs an owner and there is no
auth yet.  Created here if the seed has not been run."""

SPEC_TITLE = "Verify Step Config API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Step Config API","version":"1.0.0"},'
    '"paths":{"/users":{"get":{"responses":{"200":{"description":"ok"}}}},'
    '"/orders":{"post":{"responses":{"200":{"description":"ok"}}}},'
    '"/orders/{id}":{"put":{"responses":{"200":{"description":"ok"}}},'
    '"patch":{"responses":{"200":{"description":"ok"}}},'
    '"delete":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

PLAN_PUBLIC_ID = "plan_verify_step_config"
EMPTY_PLAN_PUBLIC_ID = "plan_verify_step_config_empty"

EXTRACTED_TOKEN = "abc123"
"""What the target returns as `token`, so the extract step has something to lift."""

TERMINAL = ("passed", "failed", "cancelled")

VERB_STEPS: tuple[tuple[str, str, str], ...] = (
    ("get_users__0", "GET", "/users"),
    ("post_orders__0", "POST", "/orders"),
    ("put_orders__0", "PUT", "/orders/1"),
    ("patch_orders__0", "PATCH", "/orders/1"),
    ("delete_orders__0", "DELETE", "/orders/1"),
)
"""The five verbs, one step each: the whole method vocabulary the executor knows."""

EXTRACT_STEP_KEY = "get_users__extract_token"
ASSERT_STEP_KEY = "assert__6"


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

HITS: dict[tuple[str, str], int] = {}
"""Every request the executor made, keyed by `(method, path)`."""


class _TargetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - silence the default log
        return

    def _answer(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        path = urlsplit(self.path).path
        key = (method, path)
        HITS[key] = HITS.get(key, 0) + 1

        body = json.dumps({"token": EXTRACTED_TOKEN, "path": path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the name is the stdlib's
        self._answer("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._answer("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._answer("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._answer("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._answer("DELETE")


def start_target_server() -> tuple[ThreadingHTTPServer, str]:
    """A real HTTP server, on a port the OS picked for us."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TargetHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    host, port = server.server_address[:2]
    assert host == "127.0.0.1", host  # noqa: S101 - a bound socket, not user input
    assert isinstance(port, int)  # noqa: S101

    # A port is not reachable the instant it is bound; one connection proves it is.
    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass

    return server, f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------- #
# Fixture
# --------------------------------------------------------------------------- #


async def ensure_fixture(base_url: str) -> None:
    """The probe project: one environment pointing at the target server.

    Written with SQL rather than through an endpoint, which is what the other
    scripts do too -- there is no project or environment API to call, and the
    point of the fixture is to have a project in place, not to exercise a mapper.
    The runs themselves are created through the real endpoint, because that is
    what writes the plan tree and the snapshot.
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
                    "name": "Verify plan step config",
                },
            )
        ).scalar_one()

        await connection.execute(
            text(
                "INSERT INTO environments "
                "(id, project_id, public_id, name, kind, base_url, is_default) "
                "VALUES (:id, :project, :public_id, :name, 'staging', :base_url, true)"
            ),
            {
                "id": uuid.uuid4(),
                "project": project_id,
                "public_id": ENVIRONMENT_PUBLIC_ID,
                "name": "Step config target",
                "base_url": base_url,
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
    method: str | None = None,
    path: str | None = None,
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


def verb_scenario(*, with_targets: bool) -> dict[str, Any]:
    """One scenario holding every verb, an extract and an assert step.

    `with_targets` is the whole experiment: with it the payload states each
    request's method and path, without it the payload states neither, and the run
    must come out the same either way.
    """
    steps: list[dict[str, Any]] = [
        step(
            key=key,
            index=index,
            method=method if with_targets else None,
            path=path if with_targets else None,
        )
        for index, (key, method, path) in enumerate(VERB_STEPS)
    ]
    steps.append(
        step(key=EXTRACT_STEP_KEY, index=len(VERB_STEPS), kind="extract", produces="token")
    )
    steps.append(step(key=ASSERT_STEP_KEY, index=len(VERB_STEPS) + 1, kind="assert"))

    return {
        "id": "scenario_verbs",
        "index": 0,
        "name": {"text": "Every verb"},
        "description": {"text": "One request step per method"},
        "riskLevel": "low",
        "expected": {"text": "All five calls are made"},
        "steps": steps,
        "assertions": [
            {
                "id": "scenario_verbs__status",
                "kind": "status",
                "target": "status",
                "expected": "200",
                "description": {"text": "The last call answered 200"},
            }
        ],
    }


def targetless_scenario() -> dict[str, Any]:
    """A request step that names no request -- nothing to store, nothing to run.

    It is here to pin the negative: the recovery path supplies what the plan
    holds, and a plan that holds nothing must not invent a call.
    """
    return {
        "id": "scenario_targetless",
        "index": 0,
        "name": {"text": "No target"},
        "description": {"text": "A request step with no method or path"},
        "riskLevel": "low",
        "expected": {"text": "It is reported as not executable"},
        "steps": [step(key="nowhere__0", index=0)],
        "assertions": [],
    }


def plan_payload(plan_id: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": plan_id,
        "projectId": PROJECT_PUBLIC_ID,
        "specId": SPEC_ID,
        "name": {"text": "Verify step config plan"},
        "goal": {"text": "Prove a persisted plan can state its own requests"},
        "riskLevel": "low",
        "status": "approved",
        "scenarios": scenarios,
        "source": "generated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "rejectedAt": None,
        "rejectionReason": None,
    }


# --------------------------------------------------------------------------- #
# HTTP and database helpers
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
            "variables": {},
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


async def plan_configs(plan_public_id: str) -> dict[str, dict[str, Any]]:
    """`test_steps.config` for a stored plan, keyed by the step's stable key."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT s.step_key, s.step_type, s.config
                    FROM test_steps s
                    JOIN test_scenarios c ON c.id = s.scenario_id
                    JOIN test_plans p ON p.id = c.plan_id
                    WHERE p.public_id = :plan
                    """
                ),
                {"plan": plan_public_id},
            )
        ).mappings().all()

    return {row["step_key"]: {"type": row["step_type"], "config": row["config"]} for row in rows}


async def run_targets(run_id: str) -> dict[str, dict[str, Any]]:
    """The snapshot's `method` / `path` per step key, plus status and error code."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT s.step_key, s.step_type, s.method, s.path, s.status, s.error_code
                    FROM run_steps s
                    JOIN run_scenarios c ON c.id = s.run_scenario_id
                    WHERE c.run_id = :run
                    """
                ),
                {"run": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return {row["step_key"]: dict(row) for row in rows}


async def plan_row_count(plan_public_id: str) -> tuple[int, int]:
    """`(scenarios, steps)` stored for a plan -- reuse means these do not move."""
    async with AsyncSessionLocal() as session:
        scenarios = (
            await session.execute(
                text(
                    "SELECT count(*) FROM test_scenarios c JOIN test_plans p ON p.id = c.plan_id "
                    "WHERE p.public_id = :plan"
                ),
                {"plan": plan_public_id},
            )
        ).scalar_one()
        steps = (
            await session.execute(
                text(
                    "SELECT count(*) FROM test_steps s "
                    "JOIN test_scenarios c ON c.id = s.scenario_id "
                    "JOIN test_plans p ON p.id = c.plan_id WHERE p.public_id = :plan"
                ),
                {"plan": plan_public_id},
            )
        ).scalar_one()

    return scenarios, steps


async def test_steps_columns() -> dict[str, str]:
    """Every column of `test_steps` and its type: the schema must not have moved."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'test_steps'"
                )
            )
        ).mappings().all()

    return {row["column_name"]: row["data_type"] for row in rows}


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


async def check_schema_untouched(report: Report) -> None:
    """The plan-side table grew no columns; the pair lives in the JSONB blob."""
    columns = await test_steps_columns()

    report.check(
        "test_steps still has no method column",
        "method" not in columns,
        sorted(columns),
    )
    report.check(
        "test_steps still has no path column",
        "path" not in columns,
        sorted(columns),
    )
    report.equal("test_steps.config is jsonb", columns.get("config"), "jsonb")


async def check_persistence(
    client: httpx.AsyncClient, report: Report, base_url: str
) -> str:
    """A create that states its targets writes them into `test_steps.config`."""
    run_id = await create_run(
        client, PLAN_PUBLIC_ID, [verb_scenario(with_targets=True)], base_url
    )

    configs = await plan_configs(PLAN_PUBLIC_ID)

    for key, method, path in VERB_STEPS:
        stored = configs.get(key, {}).get("config")
        report.equal(
            f"test_steps.config for {key}", stored, {"method": method, "path": path}
        )

    extract = configs.get(EXTRACT_STEP_KEY, {}).get("config")
    report.equal("the extract step's config holds no target", extract, {})

    assert_config = configs.get(ASSERT_STEP_KEY, {}).get("config")
    report.equal("the assert step's config holds no target", assert_config, {})

    report.equal("the plan stored one scenario", (await plan_row_count(PLAN_PUBLIC_ID))[0], 1)
    report.equal(
        "the plan stored every step",
        (await plan_row_count(PLAN_PUBLIC_ID))[1],
        len(VERB_STEPS) + 2,
    )

    # The snapshot still says exactly what the payload said -- the legacy path.
    targets = await run_targets(run_id)
    for key, method, path in VERB_STEPS:
        row = targets.get(key, {})
        report.equal(f"run_steps.method for {key} (from the payload)", row.get("method"), method)
        report.equal(f"run_steps.path for {key} (from the payload)", row.get("path"), path)

    report.check(
        "the extract step's snapshot has no target",
        targets.get(EXTRACT_STEP_KEY, {}).get("method") is None
        and targets.get(EXTRACT_STEP_KEY, {}).get("path") is None,
        targets.get(EXTRACT_STEP_KEY),
    )
    report.check(
        "the assert step's snapshot has no target",
        targets.get(ASSERT_STEP_KEY, {}).get("method") is None
        and targets.get(ASSERT_STEP_KEY, {}).get("path") is None,
        targets.get(ASSERT_STEP_KEY),
    )

    body = await wait_for_terminal(client, run_id)
    report.equal("the run that stated its targets passed", body["status"], "passed")

    for _key, method, path in VERB_STEPS:
        report.check(
            f"the executor called {method} {path}",
            HITS.get((method, path), 0) >= 1,
            dict(HITS),
        )

    return run_id


async def check_recovery(client: httpx.AsyncClient, report: Report, base_url: str) -> str:
    """The same plan, sent again with no targets: the snapshot recovers them.

    This is the Phase 8.2 shape in miniature -- the plan is already in
    `test_steps`, so the server must be able to say what each request step
    calls without being told.
    """
    before_rows = await plan_row_count(PLAN_PUBLIC_ID)
    before_configs = await plan_configs(PLAN_PUBLIC_ID)
    before_hits = dict(HITS)

    run_id = await create_run(
        client, PLAN_PUBLIC_ID, [verb_scenario(with_targets=False)], base_url
    )

    after_rows = await plan_row_count(PLAN_PUBLIC_ID)
    report.equal("reusing the plan stored no second scenario", after_rows[0], before_rows[0])
    report.equal("reusing the plan stored no second step", after_rows[1], before_rows[1])
    report.equal(
        "reusing the plan rewrote no config",
        await plan_configs(PLAN_PUBLIC_ID),
        before_configs,
    )

    targets = await run_targets(run_id)
    for key, method, path in VERB_STEPS:
        row = targets.get(key, {})
        report.equal(f"run_steps.method for {key} (recovered)", row.get("method"), method)
        report.equal(f"run_steps.path for {key} (recovered)", row.get("path"), path)

    report.check(
        "the extract step recovered no target",
        targets.get(EXTRACT_STEP_KEY, {}).get("method") is None
        and targets.get(EXTRACT_STEP_KEY, {}).get("path") is None,
        targets.get(EXTRACT_STEP_KEY),
    )
    report.check(
        "the assert step recovered no target",
        targets.get(ASSERT_STEP_KEY, {}).get("method") is None
        and targets.get(ASSERT_STEP_KEY, {}).get("path") is None,
        targets.get(ASSERT_STEP_KEY),
    )

    body = await wait_for_terminal(client, run_id)
    report.equal("the run that stated no targets passed", body["status"], "passed")

    for _key, method, path in VERB_STEPS:
        report.check(
            f"the executor called the recovered {method} {path}",
            HITS.get((method, path), 0) >= before_hits.get((method, path), 0) + 1,
            dict(HITS),
        )

    return run_id


async def check_non_request_steps(report: Report) -> None:
    """`extract` / `assert` steps never carry a target.

    Only a `request` step has a request to describe, so only it gets the pair;
    the other kinds keep the empty object they have always had.
    """
    configs = await plan_configs(PLAN_PUBLIC_ID)

    for key in (EXTRACT_STEP_KEY, ASSERT_STEP_KEY):
        stored = configs.get(key, {})
        report.equal(f"{key} stores an empty config", stored.get("config"), {})
        report.check(
            f"{key} is stored as a non-request step",
            stored.get("type") in ("extract", "assert"),
            stored,
        )


async def check_nothing_is_invented(
    client: httpx.AsyncClient, report: Report, base_url: str
) -> str:
    """A request step with no target anywhere stays empty and fails as before."""
    run_id = await create_run(
        client, EMPTY_PLAN_PUBLIC_ID, [targetless_scenario()], base_url
    )

    configs = await plan_configs(EMPTY_PLAN_PUBLIC_ID)
    report.equal(
        "a request step with no target stores an empty config",
        configs["nowhere__0"]["config"],
        {},
    )

    row = (await run_targets(run_id)).get("nowhere__0", {})
    report.check("the snapshot invents no method", row.get("method") is None, row)
    report.check("the snapshot invents no path", row.get("path") is None, row)

    body = await wait_for_terminal(client, run_id)
    report.equal("the targetless run failed", body["status"], "failed")

    row = (await run_targets(run_id)).get("nowhere__0", {})
    report.equal("the targetless step failed", row.get("status"), "failed")
    report.equal(
        "the targetless step failed as not-executable",
        row.get("error_code"),
        "not-executable",
    )

    return run_id


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()

    print("verifying the request target a persisted plan carries\n")

    server, base_url = start_target_server()

    try:
        await ensure_fixture(base_url)

        app = create_app()
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
            await check_schema_untouched(report)
            await check_persistence(client, report, base_url)
            await check_recovery(client, report, base_url)
            await check_non_request_steps(report)
            await check_nothing_is_invented(client, report, base_url)
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
