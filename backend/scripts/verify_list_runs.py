"""End-to-end verification of ``GET /api/projects/{project_id}/runs``.

This service has no test framework, and this script is not an attempt to grow
one.  It is the same shape as ``seed_dev_data.py``: outside the application, run
by hand, and deleting it changes nothing about how the service behaves.

What it is for is the part unit tests would not have covered anyway -- the
endpoint is checked against a **real PostgreSQL**, through the **real ASGI app**,
with the **real exception handlers**, on rows the **real create endpoint** wrote.
Nothing is mocked, so a wrong join or a wrong aggregate fails here rather than in
the browser.

Every check runs; a failure is reported and the run continues, so one broken
assertion does not hide the rest.  Exit code is the number of failures.

    python scripts/verify_list_runs.py

It writes a project of its own (``prj_verify_list``), reads it, and deletes it
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

PROJECT_PUBLIC_ID = "prj_verify_list"
ENVIRONMENT_PUBLIC_ID = "env_verify_staging"
BASE_URL = "http://verify.test/api"

GUEST_TOKEN = "list-runs-guest-session"
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

SPEC_TITLE = "Verify List API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify List API","version":"1.0.0"},'
    '"paths":{"/verify":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

SECRET_VALUE = "s3cr3t-verify-do-not-echo"
SECRET_NAME = "VERIFY_TOKEN"


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
        "name": {"text": "Verify list plan"},
        "goal": {"text": "Produce runs to list"},
        "riskLevel": "medium",
        "status": "approved",
        "scenarios": scenarios,
        "source": "generated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "rejectedAt": None,
        "rejectionReason": None,
    }


def scenario(*, key: str, index: int, steps: int, assertions: int) -> dict[str, Any]:
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
            for position in range(assertions)
        ],
    }


async def ensure_fixture() -> uuid.UUID:
    """Create the probe project, its environment, and one spec row.

    Written with raw statements rather than the ORM because the point is to put
    rows in place, not to exercise a mapper.  Idempotent: an earlier crashed run
    is cleaned up first.
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
                    "name": "Verify list runs",
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

    return project_id


async def cleanup_fixture() -> None:
    """Remove the probe project and everything under it, in dependency order.

    Ordered rather than relying on ``ON DELETE CASCADE`` alone: the project
    cascades into ``test_plans`` *and* ``test_runs``, and ``test_runs.plan_id``
    is ``NO ACTION`` -- so which table PostgreSQL empties first decides whether
    the delete succeeds.  Deleting children first removes that question.
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
            "DELETE FROM api_specs WHERE project_id = :project",
            "DELETE FROM environments WHERE project_id = :project",
            "DELETE FROM projects WHERE id = :project",
        ):
            await connection.execute(text(statement), {"project": project_id})


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #


@dataclass
class Create:
    """A run the create endpoint made, plus the identifiers the list must echo."""

    run_id: str
    plan_id: str


async def create_run(client: httpx.AsyncClient, plan: dict[str, Any]) -> httpx.Response:
    return await client.post(
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


async def fetch(client: httpx.AsyncClient, query: str = "") -> httpx.Response:
    return await client.get(f"/api/projects/{PROJECT_PUBLIC_ID}/runs{query}")


# --------------------------------------------------------------------------- #
# Statement counting
# --------------------------------------------------------------------------- #


class StatementCounter:
    """Counts the SQL the app actually issues, per request.

    Requirement 7 says the page must not be one query per run, and the only
    honest way to check that is to count.  Asserting on the *shape* of the code
    ("it uses a join") would pass for a join issued once per row.

    ``before_cursor_execute`` fires for every statement on every connection the
    engine owns, and the app shares this engine.
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


