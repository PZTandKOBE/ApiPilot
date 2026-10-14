"""End-to-end verification of the server-side agent foundation.

Phase 8.2 Step 2.  Same shape as the other `verify_*.py` scripts -- a real
PostgreSQL, the real ASGI app, the real exception handlers, tasks created through
the real endpoint -- with one more instrument: a **real HTTP server** on the
loopback interface that the probe environment points at.  The agent must never
call it, and "no request arrived" is a fact about a socket rather than a claim
about the code.

What is being verified, in the order the checks run:

    1. an agent task row exists, with the fields the request carried
    2. the lifecycle: pending -> analyzing -> completed
    3. the plan it produced is a draft
    4. test_plans.agent_task_id points back at the task
    5. the scenario / step / assertion rows are the plan's
    6. every request step's method and path reached test_steps.config
    7. a plan the validator refuses writes no rows and fails the task
    8. a second prompt for the same document does not overwrite the first plan
    9. the same document and prompt produce the same keys and structure
   10. no variable value reaches any of the five tables

Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_agent_foundation.py

It writes projects of its own (`prj_verify_agent`, `prj_verify_agent_bad`) and
deletes them again -- including on failure.  It does not touch any other
project's rows.

Two checks observe the running pipeline rather than its result, and both wrap a
function instead of replacing one: the wrapper records what it sees and then
calls the original, so the code under test is the code that ships.
"""

from __future__ import annotations

import asyncio
import hashlib
import datetime
import json
import os
import socket
import sys
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("AGENT_ANALYZER", "deterministic")
os.environ.setdefault("AGENT_PLANNER", "deterministic")
"""This script checks the pipeline's shape, not the model's judgement.  Since
Phase 8.3 the analyze and plan stages default to DeepSeek, and a suite that
needed a key and a network would stop being a regression suite.  The model paths
have their own verification, with a stubbed client."""

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.schemas.agent import AgentTaskCreateRequest  # noqa: E402
from backend.services import agent, agent_plan  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_verify_agent"
BAD_PROJECT_PUBLIC_ID = "prj_verify_agent_bad"
ENVIRONMENT_PUBLIC_ID = "env_verify_agent"

GUEST_TOKEN = "agent-foundation-guest-session"
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

AGENT_SECRET_NAME = "verify_agent_secret"
AGENT_SECRET_VALUE = "s3cr3t-agent-do-not-store"
REQUEST_SECRET_NAME = "secret_token"
REQUEST_SECRET_VALUE = "s3cr3t-request-do-not-store"

TITLE = "Verify Agent API"
"""The probe document: a login that mints a token, an identity endpoint, and a
collection with an item endpoint under it."""

