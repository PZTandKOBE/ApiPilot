"""End-to-end verification of the agent task audit (Phase 8.4 Step 1).

The whole pipeline again -- real PostgreSQL, real ASGI app, real task lifecycle,
both real prompt assets, the real audit writer, the real read endpoint -- with
stubs in the models' places.  What is verified is what the audit promises:

* **A** a completed task records who ran each stage (provider, model, prompt
  version), what the analysis understood, what the planner designed before the
  runtime completed it, and what each call cost;
* **B** a failed task records the stage, the code and a bounded sentence -- and
  still keeps whatever the model had produced before it failed;
* **C** a deterministic run reports the rule engine, stores no tokens at all, and
  still records the understanding it produced;
* **D** `GET /api/agent/tasks/{task_id}/audit` answers the whole structure;
* **E** nothing a task declared as a run-time value reaches the record, through
  either the API or the table;
* **F** an unknown task is the project's usual 404, and a known task with no
  record says which of the two is missing.

Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_agent_audit.py

It writes a project of its own and deletes it again, including on failure.  It
never calls the real API.
"""

from __future__ import annotations

import asyncio
import hashlib
import copy
import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["AGENT_ANALYZER"] = "deepseek"
os.environ["AGENT_PLANNER"] = "deepseek"
"""Both stages take the model path by default here; individual checks flip the
switches to exercise the rule engine as well."""

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.services import agent_analyzer, agent_plan  # noqa: E402
from backend.services.llm import LLMError, LLMResult  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_verify_audit"
ENVIRONMENT_PUBLIC_ID = "env_verify_audit"

GUEST_TOKEN = "agent-audit-guest-session"
# The fixture inserts the digest the service computes for the token it names:
# the plaintext column is gone (Phase 8.5 Step 2), and these rows are ownership
# anchors for the fixture -- no business route reads an identity yet.
GUEST_TOKEN_HASH = hashlib.sha256(GUEST_TOKEN.encode("utf-8")).hexdigest()

# Every request this suite makes carries the fixture guest's token: the
# business routes verify a guest session (Phase 8.5 Step 3), and a suite that
# sent nothing would be measuring 401s.
GUEST_HEADERS = {"X-Guest-Session": GUEST_TOKEN}

SECRET_NAME = "audit_secret"
SECRET_VALUE = "s3cr3t-audit-must-not-persist"

TITLE = "Verify Audit API"
TASK_PROMPT = "Design the order lifecycle test."

DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": TITLE, "version": "1.0.0"},
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
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
                                    "properties": {"token": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/orders": {
            "get": {
                "tags": ["orders"],
                "summary": "List orders",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


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
# The stubs in the models' places
# --------------------------------------------------------------------------- #


@dataclass
class Call:
    schema_name: str
    instructions: str
    turns: tuple[str, ...]


class StageFake:
    """A model for both stages, or a model that fails on demand."""

    def __init__(
        self,
        understanding: Mapping[str, Any] | None,
        design: Mapping[str, Any] | None,
        *,
        fail_on: str | None = None,
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        self._understanding = understanding
        self._design = design
        self._fail_on = fail_on
        self._usage = usage if usage is not None else {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 60,
            "output_tokens_details": {"reasoning_tokens": 25},
            "total_tokens": 180,
        }
        self.calls: list[Call] = []

    @property
    def model(self) -> str:
        return "fake-audit-model"

    async def complete_json(
        self,
        *,
        instructions: str,
        turns: Sequence[str],
        schema: Mapping[str, Any],
        schema_name: str,
    ) -> LLMResult:
        self.calls.append(Call(schema_name, instructions, tuple(turns)))

        if self._fail_on == schema_name:
            raise LLMError(
                "the model answered 400: " + json.dumps({"error": {"message": "nope"}}),
                status=400,
            )

        answer = self._design if schema_name == agent_analyzer.PLAN_SCHEMA_NAME else self._understanding

        return LLMResult(
            content=copy.deepcopy(dict(answer or {})),
            model=self.model,
            usage=self._usage,
            request_id="resp_fake_audit",
            status="completed",
        )

    @property
    def analyze_calls(self) -> int:
        return sum(1 for call in self.calls if call.schema_name != agent_analyzer.PLAN_SCHEMA_NAME)

    @property
    def plan_calls(self) -> int:
        return sum(1 for call in self.calls if call.schema_name == agent_analyzer.PLAN_SCHEMA_NAME)


_REAL_BUILD_CLIENT = agent_analyzer.build_client


def stubbing(fake: StageFake | None) -> None:
    if fake is None:
        agent_analyzer.build_client = _REAL_BUILD_CLIENT
    else:
        agent_analyzer.build_client = lambda: fake


# --------------------------------------------------------------------------- #
# The fixture document and the answers built from it
# --------------------------------------------------------------------------- #


def document_for(name: str) -> str:
    document = copy.deepcopy(DOCUMENT)
    document["info"]["title"] = f"{TITLE} {name}"

    return json.dumps(document)


def identity_for(name: str) -> tuple[str, str]:
    slug = f"{slugify(TITLE + ' ' + name)}_{hash_string(document_for(name))}"

    return f"spec_{slug}", f"plan_{slug}"


def parsed_for(name: str) -> agent_plan.ParsedSpec:
    spec_id, _ = identity_for(name)

    return agent_plan.parse_document(
        agent_plan.decode_document(document_for(name)),
        project_id=PROJECT_PUBLIC_ID,
        spec_id=spec_id,
        slug=spec_id.removeprefix("spec_"),
        filename="verify-audit.json",
        source="upload",
    )


def understanding_for(parsed: agent_plan.ParsedSpec) -> dict[str, Any]:
    facts = json.loads(agent_analyzer.specification_facts(parsed))
    source = parsed.authentication.token_source_endpoint_id or parsed.endpoints[0].id

    return {
        "specId": parsed.spec.id,
        "endpoints": facts["endpoints"],
        "resources": facts["resources"],
        "authentication": facts["authentication"],
        "dependencies": [
            {
                "id": f"dep_{source}__{parsed.endpoints[-1].id}__token",
                "fromEndpointId": source,
                "toEndpointId": parsed.endpoints[-1].id,
                "kind": "token",
                "binding": "token",
                "rationale": {"text": "The order routes need the token this call returns."},
            }
        ],
        "risks": [
            {
                "id": "risk_fake_authentication",
                "level": "high",
                "category": "authentication",
                "title": {"text": "Every order route needs a credential"},
                "detail": {"text": "Without one the order routes answer 401."},
                "relatedEndpointIds": [parsed.endpoints[-1].id],
                "fields": [],
            }
        ],
        "findings": [
            {
                "id": "finding_fake",
                "action": {"text": "Read the specification"},
                "decisionSummary": {"text": "One credential gates the order routes"},
                "result": "succeeded",
                "evidence": [{"label": {"text": "endpoints"}, "value": str(len(parsed.endpoints))}],
                "at": "2026-01-01T00:00:00Z",
            }
        ],
        "analyzedAt": "2026-01-01T00:00:00Z",
    }


def design_for(parsed: agent_plan.ParsedSpec, **overrides: Any) -> dict[str, Any]:
    by_path = {(endpoint.method, endpoint.path): endpoint for endpoint in parsed.endpoints}
    login = by_path[("POST", "/auth/login")]
    orders = by_path[("GET", "/orders")]

    design: dict[str, Any] = {
        "name": {"text": "Verify the order lifecycle"},
        "goal": {"text": "Prove a credential can be obtained and used on the order routes."},
        "riskLevel": "high",
        "scenarios": [
            {
                "name": {"text": "Authentication"},
                "description": {"text": "Log in and keep the token."},
                "expected": {"text": "The token is returned."},
                "riskLevel": "high",
                "steps": [
                    {
                        "kind": "request",
                        "description": {"text": "Log in."},
                        "endpointId": login.id,
                        "method": login.method,
                        "path": login.path,
                        "produces": None,
                        "consumes": [],
                    },
                    {
                        "kind": "extract",
                        "description": {"text": "Keep the token."},
                        "endpointId": login.id,
                        "method": None,
                        "path": None,
                        "produces": "token",
                        "consumes": [],
                    },
                    {
                        "kind": "request",
                        "description": {"text": "List the orders."},
                        "endpointId": orders.id,
                        "method": orders.method,
                        "path": orders.path,
                        "produces": None,
                        "consumes": ["token"],
                    },
                    {
                        "kind": "assert",
                        "description": {"text": "Check what came back."},
                        "endpointId": None,
                        "method": None,
                        "path": None,
                        "produces": None,
                        "consumes": [],
                    },
                ],
                "assertions": [
                    {
                        "kind": "status",
                        "target": "status",
                        "expected": "200",
                        "description": {"text": "The login succeeds."},
                        "endpointId": login.id,
                    },
                    {
                        "kind": "field",
                        "target": "body.token",
                        "expected": "present",
                        "description": {"text": "A token comes back."},
                        "endpointId": login.id,
                    },
                    {
                        "kind": "status",
                        "target": "status",
                        "expected": "200",
                        "description": {"text": "The list answers 200."},
                        "endpointId": orders.id,
                    },
                ],
            }
        ],
    }
    design.update(overrides)

    return design

# --------------------------------------------------------------------------- #
# The fixture
# --------------------------------------------------------------------------- #


def payload_for(
    name: str, *, prompt: str = TASK_PROMPT, variables: dict[str, str] | None = None
) -> dict[str, Any]:
    spec_id, _ = identity_for(name)

    return {
        "projectId": PROJECT_PUBLIC_ID,
        "specId": spec_id,
        "specDocument": document_for(name),
        "environmentId": ENVIRONMENT_PUBLIC_ID,
        "prompt": prompt,
        "variables": variables if variables is not None else {SECRET_NAME: SECRET_VALUE},
    }


async def ensure_fixture(base_url: str) -> None:
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
                    "name": "Verify agent audit",
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
                    "name": "Audit target",
                    "base_url": base_url,
                },
            )
        ).scalar_one()

        await connection.execute(
            text(
                "INSERT INTO environment_variables "
                "(id, environment_id, key, value_encrypted, is_secret, enabled) "
                "VALUES (:id, :environment, :key, :value, true, true)"
            ),
            {
                "id": uuid.uuid4(),
                "environment": environment_id,
                "key": SECRET_NAME,
                "value": SECRET_VALUE,
            },
        )