async def run_checks(report: Report) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
        # --- empty project ------------------------------------------------- #
        empty = await fetch(client, "")
        report.equal("empty project is 200", empty.status_code, 200)
        report.equal("empty project body is []", empty.json(), [])

        # --- fixture runs ------------------------------------------------- #
        plan_one = plan_payload(
            plan_id="plan_verify_one",
            scenarios=[
                scenario(key="scn_alpha", index=0, steps=3, assertions=2),
                scenario(key="scn_beta", index=1, steps=2, assertions=1),
            ],
        )
        plan_two = plan_payload(
            plan_id="plan_verify_two",
            scenarios=[scenario(key="scn_gamma", index=0, steps=1, assertions=0)],
        )

        created: list[httpx.Response] = []
        for plan in (plan_one, plan_one, plan_two):
            response = await create_run(client, plan)
            report.equal(
                f"create run for {plan['id']} returns 201",
                response.status_code,
                201,
            )
            created.append(response)

        if report.failures:
            return

        run_ids = [response.json()["id"] for response in created]

        # Runs created in the same transaction tick can share a timestamp, so
        # the ordering check below needs a spread.  Backdating is the only way
        # to get one without sleeping.
        await spread_created_at(run_ids)

        # --- give the run tree a mixed outcome ------------------------------ #
        await seed_counts(run_ids)

        # --- the list ------------------------------------------------------ #
        with StatementCounter() as counter:
            counter.reset()
            response = await fetch(client, "")

        report.equal("list returns 200", response.status_code, 200)
        body = response.json()
        report.equal("list returns every run", len(body), 3)

        first = body[0]
        report.equal(
            "list shape matches TestRun",
            sorted(first.keys()),
            sorted(
                [
                    "id", "projectId", "planId", "planName", "specId", "environmentId",
                    "baseUrl", "variableKeys", "status", "createdAt", "startedAt",
                    "finishedAt", "durationMs", "failure", "summary",
                ]
            ),
        )

        # --- ordering ------------------------------------------------------ #
        timestamps = [row["createdAt"] for row in body]
        report.check(
            "ordered by createdAt descending",
            timestamps == sorted(timestamps, reverse=True),
            timestamps,
        )
        report.equal("newest first is the last created", body[0]["id"], run_ids[2])

        # --- stable ids ---------------------------------------------------- #
        report.equal("run id is the row uuid", body[0]["id"], run_ids[2])
        report.equal("planId is the plan public id, not a uuid", body[0]["planId"], "plan_verify_two")
        report.equal("specId is spec_ + slug", body[0]["specId"], SPEC_ID)
        report.equal(
            "environmentId is the environment public id",
            body[0]["environmentId"],
            ENVIRONMENT_PUBLIC_ID,
        )
        report.equal("baseUrl is the frozen copy", body[0]["baseUrl"], BASE_URL)

        leaked = leaked_uuids(await internal_uuids(run_ids))
        report.check(
            "no internal uuid appears in the payload",
            not [value for value in leaked if value in response.text],
            leaked,
        )

        # --- secrets ------------------------------------------------------- #
        report.check(
            "variableKeys carries the names",
            all(row["variableKeys"] == [SECRET_NAME] for row in body),
            [row["variableKeys"] for row in body],
        )
        report.check(
            "no row carries a variables field",
            not any("variables" in row for row in body),
        )
        report.check(
            "no secret value anywhere in the response",
            SECRET_VALUE not in response.text,
        )

        # --- summary ------------------------------------------------------- #
        expected = await expected_summaries(run_ids)
        actual = {row["id"]: row["summary"] for row in body}
        for run_id, counts in expected.items():
            report.equal(f"summary for {run_id[:8]}", actual.get(run_id), counts)

        report.check(
            "summary is computed, not defaulted",
            any(row["summary"]["passedSteps"] for row in body)
            and any(row["summary"]["failedAssertions"] for row in body),
            actual,
        )

        # --- duration ------------------------------------------------------ #
        report.check(
            "durationMs is null before the run starts",
            all(row["durationMs"] is None for row in body),
            [row["durationMs"] for row in body],
        )

        await stamp_lifecycle(run_ids[2], seconds=2.5)
        after = (await fetch(client, "")).json()
        newest = next(row for row in after if row["id"] == run_ids[2])
        report.equal("durationMs is derived from the timestamps", newest["durationMs"], 2500)
        report.check(
            "durationMs stays null for a run that has not finished",
            next(row for row in after if row["id"] == run_ids[0])["durationMs"] is None,
        )

        # --- failure ------------------------------------------------------- #
        report.check(
            "failure is null without an error code",
            all(row["failure"] is None for row in after if row["id"] != run_ids[2]),
        )

        await stamp_failure(run_ids[2], "not-executable", "the step names no endpoint")
        mapped = (await fetch(client, "")).json()
        newest = next(row for row in mapped if row["id"] == run_ids[2])
        report.equal(
            "mapped error code becomes a localized message",
            newest["failure"],
            {
                "message": {"key": "console.runs.failure.notExecutable", "params": {}},
                "detail": "the step names no endpoint",
            },
        )

        await stamp_failure(run_ids[2], "something-unmapped", "raw detail")
        unmapped = (await fetch(client, "")).json()
        newest = next(row for row in unmapped if row["id"] == run_ids[2])
        report.equal(
            "unmapped error code is kept as a literal, not dropped",
            newest["failure"],
            {"message": {"text": "something-unmapped"}, "detail": "raw detail"},
        )

        # --- pagination ---------------------------------------------------- #
        page_one = (await fetch(client, "?limit=1")).json()
        page_two = (await fetch(client, "?limit=1&offset=1")).json()
        tail = (await fetch(client, "?limit=100&offset=1")).json()

        report.equal("limit bounds the page", len(page_one), 1)
        report.equal("limit + offset walks the list", page_one[0]["id"], body[0]["id"])
        report.equal("offset skips", page_two[0]["id"], body[1]["id"])
        report.equal(
            "offset + limit agrees with the unpaged list",
            [row["id"] for row in tail],
            [row["id"] for row in body[1:]],
        )
        report.check(
            "combined page equals the unpaged slice",
            [page_one[0]["id"], page_two[0]["id"]] == [body[0]["id"], body[1]["id"]],
        )
        report.equal("offset past the end is empty", (await fetch(client, "?offset=99")).json(), [])

        # --- query count --------------------------------------------------- #
        with StatementCounter() as counter:
            counter.reset()
            await fetch(client, "?limit=3")
            three_runs = len(counter.selects())

            counter.reset()
            await fetch(client, "?limit=1")
            one_run = len(counter.selects())

            counter.reset()
            await fetch(client, "?offset=99")
            empty_page = len(counter.selects())

        report.equal("a 3-run page is 5 statements", three_runs, 5)
        report.equal("no N+1: a 1-run page is the same 3 statements", one_run, three_runs)
        report.equal("an empty page skips the aggregation", empty_page, 4)

        # --- errors -------------------------------------------------------- #
        missing = await client.get("/api/projects/prj_does_not_exist/runs")
        report.equal("unknown project is 404", missing.status_code, 404)
        payload = missing.json()
        report.equal("error envelope carries code", payload.get("code"), "project-not-found")
        report.equal(
            "error envelope carries a renderable messageKey",
            payload.get("messageKey"),
            "console.runs.errors.notFound",
        )
        report.check(
            "error envelope omits params rather than sending null",
            "params" not in payload,
            payload,
        )

        for query in ("?limit=0", "?limit=201", "?offset=-1", "?limit=abc"):
            bad = await fetch(client, query)
            payload = bad.json()
            report.equal(f"{query} is rejected", bad.status_code, 422)
            report.equal(f"{query} carries the code", payload.get("code"), "invalid-request")
            report.equal(
                f"{query} reports a load failure, not a failed create",
                payload.get("messageKey"),
                "console.runs.errors.loadFailed",
            )
            report.check(
                f"{query} does not echo the request",
                "body" not in payload and "params" not in payload,
                payload,
            )

        # The create path's 422 must still read as a create failure -- the
        # method split exists to fix the read path, not to relabel the write one.
        invalid_create = await client.post(
            f"/api/projects/{PROJECT_PUBLIC_ID}/runs", json={"planId": "plan_x"}
        )
        report.equal("create still rejects a bad body", invalid_create.status_code, 422)
        report.equal(
            "create's 422 still says createFailed",
            invalid_create.json().get("messageKey"),
            "console.runs.errors.createFailed",
        )


