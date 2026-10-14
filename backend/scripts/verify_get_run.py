"""End-to-end verification of ``GET /api/runs/{run_id}``.

The same shape as ``verify_list_runs.py``, for the same reasons: this service has
no test framework and this script is not an attempt to grow one.  It is run by
hand, deleting it changes nothing about how the service behaves, and what it
checks is the part a unit test would not have covered anyway -- the endpoint
against a **real PostgreSQL**, through the **real ASGI app**, with the **real
exception handlers**, reading rows the **real create endpoint** wrote.

Every check runs; a failure is reported and the run continues, so one broken
assertion does not hide the rest.  Exit code is the number of failures.

    python scripts/verify_get_run.py

It writes a project of its own (``prj_verify_detail``), reads it, and deletes it
again -- including on failure.  It does not touch any other project's rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import os

os.environ.setdefault(
    "RUN_EXECUTOR_DISABLED", "1"
)
"""These scripts predate the executor and assert what a run looks like before
anything has run it.  A run they create must stay where they put it; the
executor's own verification covers execution."""

import httpx  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.db.database import AsyncSessionLocal, engine  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_verify_detail"
ENVIRONMENT_PUBLIC_ID = "env_verify_detail"
BASE_URL = "http://verify.test/api"

GUEST_TOKEN = "get-run-guest-session"
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

SPEC_TITLE = "Verify Detail API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Detail API","version":"1.0.0"},'
    '"paths":{"/verify":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

SECRET_VALUE = "s3cr3t-detail-do-not-echo"
SECRET_NAME = "VERIFY_TOKEN"

ENDPOINT_PUBLIC_ID = "ep_verify_get_verify"

RUN_DURATION_SECONDS = 2.5
STEP_DURATION_MS = 142
DERIVED_DURATION_MS = 250
"""A step with timestamps and no ``duration_ms``: the fallback the read path owns."""

BIG_RUN_PLAN = "plan_verify_detail_big"
SMALL_RUN_PLAN = "plan_verify_detail_small"
EMPTY_RUN_PLAN = "plan_verify_detail_empty"


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
# Fixtures
# --------------------------------------------------------------------------- #


def plan_payload(*, plan_id: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": plan_id,
        "projectId": PROJECT_PUBLIC_ID,
        "specId": SPEC_ID,
        "name": {"text": "Verify detail plan"},
        "goal": {"text": "Produce a tree to read"},
        "riskLevel": "medium",
        "status": "approved",
        "scenarios": scenarios,
        "source": "generated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "rejectedAt": None,
        "rejectionReason": None,
    }


def scenario(
    *,
    key: str,
    index: int,
    steps: int,
    assertions: int,
    assertion_order: list[int] | None = None,
) -> dict[str, Any]:
    """One scenario of the plan.

    ``assertion_order`` is the order the assertions are *submitted* in, which is
    deliberately not the order they must be read back in: the detail sorts them
    by ``assertion_key``, so submitting ``[1, 0]`` is how the ordering check gets
    something to fail on.
    """
    positions = assertion_order if assertion_order is not None else list(range(assertions))

    return {
        "id": key,
        "index": index,
        "name": {"text": f"Scenario {key}"},
        "description": {"text": "Verify"},
        "riskLevel": "low",
        "expected": {"text": "It works"},
        "steps": [
            {
                "id": f"{key}__step_{position}",
                "index": position,
                "kind": "request",
                "description": {"text": f"Step {position}"},
                "endpointId": f"get_/verify/{position}",
                "method": "GET",
                "path": "/verify",
                "produces": None,
                "consumes": [],
            }
            for position in range(steps)
        ],
        "assertions": [
            {
                "id": f"{key}__assert_{position}",
                "kind": "status",
                "target": "status",
                "expected": "200",
                "description": {"text": "Returns 200"},
            }
            for position in positions
        ],
    }