DOCUMENT = {
    "openapi": "3.0.3",
    "info": {"title": TITLE, "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "components": {
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "Order": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            }
        },
    },
    "security": [{"bearerAuth": []}],
    "paths": {
        "/auth/login": {
            "post": {
                "tags": ["auth"],
                "summary": "Exchange credentials for a token",
                "security": [],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["token"],
                                    "properties": {"token": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/me": {
            "get": {
                "tags": ["auth"],
                "summary": "The identity behind the token",
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/orders": {
            "get": {
                "tags": ["orders"],
                "summary": "List orders",
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "tags": ["orders"],
                "summary": "Create an order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["total", "currency"],
                                "properties": {
                                    "total": {"type": "number", "minimum": 1},
                                    "currency": {"type": "string", "enum": ["EUR", "USD"]},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Order"}
                            }
                        },
                    }
                },
            },
        },
        "/orders/{orderId}": {
            "get": {
                "tags": ["orders"],
                "summary": "Read one order",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}

BAD_TITLE = "Verify Agent Bad API"
BAD_DOCUMENT = {
    "openapi": "3.0.3",
    "info": {"title": BAD_TITLE, "version": "1.0.0"},
    "paths": {"/anything": {"get": {"responses": {"200": {"description": "ok"}}}}},
}

TERMINAL = ("completed", "failed")

PLAN_ID = f"plan_{slugify(TITLE)}_{hash_string(json.dumps(DOCUMENT))}"
BAD_PLAN_ID = f"plan_{slugify(BAD_TITLE)}_{hash_string(json.dumps(BAD_DOCUMENT))}"
SPEC_ID = f"spec_{slugify(TITLE)}_{hash_string(json.dumps(DOCUMENT))}"
BAD_SPEC_ID = f"spec_{slugify(BAD_TITLE)}_{hash_string(json.dumps(BAD_DOCUMENT))}"

TABLES = (
    "agent_tasks",
    "test_plans",
    "test_scenarios",
    "test_steps",
    "test_assertions",
)

HITS: list[str] = []
"""Every request the target server received.  The agent must leave this empty."""


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


class _TargetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - silence the default log
        return

    def _record(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        HITS.append(f"{method} {urlsplit(self.path).path}")
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the name is the stdlib's
        self._record("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._record("POST")


def start_target_server() -> tuple[ThreadingHTTPServer, str]:
    """A real HTTP server, on a port the OS picked for us."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TargetHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    host, port = server.server_address[:2]
    assert host == "127.0.0.1", host  # noqa: S101 - a bound socket, not user input
    assert isinstance(port, int)  # noqa: S101

    with socket.create_connection(("127.0.0.1", port), timeout=5):
        pass

    return server, f"http://127.0.0.1:{port}"

# --------------------------------------------------------------------------- #
# Fixture
# --------------------------------------------------------------------------- #

LIFECYCLE_TITLE = "Verify Agent Lifecycle API"
LIFECYCLE_DOCUMENT = {
    "openapi": "3.0.3",
    "info": {"title": LIFECYCLE_TITLE, "version": "1.0.0"},
    "paths": {"/ping": {"get": {"responses": {"204": {"description": "no content"}}}}},
}


def _document(*, title: str, paths: dict[str, Any]) -> str:
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": title, "version": "1.0.0"},
            "paths": paths,
        }
    )


async def ensure_fixture(base_url: str) -> None:
    """Two probe projects: the working one, and one for the refusal checks.

    The bad project exists so that a *different* plan id can be refused without
    disturbing the plan the other checks read.
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

        for public_id, name, with_variable in (
            (PROJECT_PUBLIC_ID, "Verify agent foundation", True),
            (BAD_PROJECT_PUBLIC_ID, "Verify agent refusals", False),
        ):
            project_id = (
                await connection.execute(
                    text(
                        "INSERT INTO projects (id, guest_session_id, public_id, name) "
                        "VALUES (:id, :guest, :public_id, :name) RETURNING id"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "guest": guest_id,
                        "public_id": public_id,
                        "name": name,
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
                        "name": "Agent target",
                        "base_url": base_url,
                    },
                )
            ).scalar_one()

            if not with_variable:
                continue

            await connection.execute(
                text(
                    "INSERT INTO environment_variables "
                    "(id, environment_id, key, value_encrypted, is_secret, enabled) "
                    "VALUES (:id, :environment, :key, :value, true, true)"
                ),
                {
                    "id": uuid.uuid4(),
                    "environment": environment_id,
                    "key": AGENT_SECRET_NAME,
                    "value": AGENT_SECRET_VALUE,
                },
            )


async def cleanup_fixture() -> None:
    """Remove the probe projects and everything under them, in dependency order."""
    async with engine.begin() as connection:
        for public_id in (PROJECT_PUBLIC_ID, BAD_PROJECT_PUBLIC_ID):
            project_id = (
                await connection.execute(
                    text("SELECT id FROM projects WHERE public_id = :public_id"),
                    {"public_id": public_id},
                )
            ).scalar_one_or_none()

            if project_id is None:
                continue

            for statement in (
                "DELETE FROM test_runs WHERE project_id = :project",
                "DELETE FROM agent_tasks WHERE project_id = :project",
                "DELETE FROM test_plans WHERE project_id = :project",
                "DELETE FROM api_specs WHERE project_id = :project",
                "DELETE FROM environments WHERE project_id = :project",
                "DELETE FROM projects WHERE id = :project",
            ):
                await connection.execute(text(statement), {"project": project_id})


# --------------------------------------------------------------------------- #
# Driving the API
# --------------------------------------------------------------------------- #


def payload_for(
    *,
    project_id: str = PROJECT_PUBLIC_ID,
    document: str,
    spec_id: str,
    prompt: str,
    variables: dict[str, str] | None = None,
    environment: bool = True,
) -> dict[str, Any]:
    return {
        "projectId": project_id,
        "specId": spec_id,
        "specDocument": document,
        "environmentId": ENVIRONMENT_PUBLIC_ID if environment else None,
        "prompt": prompt,
        "variables": variables or {},
    }


async def post_task(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post(
        f"/api/projects/{body['projectId']}/agent/tasks", json=body
    )


# --------------------------------------------------------------------------- #
# Reading the database
# --------------------------------------------------------------------------- #


async def task_row(task_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT agent_tasks.id::text AS id,
                           agent_tasks.status,
                           agent_tasks.prompt,
                           agent_tasks.created_at,
                           agent_tasks.updated_at,
                           projects.public_id AS project_public_id,
                           environments.public_id AS environment_public_id,
                           api_specs.slug,
                           api_specs.content
                    FROM agent_tasks
                    JOIN projects ON projects.id = agent_tasks.project_id
                    JOIN api_specs ON api_specs.id = agent_tasks.spec_id
                    LEFT JOIN environments ON environments.id = agent_tasks.environment_id
                    WHERE agent_tasks.id = :task
                    """
                ),
                {"task": uuid.UUID(task_id)},
            )
        ).mappings().one_or_none()

    return dict(row) if row is not None else None


async def status_of(task_id: str) -> str:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text("SELECT status FROM agent_tasks WHERE id = :task"),
                {"task": uuid.UUID(task_id)},
            )
        ).scalar_one()


async def plan_row(plan_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT test_plans.id::text AS id,
                           test_plans.public_id,
                           test_plans.status,
                           test_plans.risk_level,
                           test_plans.source,
                           test_plans.name,
                           test_plans.agent_task_id::text AS agent_task_id,
                           test_plans.approved_at,
                           test_plans.rejected_at,
                           test_plans.created_at,
                           test_plans.updated_at
                    FROM test_plans
                    WHERE test_plans.public_id = :plan
                    """
                ),
                {"plan": plan_id},
            )
        ).mappings().one_or_none()

    return dict(row) if row is not None else None


async def plan_rows(plan_id: str) -> dict[str, list[dict[str, Any]]]:
    """Every row under a plan, in the order the tree declares."""
    async with AsyncSessionLocal() as session:
        scenarios = (
            await session.execute(
                text(
                    """
                    SELECT test_scenarios.scenario_key, test_scenarios.sort_order,
                           test_scenarios.risk_level, test_scenarios.name
                    FROM test_scenarios
                    JOIN test_plans ON test_plans.id = test_scenarios.plan_id
                    WHERE test_plans.public_id = :plan
                    ORDER BY test_scenarios.sort_order
                    """
                ),
                {"plan": plan_id},
            )
        ).mappings().all()

        steps = (
            await session.execute(
                text(
                    """
                    SELECT test_scenarios.scenario_key,
                           test_steps.step_key,
                           test_steps.step_type,
                           test_steps.sort_order,
                           test_steps.produces,
                           test_steps.consumes,
                           test_steps.config
                    FROM test_steps
                    JOIN test_scenarios ON test_scenarios.id = test_steps.scenario_id
                    JOIN test_plans ON test_plans.id = test_scenarios.plan_id
                    WHERE test_plans.public_id = :plan
                    ORDER BY test_scenarios.sort_order, test_steps.sort_order
                    """
                ),
                {"plan": plan_id},
            )
        ).mappings().all()

        assertions = (
            await session.execute(
                text(
                    """
                    SELECT test_scenarios.scenario_key,
                           test_assertions.assertion_key,
                           test_assertions.assertion_type,
                           test_assertions.target,
                           test_assertions.expected_value,
                           test_assertions.step_id
                    FROM test_assertions
                    JOIN test_scenarios ON test_scenarios.id = test_assertions.scenario_id
                    JOIN test_plans ON test_plans.id = test_scenarios.plan_id
                    WHERE test_plans.public_id = :plan
                    ORDER BY test_scenarios.sort_order, test_assertions.assertion_key
                    """
                ),
                {"plan": plan_id},
            )
        ).mappings().all()

    return {
        "scenarios": [dict(row) for row in scenarios],
        "steps": [dict(row) for row in steps],
        "assertions": [dict(row) for row in assertions],
    }


async def stored_text(project_public_id: str) -> str:
    """Every column of the five agent tables, as text.

    The leak check reads what is *stored*, not what a serializer would emit: a
    value that reached a JSONB description is in here, whatever the API returns.
    """
    statements = (
        "SELECT to_jsonb(agent_tasks)::text FROM agent_tasks "
        "JOIN projects ON projects.id = agent_tasks.project_id WHERE projects.public_id = :project",
        "SELECT to_jsonb(test_plans)::text FROM test_plans "
        "JOIN projects ON projects.id = test_plans.project_id WHERE projects.public_id = :project",
        "SELECT to_jsonb(test_scenarios)::text FROM test_scenarios "
        "JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id WHERE projects.public_id = :project",
        "SELECT to_jsonb(test_steps)::text FROM test_steps "
        "JOIN test_scenarios ON test_scenarios.id = test_steps.scenario_id "
        "JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id WHERE projects.public_id = :project",
        "SELECT to_jsonb(test_assertions)::text FROM test_assertions "
        "JOIN test_scenarios ON test_scenarios.id = test_assertions.scenario_id "
        "JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id WHERE projects.public_id = :project",
    )

    async with AsyncSessionLocal() as session:
        chunks: list[str] = []
        for statement in statements:
            chunks.extend(
                (await session.execute(text(statement), {"project": project_public_id})).scalars().all()
            )

    return "\n".join(chunks)


_EXECUTION_SCOPED = {
    "test_runs": "test_runs JOIN projects ON projects.id = test_runs.project_id",
    "run_scenarios": (
        "run_scenarios JOIN test_runs ON test_runs.id = run_scenarios.run_id "
        "JOIN projects ON projects.id = test_runs.project_id"
    ),
    "run_steps": (
        "run_steps JOIN run_scenarios ON run_scenarios.id = run_steps.run_scenario_id "
        "JOIN test_runs ON test_runs.id = run_scenarios.run_id "
        "JOIN projects ON projects.id = test_runs.project_id"
    ),
    "run_assertions": (
        "run_assertions JOIN run_scenarios ON run_scenarios.id = run_assertions.run_scenario_id "
        "JOIN test_runs ON test_runs.id = run_scenarios.run_id "
        "JOIN projects ON projects.id = test_runs.project_id"
    ),
    "run_events": (
        "run_events JOIN test_runs ON test_runs.id = run_events.run_id "
        "JOIN projects ON projects.id = test_runs.project_id"
    ),
}


async def execution_rows(project_public_id: str) -> int:
    """Rows in the execution tables for a project: the agent must write none.

    `run_steps` and `run_assertions` carry no `run_id` -- they hang off a run
    scenario -- so each table is reached by the path its own foreign keys spell
    out rather than by one shared join.
    """
    async with AsyncSessionLocal() as session:
        total = 0
        for statement in _EXECUTION_SCOPED.values():
            total += (
                await session.execute(
                    text(
                        f"SELECT count(*) FROM {statement} WHERE projects.public_id = :project"
                    ),
                    {"project": project_public_id},
                )
            ).scalar_one()

    return total


_PROJECT_SCOPED = {
    "agent_tasks": (
        "agent_tasks JOIN projects ON projects.id = agent_tasks.project_id"
    ),
    "test_plans": (
        "test_plans JOIN projects ON projects.id = test_plans.project_id"
    ),
    "test_scenarios": (
        "test_scenarios JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id"
    ),
    "test_steps": (
        "test_steps JOIN test_scenarios ON test_scenarios.id = test_steps.scenario_id "
        "JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id"
    ),
    "test_assertions": (
        "test_assertions JOIN test_scenarios ON test_scenarios.id = test_assertions.scenario_id "
        "JOIN test_plans ON test_plans.id = test_scenarios.plan_id "
        "JOIN projects ON projects.id = test_plans.project_id"
    ),
}
"""Every agent table reaches its project through a different path: two carry a
@@project_id@@ of their own and the other two only hang off a scenario."""


async def plan_count(plan_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM test_plans WHERE public_id = :plan"),
                {"plan": plan_id},
            )
        ).scalar_one()


async def project_row_count(project_public_id: str, table: str) -> int:
    statement = (
        f"SELECT count(*) FROM {_PROJECT_SCOPED[table]} WHERE projects.public_id = :project"
    )

    async with AsyncSessionLocal() as session:
        return (await session.execute(text(statement), {"project": project_public_id})).scalar_one()

def pipeline(document: str, *, project_id: str, spec_id: str):
    """The three stage functions, called exactly as the service calls them."""
    parsed = agent_plan.parse_document(
        agent_plan.decode_document(document),
        project_id=project_id,
        spec_id=spec_id,
        slug=spec_id.removeprefix("spec_"),
        filename="verify.json",
        source="upload",
    )
    understanding = agent_plan.analyze(parsed)

    return agent_plan.generate_plan(understanding, parsed.spec, source="generated")


def comparable(plan: Any) -> dict[str, Any]:
    """A plan without the one field that is a timestamp by design."""
    dumped = plan.model_dump(mode="json")
    # model_dump() names fields, not aliases: the timestamp is `generated_at`.
    dumped.pop("generated_at", None)
    dumped.pop("generatedAt", None)

    return dumped


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

PROMPT = "Prove the order lifecycle holds and the token is required."


async def check_task_created(
    client: httpx.AsyncClient, report: Report
) -> tuple[str, dict[str, Any]]:
    """Test 1: one task row, with everything the request carried."""
    body = payload_for(
        document=json.dumps(DOCUMENT),
        spec_id=SPEC_ID,
        prompt=PROMPT,
        variables={REQUEST_SECRET_NAME: REQUEST_SECRET_VALUE},
    )
    response = await post_task(client, body)

    report.equal("the task endpoint answers 201", response.status_code, 201)
    task = response.json()

    row = await task_row(task["id"])
    report.check("the agent_tasks row exists", row is not None)
    report.equal("the task stores the prompt verbatim", row["prompt"], PROMPT)
    report.equal("the task is stored under the project", row["project_public_id"], PROJECT_PUBLIC_ID)
    report.equal("the task stores the environment", row["environment_public_id"], ENVIRONMENT_PUBLIC_ID)
    report.equal("the task is anchored to the document's spec row", row["slug"], SPEC_ID.removeprefix("spec_"))
    report.equal("the task stored the document it read", row["content"], json.dumps(DOCUMENT))
    report.check(
        "the task carries both timestamps",
        row["created_at"] is not None and row["updated_at"] is not None,
    )
    report.equal("the response's id is the row's id", task["id"], row["id"])
    report.equal("the response does not echo the variables", "variables" in task, False)

    # The understanding is the other half of what the console renders, and it
    # exists only on this response -- nothing persists it.
    understanding = task["understanding"]
    report.check("the create response carries the understanding", understanding is not None)
    report.equal("the understanding names the spec", understanding["specId"], SPEC_ID)
    report.equal(
        "the understanding lists every endpoint",
        [endpoint["id"] for endpoint in understanding["endpoints"]],
        [
            "ep_post_auth_login",
            "ep_get_me",
            "ep_get_orders",
            "ep_post_orders",
            "ep_get_orders_orderid",
        ],
    )
    report.equal(
        "the understanding groups the endpoints into resources",
        [resource["name"] for resource in understanding["resources"]],
        ["auth", "orders"],
    )
    report.equal(
        "the understanding names the token source",
        understanding["authentication"]["tokenSourceEndpointId"],
        "ep_post_auth_login",
    )
    report.equal(
        "the understanding found the token field",
        understanding["authentication"]["tokenField"],
        "token",
    )
    report.check(
        "the understanding traced the token dependency",
        any(
            dependency["kind"] == "token"
            and dependency["fromEndpointId"] == "ep_post_auth_login"
            for dependency in understanding["dependencies"]
        ),
        understanding["dependencies"],
    )
    report.check(
        "the understanding lists the risks it found",
        any(risk["category"] == "negative-coverage" for risk in understanding["risks"]),
        [risk["category"] for risk in understanding["risks"]],
    )
    report.equal(
        "the understanding reports one finding per stage",
        [finding["id"] for finding in understanding["findings"]],
        ["finding_parse", "finding_authentication", "finding_dependencies", "finding_risks"],
    )
    report.check(
        "every finding carries its evidence",
        all(len(finding["evidence"]) >= 1 for finding in understanding["findings"]),
    )

    return task["id"], task


async def check_lifecycle(client: httpx.AsyncClient, report: Report) -> None:
    """Test 2: pending -> analyzing -> completed, observed at three points."""
    document = json.dumps(LIFECYCLE_DOCUMENT)
    spec_id = f"spec_{slugify(LIFECYCLE_TITLE)}_{hash_string(document)}"
    request = AgentTaskCreateRequest(
        **payload_for(document=document, spec_id=spec_id, prompt="Lifecycle", variables={})
    )

    async with AsyncSessionLocal() as session:
        task_id = await agent.create_task(session, project_id=PROJECT_PUBLIC_ID, payload=request)

    report.equal("a task that has been created is pending", await status_of(str(task_id)), "pending")

    observed: list[str] = []
    original = agent._persist

    async def watching(*args: Any, **kwargs: Any) -> Any:
        observed.append(await status_of(str(task_id)))
        return await original(*args, **kwargs)

    agent._persist = watching  # type: ignore[assignment]
    try:
        async with AsyncSessionLocal() as session:
            result = await agent.process_task(session, task_id=task_id)
    finally:
        agent._persist = original

    report.equal("the pipeline ran while the task was analyzing", observed, ["analyzing"])
    report.equal("the task ends completed", result.status, "completed")
    report.equal("the stored status agrees", await status_of(str(task_id)), "completed")


async def check_plan(report: Report, task_id: str, task: dict[str, Any]) -> None:
    """Tests 3, 4 and 5: a draft, linked to its task, with the plan's rows."""
    plan = await plan_row(PLAN_ID)
    report.check("the plan row exists", plan is not None)

    report.equal("the plan is a draft", plan["status"], "draft")
    report.check(
        "the plan has never been approved or rejected",
        plan["approved_at"] is None and plan["rejected_at"] is None,
    )
    report.equal("the plan points back at its task", plan["agent_task_id"], task_id)
    report.equal("the response calls the plan a draft", task["plan"]["status"], "draft")
    report.equal("the response names the plan by its stable id", task["plan"]["id"], PLAN_ID)

    rows = await plan_rows(PLAN_ID)
    scenarios, steps, assertions = rows["scenarios"], rows["steps"], rows["assertions"]

    report.equal("six scenarios were stored", len(scenarios), 6)
    report.equal("fourteen steps were stored", len(steps), 14)
    report.equal("eight assertions were stored", len(assertions), 8)
    # The response carries the tree the console reviews, not a count of it.
    tree = task["plan"]["scenarios"]
    report.equal("the response carries six scenarios", len(tree), 6)
    report.equal(
        "the response carries every step",
        sum(len(scenario["steps"]) for scenario in tree),
        14,
    )
    report.equal(
        "the response carries every assertion",
        sum(len(scenario["assertions"]) for scenario in tree),
        8,
    )
    report.equal(
        "the response's scenario keys are the stored ones",
        [scenario["id"] for scenario in tree],
        [row["scenario_key"] for row in scenarios],
    )
    report.equal(
        "the response's step keys are the stored ones",
        [step["id"] for scenario in tree for step in scenario["steps"]],
        [row["step_key"] for row in steps],
    )
    report.equal(
        "the response's request targets are the stored config",
        [
            (step["method"], step["path"])
            for scenario in tree
            for step in scenario["steps"]
            if step["kind"] == "request"
        ],
        [
            (row["config"].get("method"), row["config"].get("path"))
            for row in steps
            if row["step_type"] == "request"
        ],
    )
    report.check(
        "every plan step says it has no endpoint id, because none is stored",
        all(
            step["endpointId"] is None
            for scenario in tree
            for step in scenario["steps"]
        ),
    )
    generated = task["plan"]["generatedAt"]
    report.equal(
        "the response dates the plan when the row was written",
        datetime.datetime.fromisoformat(generated.replace("Z", "+00:00")),
        plan["created_at"],
    )
    # The same spelling the run contract fixes: a plan is handed to create-run,
    # and that contract's timestamps carry Z rather than an offset.
    report.check("the plan's date is spelled with Z", generated.endswith("Z"), generated)
    report.equal(
        "the response echoes the project and the spec",
        (task["plan"]["projectId"], task["plan"]["specId"]),
        (PROJECT_PUBLIC_ID, SPEC_ID),
    )

    keys = [row["scenario_key"] for row in scenarios]
    report.equal("scenario keys are unique", len(set(keys)), len(keys))
    report.equal("scenario order is dense from one", [row["sort_order"] for row in scenarios], list(range(1, 7)))
    report.check(
        "the plan opens with the authentication scenario",
        keys[0] == "scenario_authentication",
        keys,
    )
    report.check(
        "every endpoint got a smoke scenario",
        sum(1 for key in keys if key.startswith("scenario_smoke_")) == 5,
        keys,
    )

    for scenario_key in set(keys):
        own = [row for row in steps if row["scenario_key"] == scenario_key]
        report.equal(
            f"{scenario_key} step order is dense from zero",
            [row["sort_order"] for row in own],
            list(range(len(own))),
        )
        report.equal(
            f"{scenario_key} step keys are unique",
            len({row["step_key"] for row in own}),
            len(own),
        )

    report.equal("all three step kinds are stored", {row["step_type"] for row in steps}, {"request", "extract", "assert"})
    report.equal(
        "the assertion kinds are the executable ones",
        {row["assertion_type"] for row in assertions},
        {"status", "field"},
    )
    report.check(
        "every assertion is scenario-level",
        all(row["step_id"] is None for row in assertions),
    )
    report.check(
        "assertion expected values are strings",
        all(isinstance(row["expected_value"], str) for row in assertions),
        [row["expected_value"] for row in assertions],
    )

    extract = [row for row in steps if row["step_type"] == "extract"]
    report.equal("one extract step was stored", len(extract), 1)
    report.equal("the extract step produces the token field", extract[0]["produces"], "token")
    report.check(
        "the identity call consumes the token it lifted",
        any(row["step_type"] == "request" and "token" in (row["consumes"] or []) for row in steps),
    )


async def check_step_config(report: Report) -> None:
    """Test 6: every request step's method and path reached test_steps.config."""
    rows = await plan_rows(PLAN_ID)
    request_steps = [row for row in rows["steps"] if row["step_type"] == "request"]

    report.equal("seven request steps were stored", len(request_steps), 7)

    for row in request_steps:
        config = row["config"]
        report.check(
            f"config for {row['step_key']} is a method/path pair",
            set(config) == {"method", "path"} and isinstance(config["method"], str) and isinstance(config["path"], str),
            config,
        )

    for row in rows["steps"]:
        if row["step_type"] == "request":
            continue
        report.equal(f"{row['step_type']} step {row['step_key']} stored no target", row["config"], {})

    placeholder = [
        row for row in request_steps if row["config"].get("path") == "/orders/{{orderId}}"
    ]
    report.equal("the path parameter became a variable placeholder", len(placeholder), 1)
    report.check(
        "the placeholder is declared in consumes",
        placeholder and "orderId" in (placeholder[0]["consumes"] or []),
        placeholder,
    )


async def check_refusal(client: httpx.AsyncClient, report: Report) -> None:
    """Test 7: a plan the validator refuses writes nothing and fails the task."""
    before = {
        table: await project_row_count(BAD_PROJECT_PUBLIC_ID, table)
        for table in ("test_plans",)
    }

    original = agent_plan.generate_plan

    def broken(understanding: Any, spec: Any, *, source: str = "generated") -> Any:
        plan = original(understanding, spec, source=source)
        # Three contract violations at once: a plan that is not a draft, two
        # steps wearing one id, and a request step that names no request.
        hacked = plan.model_copy(deep=True)
        hacked.status = "approved"
        hacked.scenarios[0].steps[1].id = hacked.scenarios[0].steps[0].id
        hacked.scenarios[0].steps[0].method = None

        return hacked

    agent_plan.generate_plan = broken  # type: ignore[assignment]
    try:
        response = await post_task(
            client,
            payload_for(
                project_id=BAD_PROJECT_PUBLIC_ID,
                document=json.dumps(BAD_DOCUMENT),
                spec_id=BAD_SPEC_ID,
                prompt="This plan must be refused.",
            ),
        )
    finally:
        agent_plan.generate_plan = original

    report.equal("a refused plan answers 422", response.status_code, 422)
    body = response.json()
    report.equal("the refusal is a validation failure", body["code"], "plan-invalid")
    report.equal(
        "the refusal renders a sentence the frontend has",
        body["messageKey"],
        "console.aiTest.errors.generateFailed",
    )

    async with AsyncSessionLocal() as session:
        tasks = (
            await session.execute(
                text(
                    "SELECT agent_tasks.status FROM agent_tasks "
                    "JOIN projects ON projects.id = agent_tasks.project_id "
                    "WHERE projects.public_id = :project"
                ),
                {"project": BAD_PROJECT_PUBLIC_ID},
            )
        ).scalars().all()

    report.equal("the refused task is recorded once", len(tasks), 1)
    report.equal("the refused task failed", tasks[0], "failed")

    for table in ("test_plans", "test_scenarios", "test_steps", "test_assertions"):
        report.equal(f"nothing was written to {table}", await project_row_count(BAD_PROJECT_PUBLIC_ID, table), 0)

    report.equal("the refused plan never appeared", await project_row_count(BAD_PROJECT_PUBLIC_ID, "test_plans"), before["test_plans"])


async def check_no_overwrite(client: httpx.AsyncClient, report: Report) -> None:
    """Test 8: the same document again is refused, and the plan is untouched."""
    before_plan = await plan_row(PLAN_ID)
    before_rows = await plan_rows(PLAN_ID)
    before_tasks = await project_row_count(PROJECT_PUBLIC_ID, "agent_tasks")

    response = await post_task(
        client,
        payload_for(
            document=json.dumps(DOCUMENT),
            spec_id=SPEC_ID,
            prompt="A different prompt, the same document.",
        ),
    )

    report.equal("a second prompt for the same document is refused", response.status_code, 409)
    report.equal("the refusal names the plan it collided with", response.json()["details"]["planId"], PLAN_ID)

    after_plan = await plan_row(PLAN_ID)
    report.equal("the stored plan is unchanged", after_plan, before_plan)
    report.equal("the stored tree is unchanged", await plan_rows(PLAN_ID), before_rows)
    report.equal("only one plan exists for the document", await plan_count(PLAN_ID), 1)
    report.equal(
        "a refused request creates no task",
        await project_row_count(PROJECT_PUBLIC_ID, "agent_tasks"),
        before_tasks,
    )


async def check_determinism(report: Report) -> None:
    """Test 9: the same input produces the same keys and the same structure."""
    document = json.dumps(DOCUMENT)
    first = pipeline(document, project_id=PROJECT_PUBLIC_ID, spec_id=SPEC_ID)
    second = pipeline(document, project_id=PROJECT_PUBLIC_ID, spec_id=SPEC_ID)

    report.check("two runs produce the same plan", comparable(first) == comparable(second))
    report.equal("the plan id is the document's slug", first.id, PLAN_ID)
    report.check(
        "no business key is a UUID",
        not any(
            character.isdigit() and len(part) == 36
            for part in [first.id, *[scenario.id for scenario in first.scenarios]]
            for character in part
        ),
    )

    stored = await plan_rows(PLAN_ID)
    report.equal(
        "the stored scenario keys are the generated ones",
        [row["scenario_key"] for row in stored["scenarios"]],
        [scenario.id for scenario in first.scenarios],
    )
    report.equal(
        "the stored step keys are the generated ones",
        [row["step_key"] for row in stored["steps"]],
        [step.id for scenario in first.scenarios for step in scenario.steps],
    )
    report.equal(
        "the stored assertion keys are the generated ones",
        sorted(row["assertion_key"] for row in stored["assertions"]),
        # Sorted on both sides: assertions have no sort_order column, so the
        # table's order is the reader's choice and only the keys are the fact.
        sorted(assertion.id for scenario in first.scenarios for assertion in scenario.assertions),
    )


async def check_secrets(report: Report, task: dict[str, Any]) -> None:
    """Test 10: no variable value reached a table, or a response."""
    haystack = await stored_text(PROJECT_PUBLIC_ID)
    serialised = json.dumps(task)

    for name, value in (
        (REQUEST_SECRET_NAME, REQUEST_SECRET_VALUE),
        (AGENT_SECRET_NAME, AGENT_SECRET_VALUE),
    ):
        report.check(
            f"the value of {name} is nowhere in the five tables",
            value not in haystack,
            value,
        )
        report.check(f"the value of {name} is not echoed in the response", value not in serialised)

    report.check(
        "the environment variable's name is not a plan path either",
        AGENT_SECRET_NAME not in haystack,
    )


async def check_boundaries(report: Report) -> None:
    """The agent does not execute, does not approve, and speaks the dictionary."""
    report.equal("the agent made no HTTP request", HITS, [])
    report.equal("the agent wrote no execution rows", await execution_rows(PROJECT_PUBLIC_ID), 0)

    plans = await plan_rows(PLAN_ID)
    report.check("the plan holds at least one scenario", len(plans["scenarios"]) > 0)

    locales = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales" / "console"
    for locale in ("en-US.ts", "zh-CN.ts"):
        source = (locales / locale).read_text(encoding="utf-8")
        missing = [
            key
            for key in sorted(agent_plan.AGENT_TEXT_KEYS)
            if f"{key.rsplit('.', 1)[-1]}:" not in source
        ]
        report.equal(f"every authored key has a leaf in {locale}", missing, [])

async def check_read_back(
    client: httpx.AsyncClient, report: Report, task_id: str, task: dict[str, Any]
) -> None:
    """The second route: a task can be read back, and a missing one is a 404."""
    response = await client.get(f"/api/agent/tasks/{task_id}")

    report.equal("the task can be read back", response.status_code, 200)
    body = response.json()
    report.equal("the read agrees on the id", body["id"], task_id)
    report.equal("the read agrees on the status", body["status"], "completed")
    report.equal("the read agrees on the prompt", body["prompt"], task["prompt"])
    report.equal("the read carries the same plan tree", body["plan"], task["plan"])
    report.equal(
        "the read carries no understanding, because none is stored",
        body["understanding"],
        None,
    )
    report.check(
        "the read carries no variables field",
        "variables" not in body,
    )

    missing = await client.get(f"/api/agent/tasks/{uuid.uuid4()}")
    report.equal("an unknown task is a 404", missing.status_code, 404)
    report.equal("an unknown task says so", missing.json()["code"], "task-not-found")

    malformed = await client.get("/api/agent/tasks/not-a-uuid")
    report.equal("a malformed task id is a 404 too", malformed.status_code, 404)

    async with AsyncSessionLocal() as session:
        failed_id = (
            await session.execute(
                text(
                    "SELECT agent_tasks.id::text FROM agent_tasks "
                    "JOIN projects ON projects.id = agent_tasks.project_id "
                    "WHERE projects.public_id = :project AND agent_tasks.status = 'failed'"
                ),
                {"project": BAD_PROJECT_PUBLIC_ID},
            )
        ).scalar_one_or_none()

    report.check("the refused task is readable", failed_id is not None)
    if failed_id is not None:
        failed = await client.get(f"/api/agent/tasks/{failed_id}")
        report.equal("a failed task still reads as 200", failed.status_code, 200)
        report.equal("a failed task reports its status", failed.json()["status"], "failed")
        report.equal("a failed task has no plan", failed.json()["plan"], None)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()

    print("verifying the server-side agent foundation\n")

    server, base_url = start_target_server()

    try:
        await ensure_fixture(base_url)

        app = create_app()
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
            task_id, task = await check_task_created(client, report)
            await check_lifecycle(client, report)
            await check_plan(report, task_id, task)
            await check_step_config(report)
            # The refusal check runs before the read-back one: reading a failed
            # task is only possible once there is one.
            await check_refusal(client, report)
            await check_read_back(client, report, task_id, task)
            await check_no_overwrite(client, report)
            await check_determinism(report)
            await check_secrets(report, task)
            await check_boundaries(report)
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