# --------------------------------------------------------------------------- #
# Direct SQL, for the things the API is not allowed to say
# --------------------------------------------------------------------------- #


async def spread_created_at(run_ids: list[str]) -> None:
    """Backdate the three runs so ``createdAt`` descending has something to order."""
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    async with engine.begin() as connection:
        for position, run_id in enumerate(run_ids):
            await connection.execute(
                text("UPDATE test_runs SET created_at = :at WHERE id = :id"),
                {"at": base + timedelta(hours=position), "id": uuid.UUID(run_id)},
            )


async def seed_counts(run_ids: list[str]) -> None:
    """Give the run tree a mixed outcome.

    The create path writes every step as ``pending`` and every assertion as
    ``skipped``, which is the honest state of a run nothing has executed -- and
    it makes every passed/failed count zero, which is exactly the value a broken
    aggregate would also produce.  Flipping some rows is what makes the summary
    check mean something.
    """
    async with engine.begin() as connection:
        for run_id in run_ids:
            await connection.execute(
                text(
                    "UPDATE run_steps SET status = 'passed' "
                    "WHERE sort_order = 0 AND run_scenario_id IN "
                    "(SELECT id FROM run_scenarios WHERE run_id = :run)"
                ),
                {"run": uuid.UUID(run_id)},
            )
            await connection.execute(
                text(
                    "UPDATE run_steps SET status = 'failed' "
                    "WHERE sort_order = 1 AND run_scenario_id IN "
                    "(SELECT id FROM run_scenarios WHERE run_id = :run)"
                ),
                {"run": uuid.UUID(run_id)},
            )
            await connection.execute(
                text(
                    "UPDATE run_assertions SET status = 'passed' "
                    "WHERE assertion_key LIKE '%assert_0' AND run_scenario_id IN "
                    "(SELECT id FROM run_scenarios WHERE run_id = :run)"
                ),
                {"run": uuid.UUID(run_id)},
            )
            await connection.execute(
                text(
                    "UPDATE run_assertions SET status = 'failed' "
                    "WHERE assertion_key LIKE '%assert_1' AND run_scenario_id IN "
                    "(SELECT id FROM run_scenarios WHERE run_id = :run)"
                ),
                {"run": uuid.UUID(run_id)},
            )