async def ensure_fixture() -> None:
    """Create the probe project, its environment, and nothing else.

    Written with raw statements rather than the ORM because the point is to put
    rows in place, not to exercise a mapper.  Idempotent: an earlier crashed run
    is cleaned up first.  Every run row in this script is written by the real
    create endpoint.
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
                    "name": "Verify get run",
                },
            )
        ).scalar_one()

        await connection.execute(
            text(
                "INSERT INTO environments "
                "(id, project_id, public_id, name, kind, base_url, is_default) "
                "VALUES (:id, :project, :public_id, :name, 'staging', :base_url, false)"
            ),
            {
                "id": uuid.uuid4(),
                "project": project_id,
                "public_id": ENVIRONMENT_PUBLIC_ID,
                "name": "Staging",
                "base_url": BASE_URL,
            },
        )


async def cleanup_fixture() -> None:
    """Remove the probe project and everything under it, in dependency order.

    Ordered rather than relying on ``ON DELETE CASCADE`` alone: the project
    cascades into ``test_plans`` *and* ``test_runs``, and ``test_runs.plan_id`` is
    ``NO ACTION`` -- so which table PostgreSQL empties first decides whether the
    delete succeeds.  Deleting children first removes that question.
    """
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
            "DELETE FROM api_endpoints WHERE spec_id IN "
            "(SELECT id FROM api_specs WHERE project_id = :project)",
            "DELETE FROM api_specs WHERE project_id = :project",
            "DELETE FROM environments WHERE project_id = :project",
            "DELETE FROM projects WHERE id = :project",
        ):
            await connection.execute(text(statement), {"project": project_id})


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #


async def create_run(client: httpx.AsyncClient, plan: dict[str, Any]) -> str:
    """Create a run through the real endpoint and return its id."""
    response = await client.post(
        f"/api/projects/{PROJECT_PUBLIC_ID}/runs",
        json={
            "projectId": PROJECT_PUBLIC_ID,
            "planId": plan["id"],
            "plan": plan,
            "specId": SPEC_ID,
            "specDocument": SPEC_DOCUMENT,
            "environmentId": ENVIRONMENT_PUBLIC_ID,
            "variables": {SECRET_NAME: SECRET_VALUE},
            "baseUrl": BASE_URL,
        },
    )
    if response.status_code != 201:
        raise AssertionError(f"create returned {response.status_code}: {response.text[:400]}")

    return response.json()["id"]


async def detail(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    return await client.get(f"/api/runs/{run_id}")


# --------------------------------------------------------------------------- #
# Statement counting
# --------------------------------------------------------------------------- #


class StatementCounter:
    """Counts the SQL the app actually issues, per request.

    The only honest way to check "no N+1" is to count.  Asserting on the *shape*
    of the code would pass for a correct query issued once per row.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._listening = False

    def _record(self, *args: Any) -> None:
        self.statements.append(args[2])

    def __enter__(self) -> StatementCounter:
        event.listen(engine.sync_engine, "before_cursor_execute", self._record)
        self._listening = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._listening:
            event.remove(engine.sync_engine, "before_cursor_execute", self._record)
            self._listening = False

    def reset(self) -> None:
        self.statements = []

    def selects(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]

# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def steps_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every step of the detail, keyed by its stable id."""
    return {
        step["id"]: step
        for scenario in body["scenarios"]
        for step in scenario["steps"]
    }


def assertions_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        assertion["id"]: assertion
        for scenario in body["scenarios"]
        for assertion in scenario["assertions"]
    }


async def run_checks(report: Report) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
        # --- the three trees, all written by the real create endpoint ------- #
        #
        # The big plan submits its scenarios in the order third, first, second
        # while their indexes are 2, 0, 1 -- so the read order has to come from
        # sort_order rather than from insertion order or from the ids.
        big = await create_run(
            client,
            plan_payload(
                plan_id=BIG_RUN_PLAN,
                scenarios=[
                    scenario(key="scn_third", index=2, steps=3, assertions=0),
                    scenario(
                        key="scn_first",
                        index=0,
                        steps=1,
                        assertions=2,
                        assertion_order=[1, 0],
                    ),
                    scenario(key="scn_second", index=1, steps=2, assertions=0),
                ],
            ),
        )
        small = await create_run(
            client,
            plan_payload(
                plan_id=SMALL_RUN_PLAN,
                scenarios=[scenario(key="scn_only", index=0, steps=1, assertions=1)],
            ),
        )
        empty = await create_run(
            client, plan_payload(plan_id=EMPTY_RUN_PLAN, scenarios=[])
        )

        await seed_big_run(big)

        await check_not_found(client, report)
        await check_tree(client, report, big)
        await check_outcomes(client, report, big, small, empty)
        await check_queries(client, report, big, small, empty)
        await check_widening(client, report, big)
        await check_environment_gone(client, report, small)


async def check_not_found(client: httpx.AsyncClient, report: Report) -> None:
    """A run that does not exist is a 404, and so is an id that cannot be one."""
    unknown = str(uuid.uuid4())
    response = await client.get(f"/api/runs/{unknown}")

    report.equal("an unknown run is 404", response.status_code, 404)

    payload = response.json()
    report.equal("the 404 carries the run-not-found code", payload.get("code"), "run-not-found")
    report.equal(
        "the 404 carries a renderable sentence",
        payload.get("messageKey"),
        "console.runs.errors.notFound",
    )
    report.check(
        "the 404 omits params rather than sending null", "params" not in payload, payload
    )
    report.check(
        "the 404 does not answer 200 with a null body",
        response.status_code == 404 and "scenarios" not in payload,
    )

    malformed = await client.get("/api/runs/not-a-uuid")
    report.equal("an id that cannot be a UUID is 404, not 500", malformed.status_code, 404)
    report.equal(
        "a malformed id gets the same code", malformed.json().get("code"), "run-not-found"
    )