async def cleanup_fixture() -> None:
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
            "DELETE FROM agent_tasks WHERE project_id = :project",
            "DELETE FROM test_plans WHERE project_id = :project",
            "DELETE FROM api_specs WHERE project_id = :project",
            "DELETE FROM environments WHERE project_id = :project",
            "DELETE FROM projects WHERE id = :project",
        ):
            await connection.execute(text(statement), {"project": project_id})


class Probe(BaseHTTPRequestHandler):
    """Counts what reaches it.  Nothing should: no stage executes anything."""

    hits = 0

    def do_GET(self) -> None:  # noqa: N802 - the handler's own spelling
        Probe.hits += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_GET  # type: ignore[assignment]

    def log_message(self, *args: Any) -> None:  # pragma: no cover - quiet
        return


def start_target_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Probe)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]

    return server, f"http://{host}:{port}"


# --------------------------------------------------------------------------- #
# Driving the API and reading the record
# --------------------------------------------------------------------------- #


async def post_task(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post(f"/api/projects/{PROJECT_PUBLIC_ID}/agent/tasks", json=body)


async def get_audit(client: httpx.AsyncClient, task_id: str) -> httpx.Response:
    return await client.get(f"/api/agent/tasks/{task_id}/audit")


async def run_task(
    client: httpx.AsyncClient,
    *,
    name: str,
    fake: StageFake | None = None,
    variables: dict[str, str] | None = None,
    document: str | None = None,
) -> tuple[httpx.Response, StageFake]:
    """Post one task with a stub in the models' places."""
    parsed = parsed_for(name)
    stub = fake if fake is not None else StageFake(understanding_for(parsed), design_for(parsed))
    stubbing(stub)

    try:
        response = await post_task(
            client, payload_for(name, variables=variables)
        )
    finally:
        stubbing(None)

    return response, stub


async def audit_row(task_id: str) -> dict[str, Any] | None:
    """The stored row, verbatim, for the checks the API cannot make."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT task_id::text, status, failure_stage, failure_code, failure_message, "
                    "analyzer_provider, analyzer_model, analyzer_prompt, "
                    "planner_provider, planner_model, planner_prompt, "
                    "understanding::text, plan_design::text, usage::text, "
                    "created_at, updated_at "
                    "FROM agent_task_audits WHERE task_id = :task"
                ),
                {"task": uuid.UUID(task_id)},
            )
        ).mappings().one_or_none()

    return dict(row) if row is not None else None


async def audit_count_for_task(task_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM agent_task_audits WHERE task_id = :task"),
                {"task": uuid.UUID(task_id)},
            )
        ).scalar_one()


async def task_count_for_spec(spec_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                text(
                    "SELECT count(*) FROM agent_tasks "
                    "JOIN api_specs ON api_specs.id = agent_tasks.spec_id "
                    "WHERE api_specs.slug = :slug"
                ),
                {"slug": spec_id.removeprefix("spec_")},
            )
        ).scalar_one()


AUDIT_FIELDS = {
    "taskId",
    "status",
    "failureStage",
    "failureCode",
    "failureMessage",
    "analyzer",
    "planner",
    "understanding",
    "planDesign",
    "usage",
    "createdAt",
    "updatedAt",
}


# --------------------------------------------------------------------------- #
# A -- a completed task records the whole decision
# --------------------------------------------------------------------------- #


async def check_completed(client: httpx.AsyncClient, report: Report) -> None:
    name = "completed"
    parsed = parsed_for(name)
    response, fake = await run_task(client, name=name)

    report.equal("A: the task is accepted", response.status_code, 201)
    body = response.json()
    task_id = body.get("id", "")

    audit = await get_audit(client, task_id)
    report.equal("A: the audit is readable", audit.status_code, 200)
    record = audit.json()

    report.check(
        "A: every documented field is present, and nothing else",
        set(record) == AUDIT_FIELDS,
        sorted(record),
    )
    report.equal("A: it belongs to the task", record.get("taskId"), task_id)
    report.equal("A: the pipeline completed", record.get("status"), "completed")
    report.check(
        "A: a completed task carries no failure",
        record.get("failureStage") is None
        and record.get("failureCode") is None
        and record.get("failureMessage") is None,
        {key: record.get(key) for key in ("failureStage", "failureCode", "failureMessage")},
    )

    report.equal(
        "A: the analyzer is named",
        record.get("analyzer"),
        {"provider": "deepseek", "model": "fake-audit-model", "promptVersion": "analyze-v1"},
    )
    report.equal(
        "A: the planner is named too",
        record.get("planner"),
        {
            "provider": "deepseek",
            "model": "fake-audit-model",
            "promptVersion": "generate-plan-v1",
        },
    )

    report.check(
        "A: usage is recorded per stage, with every count the provider reported",
        record.get("usage")
        == {
            "analyze": {
                "inputTokens": 120,
                "cachedInputTokens": 40,
                "outputTokens": 60,
                "reasoningTokens": 25,
                "totalTokens": 180,
            },
            "generatePlan": {
                "inputTokens": 120,
                "cachedInputTokens": 40,
                "outputTokens": 60,
                "reasoningTokens": 25,
                "totalTokens": 180,
            },
        },
        record.get("usage"),
    )

    understanding = record.get("understanding") or {}
    report.equal(
        "A: the understanding is the validated one",
        [finding.get("id") for finding in understanding.get("findings", [])],
        ["finding_fake"],
    )
    report.equal("A: and it is the same one the response carried", understanding, body.get("understanding"))

    design = record.get("plan_design_text") or record.get("planDesign") or {}
    report.equal(
        "A: the design is the one the model proposed",
        [scenario.get("name", {}).get("text") for scenario in design.get("scenarios", [])],
        ["Authentication"],
    )
    report.check(
        "A: the design is the design, not the completed plan",
        "id" not in design and "scenarios" in design,
        sorted(design),
    )

    report.equal(
        "A: exactly one call per stage, and no extra request for the audit",
        (fake.analyze_calls, fake.plan_calls),
        (1, 1),
    )
    report.equal("A: the row exists once", await audit_count_for_task(task_id), 1)
    report.equal("A: nothing executed anything", Probe.hits, 0)


# --------------------------------------------------------------------------- #
# B -- a failed task records where and why
# --------------------------------------------------------------------------- #


async def check_failed(client: httpx.AsyncClient, report: Report) -> None:
    # B, first shape -- the analysis itself fails.
    name = "analyze-failed"
    parsed = parsed_for(name)
    analyze_stub = StageFake(understanding_for(parsed), design_for(parsed), fail_on="api_understanding")
    response, fake = await run_task(client, name=name, fake=analyze_stub)

    report.equal("B: the task fails", response.status_code, 422)
    task_id = await latest_task_id(name)

    audit = await get_audit(client, task_id)
    report.equal("B: the audit exists anyway", audit.status_code, 200)
    record = audit.json()

    report.equal("B: the status says failed", record.get("status"), "failed")
    report.equal("B: the stage is the analysis", record.get("failureStage"), "analyze")
    report.equal("B: the code is the contract's", record.get("failureCode"), "analyze-failed")
    report.check(
        "B: the message is a bounded sentence",
        isinstance(record.get("failureMessage"), str)
        and 0 < len(record["failureMessage"]) <= 500,
        record.get("failureMessage"),
    )
    report.check(
        "B: nothing was understood, because nothing was accepted",
        record.get("understanding") is None,
    )
    report.equal("B: and it was one call", fake.analyze_calls, 1)

    # B, second shape -- the design is refused after a successful analysis.
    name = "plan-refused"
    parsed = parsed_for(name)
    broken = design_for(parsed)
    broken["extraSection"] = {"note": "a field nobody asked for"}
    plan_stub = StageFake(understanding_for(parsed), broken)
    response, fake = await run_task(client, name=name, fake=plan_stub)

    report.equal("B: the refused design fails the task", response.status_code, 422)
    task_id = await latest_task_id(name)
    record = (await get_audit(client, task_id)).json()

    report.equal("B: the status says failed", record.get("status"), "failed")
    report.equal("B: the stage is the design", record.get("failureStage"), "generate")
    report.equal("B: the code is the contract's", record.get("failureCode"), "plan-invalid")
    report.check(
        "B: the message says what happened, not a traceback",
        "Traceback" not in (record.get("failureMessage") or "")
        and len(record.get("failureMessage") or "") > 0,
        record.get("failureMessage"),
    )
    report.check(
        "B: what the analysis understood survives the failure",
        (record.get("understanding") or {}).get("findings", [{}])[0].get("id") == "finding_fake",
        record.get("understanding"),
    )
    report.check(
        "B: the refused design is not stored as if it were accepted",
        record.get("planDesign") is None,
    )
    report.equal("B: one call per stage", (fake.analyze_calls, fake.plan_calls), (1, 1))


async def latest_task_id(spec_name: str) -> str:
    """The task id of the most recent task for that document."""
    spec_id, _ = identity_for(spec_name)

    async with AsyncSessionLocal() as session:
        return str(
            (
                await session.execute(
                    text(
                        "SELECT agent_tasks.id::text FROM agent_tasks "
                        "JOIN api_specs ON api_specs.id = agent_tasks.spec_id "
                        "WHERE api_specs.slug = :slug ORDER BY agent_tasks.created_at DESC LIMIT 1"
                    ),
                    {"slug": spec_id.removeprefix("spec_")},
                )
            ).scalar_one()
        )


# --------------------------------------------------------------------------- #
# C -- the rule engine reports itself, and invents nothing
# --------------------------------------------------------------------------- #


async def check_deterministic(client: httpx.AsyncClient, report: Report) -> None:
    name = "deterministic"
    saved = (os.environ["AGENT_ANALYZER"], os.environ["AGENT_PLANNER"])

    try:
        os.environ["AGENT_ANALYZER"] = "deterministic"
        os.environ["AGENT_PLANNER"] = "deterministic"

        # No stub: the rule engine really runs both stages.
        stubbing(None)
        response = await post_task(client, payload_for(name))
    finally:
        os.environ["AGENT_ANALYZER"], os.environ["AGENT_PLANNER"] = saved
        stubbing(None)

    report.equal("C: the task completes on the rules alone", response.status_code, 201)
    task_id = response.json().get("id", "")
    record = (await get_audit(client, task_id)).json()

    report.equal("C: the analyzer reports the rule engine", record.get("analyzer"), {
        "provider": "deterministic",
        "model": None,
        "promptVersion": None,
    })
    report.equal("C: so does the planner", record.get("planner"), {
        "provider": "deterministic",
        "model": None,
        "promptVersion": None,
    })
    report.check(
        "C: no tokens are invented",
        record.get("usage") == {"analyze": None, "generatePlan": None},
        record.get("usage"),
    )
    report.check(
        "C: the understanding is still recorded",
        len((record.get("understanding") or {}).get("endpoints") or []) == 2,
        record.get("understanding"),
    )
    report.check(
        "C: and the rule engine has no separate design to record",
        record.get("planDesign") is None,
    )
    report.equal("C: the plan is still stored", response.json().get("plan", {}).get("status"), "draft")


# --------------------------------------------------------------------------- #
# D, E, F -- the endpoint's own promises
# --------------------------------------------------------------------------- #


async def check_endpoint_shape(client: httpx.AsyncClient, report: Report) -> None:
    """D: the endpoint answers the documented structure, types included."""
    name = "endpoint"
    response, _ = await run_task(client, name=name)
    task_id = response.json().get("id", "")
    record = (await get_audit(client, task_id)).json()

    report.check("D: it is a JSON object", isinstance(record, dict))
    report.check("D: the task id is a string", isinstance(record.get("taskId"), str))
    report.check(
        "D: the stages are objects with three named fields",
        all(
            set(record.get(stage) or {}) == {"provider", "model", "promptVersion"}
            for stage in ("analyzer", "planner")
        ),
    )
    report.check(
        "D: usage is keyed by stage",
        set(record.get("usage") or {}) == {"analyze", "generatePlan"},
    )
    report.check(
        "D: timestamps are ISO strings",
        all(
            isinstance(record.get(field), str) and "T" in record[field]
            for field in ("createdAt", "updatedAt")
        ),
        {field: record.get(field) for field in ("createdAt", "updatedAt")},
    )
    report.check(
        "D: the understanding is the contract's shape",
        set(record.get("understanding") or {})
        == {"specId", "endpoints", "resources", "authentication", "dependencies", "risks", "findings", "analyzedAt"},
        sorted(record.get("understanding") or {}),
    )
    report.equal("D: one audit per task", await audit_count_for_task(task_id), 1)


async def check_no_secrets(client: httpx.AsyncClient, report: Report) -> None:
    """E: a declared run-time value never reaches the record."""
    name = "secrets"
    response, fake = await run_task(
        client, name=name, variables={SECRET_NAME: SECRET_VALUE}
    )
    task_id = response.json().get("id", "")
    record = (await get_audit(client, task_id)).json()
    stored = await audit_row(task_id)

    serialised = json.dumps(record)
    row_text = json.dumps(stored, default=str)

    report.check("E: the run succeeded", response.status_code == 201)
    report.check(
        "E: the declared value is not in the API response",
        SECRET_VALUE not in serialised,
    )
    report.check(
        "E: and not in the stored row",
        SECRET_VALUE not in row_text,
    )
    report.check(
        "E: the model was never given it either",
        all(
            SECRET_VALUE not in call.instructions and all(SECRET_VALUE not in turn for turn in call.turns)
            for call in fake.calls
        ),
    )
    report.check(
        "E: no credential-shaped text was stored by accident",
        not any(
            marker in row_text
            for marker in ("Bearer ", "sk-", "Authorization", "authorization", "password")
        ),
        row_text[:300],
    )
    report.check(
        "E: the audit still has real content",
        stored is not None and stored["understanding"] is not None and stored["plan_design"] is not None,
    )


async def check_missing(client: httpx.AsyncClient, report: Report) -> None:
    """F: unknown task, and a task with no record, say different things."""
    unknown = await get_audit(client, str(uuid.uuid4()))
    report.equal("F: an unknown task is a 404", unknown.status_code, 404)
    report.equal(
        "F: with the project's task-not-found code",
        unknown.json().get("code"),
        "task-not-found",
    )
    report.equal(
        "F: and the sentence the console already renders",
        unknown.json().get("messageKey"),
        "console.runs.errors.notFound",
    )

    malformed = await get_audit(client, "not-a-uuid")
    report.equal("F: a malformed id is the same 404", malformed.status_code, 404)

    # A task that exists with no audit row: the two are different answers.
    name = "no-record"
    response, _ = await run_task(client, name=name)
    task_id = response.json().get("id", "")

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM agent_task_audits WHERE task_id = :task"),
            {"task": uuid.UUID(task_id)},
        )

    orphan = await get_audit(client, task_id)
    report.equal("F: a task without a record is a 404", orphan.status_code, 404)
    report.equal("F: and says which of the two is missing", orphan.json().get("code"), "audit-not-found")
    report.check(
        "F: the task itself is still readable",
        (await client.get(f"/api/agent/tasks/{task_id}")).status_code == 200,
    )


# --------------------------------------------------------------------------- #
# G -- the record is part of the task's life
# --------------------------------------------------------------------------- #


async def check_lifecycle(client: httpx.AsyncClient, report: Report) -> None:
    """An audit cannot outlive its task, and cannot exist without one.

    The record is created in the task's own commit and removed by the same
    cascade, which is what makes "every task has exactly one audit" true rather
    than aspirational.
    """
    name = "lifecycle"
    response, _ = await run_task(client, name=name)
    task_id = response.json().get("id", "")

    report.equal(
        "G: the record exists while the task does", await audit_count_for_task(task_id), 1
    )

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM agent_tasks WHERE id = :task"), {"task": uuid.UUID(task_id)}
        )

    report.equal("G: and goes with the task", await audit_count_for_task(task_id), 0)
    report.equal(
        "G: leaving nothing to read",
        (await client.get(f"/api/agent/tasks/{task_id}")).status_code,
        404,
    )
    report.equal(
        "G: for the audit route too", (await get_audit(client, task_id)).status_code, 404
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()
    server, base_url = start_target_server()
    await ensure_fixture(base_url)

    print("verifying the agent task audit (stubbed models, real pipeline)\n")

    app = create_app()
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
            await check_completed(client, report)
            await check_failed(client, report)
            await check_deterministic(client, report)
            await check_endpoint_shape(client, report)
            await check_no_secrets(client, report)
            await check_missing(client, report)
            await check_lifecycle(client, report)
    finally:
        stubbing(None)
        await engine.dispose()
        server.shutdown()
        await cleanup_fixture()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