async def stamp_lifecycle(run_id: str, *, seconds: float) -> None:
    started = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE test_runs SET started_at = :started, finished_at = :finished, "
                "status = 'passed' WHERE id = :id"
            ),
            {
                "started": started,
                "finished": started + timedelta(seconds=seconds),
                "id": uuid.UUID(run_id),
            },
        )


async def stamp_failure(run_id: str, code: str, message: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE test_runs SET error_code = :code, error_message = :message WHERE id = :id"),
            {"code": code, "message": message, "id": uuid.UUID(run_id)},
        )


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


async def internal_uuids(run_ids: list[str]) -> list[str]:
    """The UUIDs the wire contract forbids, collected from the database.

    ``test_runs.id`` is excluded on purpose: it is the one row key that *is* the
    external id (``test_runs`` has no ``public_id``).  Everything else here --
    the plan's, the spec's, the environment's, and every scenario/step/assertion
    row -- must not appear anywhere in the payload.
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT test_runs.plan_id::text AS plan_id,
                           test_runs.spec_id::text AS spec_id,
                           test_runs.environment_id::text AS environment_id,
                           test_plans.id::text AS test_plan_id,
                           test_plans.spec_id::text AS test_plan_spec_id
                    FROM test_runs
                    JOIN test_plans ON test_plans.id = test_runs.plan_id
                    WHERE test_runs.id = ANY(:ids)
                    """
                ),
                {"ids": [uuid.UUID(run_id) for run_id in run_ids]},
            )
        ).mappings().all()

        children = (
            await session.execute(
                text(
                    """
                    SELECT c.id::text AS scenario_id, s.id::text AS step_id, a.id::text AS assertion_id
                    FROM run_scenarios c
                    LEFT JOIN run_steps s ON s.run_scenario_id = c.id
                    LEFT JOIN run_assertions a ON a.run_scenario_id = c.id
                    WHERE c.run_id = ANY(:ids)
                    """
                ),
                {"ids": [uuid.UUID(run_id) for run_id in run_ids]},
            )
        ).mappings().all()

    values: list[str] = []
    for row in rows:
        values.extend(row[key] for key in row.keys() if row[key])
    for row in children:
        values.extend(row[key] for key in row.keys() if row[key])

    return values


def leaked_uuids(values: list[str]) -> list[str]:
    return sorted(set(values))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> int:
    report = Report()

    print(f"verifying GET /api/projects/{PROJECT_PUBLIC_ID}/runs\n")

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