async def check_tree(client: httpx.AsyncClient, report: Report, big: str) -> None:
    """The shape, the nesting, the ids and the order of the whole tree."""
    response = await detail(client, big)
    report.equal("the detail returns 200", response.status_code, 200)

    body = response.json()
    report.equal(
        "the detail carries exactly run, scenarios and lastSeq",
        sorted(body.keys()),
        ["lastSeq", "run", "scenarios"],
    )

    scenarios = body["scenarios"]
    steps = steps_of(body)
    assertions = assertions_of(body)

    # --- shapes --------------------------------------------------------- #
    report.equal(
        "run matches TestRun",
        sorted(body["run"].keys()),
        sorted(
            [
                "id", "projectId", "planId", "planName", "specId", "environmentId",
                "baseUrl", "variableKeys", "status", "createdAt", "startedAt",
                "finishedAt", "durationMs", "failure", "summary",
            ]
        ),
    )
    report.equal(
        "a scenario matches RunScenario",
        sorted(scenarios[0].keys()),
        sorted(["id", "index", "name", "riskLevel", "status", "steps", "assertions"]),
    )
    report.equal(
        "a step matches RunStep",
        sorted(steps["scn_first__step_0"].keys()),
        sorted(
            [
                "id", "scenarioId", "index", "kind", "description", "endpointId",
                "method", "path", "status", "durationMs", "failure", "evidence",
            ]
        ),
    )
    report.equal(
        "an assertion matches RunAssertion",
        sorted(assertions["scn_first__assert_0"].keys()),
        sorted(
            [
                "id", "scenarioId", "stepId", "kind", "target", "expected",
                "actual", "status", "description",
            ]
        ),
    )

    # --- nesting -------------------------------------------------------- #
    report.equal("every scenario of the run is present", len(scenarios), 3)
    report.equal("every step of every scenario is present", len(steps), 6)
    report.equal("every assertion of every scenario is present", len(assertions), 2)

    report.check(
        "every step points at its own scenario",
        all(step["scenarioId"] == scenario["id"] for scenario in scenarios for step in scenario["steps"]),
    )
    report.check(
        "every assertion points at its own scenario",
        all(
            assertion["scenarioId"] == scenario["id"]
            for scenario in scenarios
            for assertion in scenario["assertions"]
        ),
    )
    report.check(
        "no step is attached to a scenario that is not in the payload",
        {step["scenarioId"] for step in steps.values()} == {scenario["id"] for scenario in scenarios},
    )
    report.equal(
        "a scenario with no assertions carries an empty list",
        next(scenario for scenario in scenarios if scenario["id"] == "scn_second")["assertions"],
        [],
    )

    # --- stable ids ----------------------------------------------------- #
    report.check(
        "the run id is the one row key that is a UUID, by design",
        body["run"]["id"] == big,
    )
    report.equal("scenario ids are the plan's scenario keys", sorted(s["id"] for s in scenarios), sorted(["scn_first", "scn_second", "scn_third"]))
    report.check(
        "step ids are the plan's step keys",
        set(steps) == {
            "scn_first__step_0",
            "scn_second__step_0",
            "scn_second__step_1",
            "scn_third__step_0",
            "scn_third__step_1",
            "scn_third__step_2",
        },
        sorted(steps),
    )
    report.check(
        "assertion ids are the plan's assertion keys",
        set(assertions) == {"scn_first__assert_0", "scn_first__assert_1"},
        sorted(assertions),
    )
    report.equal(
        "an assertion names the step it was checked on, by key",
        assertions["scn_first__assert_0"]["stepId"],
        "scn_first__step_0",
    )
    report.equal(
        "endpointId is the endpoint's public id, not the row's UUID",
        steps["scn_first__step_0"]["endpointId"],
        ENDPOINT_PUBLIC_ID,
    )

    # --- ordering ------------------------------------------------------- #
    #
    # The plan submitted the scenarios as third, first, second; sorting by index
    # alone would give first, second, third; the seeded tie puts scn_third on
    # sort_order 0 as well, so only (sort_order, scenario_key) produces this.
    report.equal(
        "scenarios are ordered by sort_order with the key as tiebreaker",
        [scenario["id"] for scenario in scenarios],
        ["scn_first", "scn_third", "scn_second"],
    )
    report.equal(
        "steps are ordered by sort_order with the key as tiebreaker",
        [step["id"] for step in scenarios[1]["steps"]],
        ["scn_third__step_0", "scn_third__step_2", "scn_third__step_1"],
    )
    report.equal(
        "assertions are ordered by assertion_key, not by submission order",
        [assertion["id"] for assertion in scenarios[0]["assertions"]],
        ["scn_first__assert_0", "scn_first__assert_1"],
    )
    report.equal(
        "the tree the database orders is the tree the service returns",
        await tree_order(big),
        [
            ["scn_first", ["scn_first__step_0"], ["scn_first__assert_0", "scn_first__assert_1"]],
            ["scn_third", ["scn_third__step_0", "scn_third__step_2", "scn_third__step_1"], []],
            ["scn_second", ["scn_second__step_0", "scn_second__step_1"], []],
        ],
    )
    report.equal(
        "scenario index is the stored sort_order",
        [scenario["index"] for scenario in scenarios],
        [0, 0, 1],
    )

    # --- one body for both paths ---------------------------------------- #
    listed = {
        row["id"]: row
        for row in (await client.get(f"/api/projects/{PROJECT_PUBLIC_ID}/runs")).json()
    }
    report.equal(
        "the detail's run is byte-for-byte the list's row for the same run",
        body["run"],
        listed.get(big),
    )

    # --- what must not leak --------------------------------------------- #
    leaked = await internal_uuids()
    present = sorted(value for value in leaked if value in response.text)
    report.check("no internal UUID appears anywhere in the payload", not present, present)

    report.check(
        "the run carries variable names only",
        body["run"]["variableKeys"] == [SECRET_NAME],
        body["run"]["variableKeys"],
    )
    report.check("no variables field is echoed", "variables" not in response.text)
    report.check("no secret value appears anywhere", SECRET_VALUE not in response.text)


async def check_outcomes(
    client: httpx.AsyncClient, report: Report, big: str, small: str, empty: str
) -> None:
    """Duration, failure, summary, evidence and the event high-water mark."""
    body = (await detail(client, big)).json()
    steps = steps_of(body)
    run = body["run"]

    # --- duration ------------------------------------------------------- #
    report.equal(
        "the run's durationMs is derived from its two timestamps",
        run["durationMs"],
        int(RUN_DURATION_SECONDS * 1000),
    )
    report.equal(
        "a step's durationMs is the column it owns",
        steps["scn_first__step_0"]["durationMs"],
        STEP_DURATION_MS,
    )
    report.equal(
        "a step with timestamps and no duration column falls back to them",
        steps["scn_second__step_1"]["durationMs"],
        DERIVED_DURATION_MS,
    )
    report.check(
        "a step that has not run has no duration",
        steps["scn_third__step_0"]["durationMs"] is None,
        steps["scn_third__step_0"]["durationMs"],
    )
    report.check(
        "a run that never started has no duration",
        (await detail(client, empty)).json()["run"]["durationMs"] is None,
    )

    # --- failure -------------------------------------------------------- #
    report.equal(
        "a mapped run error code becomes a localized message",
        run["failure"],
        {
            "message": {"key": "console.runs.failure.notExecutable", "params": {}},
            "detail": "the step names no endpoint",
        },
    )
    report.equal(
        "a step's failure is mapped the same way",
        steps["scn_second__step_0"]["failure"],
        {
            "message": {"key": "console.runs.failure.notExecutable", "params": {}},
            "detail": "the step names no endpoint",
        },
    )
    report.check(
        "a step without an error code has no failure",
        steps["scn_third__step_0"]["failure"] is None,
    )
    report.check(
        "a run without an error code has no failure",
        (await detail(client, small)).json()["run"]["failure"] is None,
    )

    await stamp_run_failure(big, "something-unmapped", "raw detail")
    unmapped = (await detail(client, big)).json()
    report.equal(
        "an unmapped run error code is kept as a literal, not dropped",
        unmapped["run"]["failure"],
        {"message": {"text": "something-unmapped"}, "detail": "raw detail"},
    )
    await stamp_run_failure(big, "not-executable", "the step names no endpoint")

    # --- summary -------------------------------------------------------- #
    expected = await expected_summaries([big, small, empty])
    for run_id, counts in expected.items():
        report.equal(
            f"summary agrees with an independent count for {run_id[:8]}",
            (await detail(client, run_id)).json()["run"]["summary"],
            counts,
        )

    report.equal(
        "the summary is computed, not defaulted",
        run["summary"],
        {
            "scenarios": 3,
            "steps": 6,
            "assertions": 2,
            "passedSteps": 2,
            "failedSteps": 1,
            "passedAssertions": 1,
            "failedAssertions": 1,
        },
    )
    report.equal(
        "a run with no scenarios reports seven zeroes",
        (await detail(client, empty)).json()["run"]["summary"],
        {
            "scenarios": 0,
            "steps": 0,
            "assertions": 0,
            "passedSteps": 0,
            "failedSteps": 0,
            "passedAssertions": 0,
            "failedAssertions": 0,
        },
    )

    # --- evidence ------------------------------------------------------- #
    evidence = steps["scn_first__step_0"]["evidence"]
    report.equal(
        "evidence is nested in the step it belongs to, in observation order",
        [item["value"] for item in evidence],
        ["first", "second", "third"],
    )
    report.equal(
        "an authored label keeps its i18n key",
        evidence[0]["label"],
        {"key": "console.runs.evidence.endpoint", "params": {}},
    )
    report.equal(
        "a label that is not a message becomes a literal instead of a 500",
        steps["scn_third__step_0"]["evidence"][0]["label"],
        {"text": "123"},
    )
    report.equal("a step with no evidence has an empty list", steps["scn_second__step_0"]["evidence"], [])
    report.check(
        "evidence whose step link is null is not rendered anywhere",
        "orphan" not in (await detail(client, big)).text,
    )

    # --- lastSeq -------------------------------------------------------- #
    await insert_events(big)
    report.equal(
        "lastSeq is MAX(run_events.seq)",
        (await detail(client, big)).json()["lastSeq"],
        3,
    )
    report.equal(
        "lastSeq is 0 for a run with no events",
        (await detail(client, empty)).json()["lastSeq"],
        0,
    )
    report.equal(
        "lastSeq is 0 for a run whose only events belong to another run",
        (await detail(client, small)).json()["lastSeq"],
        0,
    )


async def check_queries(
    client: httpx.AsyncClient, report: Report, big: str, small: str, empty: str
) -> None:
    """The whole tree is read in a constant number of statements.

    Asserting that a one-scenario run costs exactly what a three-scenario one
    costs is the check that would fail if the scenarios, steps, assertions,
    evidence or counts were fetched per row: the number would scale with the
    tree instead of staying put.
    """
    await detail(client, big)  # warm: never count a connection's first statement

    with StatementCounter() as counter:
        counter.reset()
        await detail(client, big)
        big_selects = len(counter.selects())

        counter.reset()
        await detail(client, small)
        small_selects = len(counter.selects())

        counter.reset()
        await detail(client, empty)
        empty_selects = len(counter.selects())

    report.equal("a three-scenario tree is nine statements", big_selects, 9)
    report.equal("no N+1: a one-scenario run costs the same seven", small_selects, big_selects)
    report.equal("a run with no scenarios skips the tree and the counts", empty_selects, 5)


async def check_widening(client: httpx.AsyncClient, report: Report, big: str) -> None:
    """Columns the database permits and the contract forbids must still render.

    ``run_assertions.expected_value`` / ``actual_value`` are JSONB where the wire
    says ``str``, and ``description`` is nullable where the wire says
    ``LocalizedText``.  A read path that lets Pydantic raise on either turns a
    run that exists into a 500, which is why the narrowing lives in the service.
    """
    await widen_assertions(big)
    response = await detail(client, big)

    report.equal("a wider column still reads as 200", response.status_code, 200)

    assertions = assertions_of(response.json())
    report.equal(
        "a jsonb string is passed through, not re-quoted",
        assertions["scn_first__assert_0"]["expected"],
        "200",
    )
    report.equal(
        "a jsonb number becomes the text of that number",
        assertions["scn_first__assert_0"]["actual"],
        "201",
    )
    report.equal(
        "a jsonb object becomes its JSON, keys sorted",
        assertions["scn_first__assert_1"]["expected"],
        '{"ok": true}',
    )
    report.check(
        "an absent actual stays null rather than becoming the text of None",
        assertions["scn_first__assert_1"]["actual"] is None,
    )
    report.equal(
        "a null description becomes an empty literal, not a validation error",
        assertions["scn_first__assert_0"]["description"],
        {"text": ""},
    )


async def check_environment_gone(
    client: httpx.AsyncClient, report: Report, small: str
) -> None:
    """A run whose environment row is gone: a 500 naming the run, not a fake id.

    ``test_runs.environment_id`` is nullable ``SET NULL`` while the contract's
    ``environmentId`` is a required string, so this is the one state the read path
    cannot express.  The two quiet ways out -- dropping the run, or sending an
    empty string where an id belongs -- are both worse than saying so.  It is the
    policy the list path already documents, checked here on the detail as well.
    """
    await null_environment(small)

    response = await detail(client, small)
    report.equal("a run with no environment row is a 500, not a fake id", response.status_code, 500)

    payload = response.json()
    report.equal("...with the internal-error code", payload.get("code"), "internal-error")
    report.check(
        "...naming the run in details",
        payload.get("details", {}).get("runId") == small,
        payload,
    )
    report.check(
        "...with no run body and no invented environment id",
        "run" not in payload and ENVIRONMENT_PUBLIC_ID not in response.text,
        payload,
    )

    listed = await client.get(f"/api/projects/{PROJECT_PUBLIC_ID}/runs")
    report.equal("the list answers the same way for the same run", listed.status_code, 500)


# --------------------------------------------------------------------------- #
# Direct SQL: the states the API is not allowed to produce
# --------------------------------------------------------------------------- #


RUN_SCOPED = "run_scenario_id IN (SELECT id FROM run_scenarios WHERE run_id = :run)"

SEEDED_LABEL = '{"key": "console.runs.evidence.endpoint"}'


async def seed_big_run(run_id: str) -> None:
    """Give the big run the states the read path has to render.

    The create path writes every step as ``pending`` and every assertion as
    ``skipped`` -- the honest state of a run nothing has executed -- which also
    makes every passed/failed count zero and every duration null.  Those are
    exactly the values a broken read path would also produce, so the rows are
    moved by hand: one passed step with a duration, one failed step with a mapped
    error code, one step with timestamps and no duration, and two assertions with
    opposite outcomes.
    """
    run = uuid.UUID(run_id)
    started = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE test_runs SET status = 'passed', started_at = :started, "
                "finished_at = :finished, error_code = 'not-executable', "
                "error_message = 'the step names no endpoint' WHERE id = :run"
            ),
            {
                "started": started,
                "finished": started + timedelta(seconds=RUN_DURATION_SECONDS),
                "run": run,
            },
        )

        await connection.execute(
            text(
                "UPDATE run_steps SET status = 'passed', duration_ms = :ms, "
                "started_at = :started, finished_at = :finished "
                f"WHERE step_key = 'scn_first__step_0' AND {RUN_SCOPED}"
            ),
            {
                "ms": STEP_DURATION_MS,
                "started": started,
                "finished": started + timedelta(milliseconds=STEP_DURATION_MS),
                "run": run,
            },
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET status = 'failed', error_code = 'not-executable', "
                "error_message = 'the step names no endpoint' "
                f"WHERE step_key = 'scn_second__step_0' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET status = 'passed', started_at = :started, "
                "finished_at = :finished "
                f"WHERE step_key = 'scn_second__step_1' AND {RUN_SCOPED}"
            ),
            {
                "started": started,
                "finished": started + timedelta(milliseconds=DERIVED_DURATION_MS),
                "run": run,
            },
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET status = 'running' "
                f"WHERE step_key = 'scn_third__step_0' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET status = 'skipped' "
                f"WHERE step_key = 'scn_third__step_2' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )

        await connection.execute(
            text(
                "UPDATE run_assertions SET status = 'passed' "
                f"WHERE assertion_key = 'scn_first__assert_0' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )
        await connection.execute(
            text(
                "UPDATE run_assertions SET status = 'failed' "
                f"WHERE assertion_key = 'scn_first__assert_1' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )

        # The order the rows were written in is not the order they must be read
        # in.  Putting a third scenario on sort_order 0, and a third step on
        # sort_order 0, leaves the stable key as the only thing that can break
        # each tie -- so a read path that falls back to the default order has
        # nothing left to hide behind.
        await connection.execute(
            text(
                "UPDATE run_scenarios SET sort_order = 0 "
                "WHERE scenario_key = 'scn_third' AND run_id = :run"
            ),
            {"run": run},
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET sort_order = 0 "
                f"WHERE step_key = 'scn_third__step_2' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )

        endpoint_id = uuid.uuid4()
        await connection.execute(
            text(
                "INSERT INTO api_endpoints (id, spec_id, public_id, method, path) "
                "SELECT :id, id, :public_id, 'GET', '/verify' FROM api_specs "
                "WHERE project_id = (SELECT id FROM projects WHERE public_id = :project)"
            ),
            {"id": endpoint_id, "public_id": ENDPOINT_PUBLIC_ID, "project": PROJECT_PUBLIC_ID},
        )
        await connection.execute(
            text(
                "UPDATE run_steps SET endpoint_id = :endpoint "
                f"WHERE step_key = 'scn_first__step_0' AND {RUN_SCOPED}"
            ),
            {"endpoint": endpoint_id, "run": run},
        )

        # Evidence is inserted newest first and must be read oldest first.
        for value, position in (("third", 3), ("second", 2), ("first", 1)):
            await connection.execute(
                text(
                    "INSERT INTO run_evidence "
                    "(id, run_id, run_step_id, evidence_type, label, value, created_at) "
                    "SELECT :id, :run, run_steps.id, 'endpoint', CAST(:label AS jsonb), "
                    f":value, :at FROM run_steps WHERE step_key = 'scn_first__step_0' "
                    f"AND {RUN_SCOPED}"
                ),
                {
                    "id": uuid.uuid4(),
                    "run": run,
                    "label": SEEDED_LABEL,
                    "value": value,
                    "at": started + timedelta(seconds=position),
                },
            )

        # Evidence whose step link is null: the contract has no place to render
        # it, and a read path that attached it to whatever came first would be
        # inventing an owner.
        await connection.execute(
            text(
                "INSERT INTO run_evidence "
                "(id, run_id, run_step_id, evidence_type, label, value, created_at) "
                "VALUES (:id, :run, NULL, 'endpoint', CAST(:label AS jsonb), 'orphan', :at)"
            ),
            {"id": uuid.uuid4(), "run": run, "label": SEEDED_LABEL, "at": started},
        )

        # A label that is not a LocalizedText at all.  JSONB accepts it; the
        # contract's field is required; only the read path can decide what it is.
        await connection.execute(
            text(
                "INSERT INTO run_evidence "
                "(id, run_id, run_step_id, evidence_type, label, value, created_at) "
                "SELECT :id, :run, run_steps.id, 'checked', CAST('123' AS jsonb), "
                f"'widened', :at FROM run_steps WHERE step_key = 'scn_third__step_0' "
                f"AND {RUN_SCOPED}"
            ),
            {"id": uuid.uuid4(), "run": run, "at": started},
        )


async def insert_events(run_id: str) -> None:
    """Write the run's stream, so ``lastSeq`` has a maximum to find."""
    run = uuid.UUID(run_id)
    at = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

    async with engine.begin() as connection:
        for seq, event_type in enumerate(
            ("run.started", "step.started", "step.completed"), start=1
        ):
            await connection.execute(
                text(
                    "INSERT INTO run_events (id, run_id, seq, event_type, payload, created_at) "
                    "VALUES (:id, :run, :seq, :type, CAST('{}' AS jsonb), :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "run": run,
                    "seq": seq,
                    "type": event_type,
                    "at": at,
                },
            )


async def stamp_run_failure(run_id: str, code: str, message: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE test_runs SET error_code = :code, error_message = :message "
                "WHERE id = :id"
            ),
            {"code": code, "message": message, "id": uuid.UUID(run_id)},
        )


async def widen_assertions(run_id: str) -> None:
    """Make the assertion columns wider than the wire contract.

    ``actual_value`` becomes a JSON *number*, ``expected_value`` a JSON
    *object*, and one description is removed entirely: three states the columns
    permit and the response model does not.
    """
    run = uuid.UUID(run_id)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE run_assertions SET actual_value = CAST('201' AS jsonb), "
                f"description = NULL WHERE assertion_key = 'scn_first__assert_0' AND {RUN_SCOPED}"
            ),
            {"run": run},
        )
        await connection.execute(
            text(
                "UPDATE run_assertions SET expected_value = CAST(:value AS jsonb) "
                f"WHERE assertion_key = 'scn_first__assert_1' AND {RUN_SCOPED}"
            ),
            {"run": run, "value": '{"ok": true}'},
        )


async def null_environment(run_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE test_runs SET environment_id = NULL WHERE id = :id"),
            {"id": uuid.UUID(run_id)},
        )


async def tree_order(run_id: str) -> list[list[Any]]:
    """The tree in the order the read path is supposed to produce it, by SQL.

    The ordering rule is written a second time here on purpose: an expectation
    computed by the code under test proves nothing about the code under test.
    """
    run = uuid.UUID(run_id)

    async with AsyncSessionLocal() as session:
        scenarios = (
            await session.execute(
                text(
                    "SELECT id, scenario_key FROM run_scenarios WHERE run_id = :run "
                    "ORDER BY sort_order, scenario_key"
                ),
                {"run": run},
            )
        ).mappings().all()

        tree: list[list[Any]] = []

        for scenario in scenarios:
            steps = (
                await session.execute(
                    text(
                        "SELECT step_key FROM run_steps WHERE run_scenario_id = :id "
                        "ORDER BY sort_order, step_key"
                    ),
                    {"id": scenario["id"]},
                )
            ).scalars().all()
            assertions = (
                await session.execute(
                    text(
                        "SELECT assertion_key FROM run_assertions "
                        "WHERE run_scenario_id = :id ORDER BY assertion_key"
                    ),
                    {"id": scenario["id"]},
                )
            ).scalars().all()

            tree.append([scenario["scenario_key"], list(steps), list(assertions)])

    return tree


async def expected_summaries(run_ids: list[str]) -> dict[str, dict[str, int]]:
    """The summary, computed by SQL that shares no code with the service.

    Deliberately not calling ``runs._fetch_run_counts``: an aggregate checked
    against itself proves nothing.  This is a plain count per table.
    """
    summaries: dict[str, dict[str, int]] = {}

    async with AsyncSessionLocal() as session:
        for run_id in run_ids:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM run_scenarios WHERE run_id = :run) AS scenarios,
                          (SELECT count(*) FROM run_steps s JOIN run_scenarios c ON c.id = s.run_scenario_id
                             WHERE c.run_id = :run) AS steps,
                          (SELECT count(*) FROM run_assertions a JOIN run_scenarios c ON c.id = a.run_scenario_id
                             WHERE c.run_id = :run) AS assertions,
                          (SELECT count(*) FROM run_steps s JOIN run_scenarios c ON c.id = s.run_scenario_id
                             WHERE c.run_id = :run AND s.status = 'passed') AS passed_steps,
                          (SELECT count(*) FROM run_steps s JOIN run_scenarios c ON c.id = s.run_scenario_id
                             WHERE c.run_id = :run AND s.status = 'failed') AS failed_steps,
                          (SELECT count(*) FROM run_assertions a JOIN run_scenarios c ON c.id = a.run_scenario_id
                             WHERE c.run_id = :run AND a.status = 'passed') AS passed_assertions,
                          (SELECT count(*) FROM run_assertions a JOIN run_scenarios c ON c.id = a.run_scenario_id
                             WHERE c.run_id = :run AND a.status = 'failed') AS failed_assertions
                        """
                    ),
                    {"run": uuid.UUID(run_id)},
                )
            ).mappings().one()

            summaries[run_id] = {
                "scenarios": row["scenarios"],
                "steps": row["steps"],
                "assertions": row["assertions"],
                "passedSteps": row["passed_steps"],
                "failedSteps": row["failed_steps"],
                "passedAssertions": row["passed_assertions"],
                "failedAssertions": row["failed_assertions"],
            }

    return summaries


PROJECT_RUNS = (
    "SELECT id FROM test_runs WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)"
)
PROJECT_SCENARIOS = f"SELECT id FROM run_scenarios WHERE run_id IN ({PROJECT_RUNS})"
PROJECT_STEPS = f"SELECT id FROM run_steps WHERE run_scenario_id IN ({PROJECT_SCENARIOS})"

INTERNAL_UUID_QUERIES: tuple[str, ...] = (
    "SELECT id::text FROM projects WHERE public_id = :project",
    "SELECT id::text FROM environments WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)",
    "SELECT id::text FROM api_specs WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)",
    "SELECT id::text FROM api_endpoints WHERE spec_id IN "
    "(SELECT id FROM api_specs WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project))",
    "SELECT id::text FROM test_plans WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)",
    f"SELECT plan_id::text FROM test_runs WHERE id IN ({PROJECT_RUNS})",
    f"SELECT spec_id::text FROM test_runs WHERE id IN ({PROJECT_RUNS})",
    f"SELECT environment_id::text FROM test_runs WHERE id IN ({PROJECT_RUNS})",
    f"SELECT id::text FROM run_scenarios WHERE run_id IN ({PROJECT_RUNS})",
    f"SELECT id::text FROM run_steps WHERE run_scenario_id IN ({PROJECT_SCENARIOS})",
    f"SELECT id::text FROM run_assertions WHERE run_scenario_id IN ({PROJECT_SCENARIOS})",
    f"SELECT id::text FROM run_evidence WHERE run_id IN ({PROJECT_RUNS})",
    f"SELECT id::text FROM run_events WHERE run_id IN ({PROJECT_RUNS})",
)
"""Every internal key of the probe project, collected from the database.

``test_runs.id`` is deliberately absent: it is the one row key that *is* the
external id (``test_runs`` has no ``public_id``).  Everything else here -- the
project's, the environment's, the spec's, the plan's, the endpoint's, and every
scenario, step, assertion, evidence and event row -- must not appear anywhere in
a response body.
"""


async def internal_uuids() -> list[str]:
    values: list[str] = []

    async with AsyncSessionLocal() as session:
        for statement in INTERNAL_UUID_QUERIES:
            rows = (
                await session.execute(text(statement), {"project": PROJECT_PUBLIC_ID})
            ).scalars().all()
            values.extend(row for row in rows if row)

    return values


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()

    print("verifying GET /api/runs/{run_id}\n")

    try:
        await ensure_fixture()
        await run_checks(report)
    finally:
        await cleanup_fixture()
        await engine.dispose()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
