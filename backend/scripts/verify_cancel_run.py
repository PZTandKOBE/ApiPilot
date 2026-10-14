"""End-to-end verification of ``POST /api/runs/{run_id}/cancel``.

The same shape as ``verify_list_runs.py`` and ``verify_get_run.py``, for the
same reasons: no test framework, a real PostgreSQL, the real ASGI app, the real
exception handlers, and runs created by the real create endpoint.  Nothing is
mocked, so a wrong ``WHERE`` clause or a missing rollback fails here rather than
in the browser.

Every check runs; a failure is reported and the run continues, so one broken
assertion does not hide the rest.  Exit code is the number of failures.

    python scripts/verify_cancel_run.py

It writes a project of its own (``prj_verify_cancel``), reads it, and deletes it
again -- including on failure.  It does not touch any other project's rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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

PROJECT_PUBLIC_ID = "prj_verify_cancel"
ENVIRONMENT_PUBLIC_ID = "env_verify_cancel"
BASE_URL = "http://verify.test/api"

GUEST_TOKEN = "cancel-run-guest-session"
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

SPEC_TITLE = "Verify Cancel API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Cancel API","version":"1.0.0"},'
    '"paths":{"/verify":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

SECRET_VALUE = "s3cr3t-cancel-do-not-echo"
SECRET_NAME = "VERIFY_TOKEN"

RUNNING_STARTED_AGO_MS = 2500
"""How long the seeded ``running`` run has been going when it is cancelled.

Large enough that the derived duration is unmistakable, and it is the value the
test recomputes from the response's own two timestamps rather than trusting.
"""

LOST_RACE = "one of two concurrent cancels"
"""Used in check labels for the pair that races."""


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
        "name": {"text": "Verify cancel plan"},
        "goal": {"text": "Produce runs to cancel"},
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


async def ensure_fixture() -> None:
    """Create the probe project and its environment; every run is created by the API.

    Idempotent: an earlier crashed run is cleaned up first.
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
                    "name": "Verify cancel run",
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
    delete succeeds.  ``test_runs`` takes ``run_scenarios``, ``run_steps``,
    ``run_assertions``, ``run_evidence`` and ``run_events`` with it.
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


async def create_run(client: httpx.AsyncClient, plan_id: str, scenarios: list[dict[str, Any]]) -> str:
    response = await client.post(
        f"/api/projects/{PROJECT_PUBLIC_ID}/runs",
        json={
            "projectId": PROJECT_PUBLIC_ID,
            "planId": plan_id,
            "plan": plan_payload(plan_id=plan_id, scenarios=scenarios),
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


async def cancel(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    return await client.post(f"/api/runs/{run_id}/cancel")


async def detail(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    return await client.get(f"/api/runs/{run_id}")


# --------------------------------------------------------------------------- #
# Statement counting
# --------------------------------------------------------------------------- #


class StatementCounter:
    """Counts the SQL the app actually issues, per request.

    The only honest way to check that a cancel does not walk a tree is to count:
    asserting on the shape of the code would pass for a statement issued per row.
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


RUN_FIELDS = [
    "id", "projectId", "planId", "planName", "specId", "environmentId",
    "baseUrl", "variableKeys", "status", "createdAt", "startedAt",
    "finishedAt", "durationMs", "failure", "summary",
]
"""The fifteen fields every run body carries, in the contract's spelling."""


def instant(value: str) -> datetime:
    """An ISO 8601 string as an instant.

    Compared as instants rather than as strings because the REST layer renders a
    UTC datetime as ``...Z`` while ``isoformat()`` renders it as ``...+00:00``:
    the same moment, two spellings, and a string comparison would call that a
    mismatch in a payload that is correct.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Fixture:
    """The runs this script created, each one written by the real POST endpoint."""

    queued: str
    running: str
    passed: str
    failed: str
    repeat: str
    race: str
    orphan_environment: str
    tiny: str


@dataclass
class Seeded:
    running_started_at: datetime


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


async def run_checks(report: Report) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    tree = [
        scenario(key="scn_a", index=0, steps=2, assertions=1),
        scenario(key="scn_b", index=1, steps=1, assertions=1),
    ]

    async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
        fixture = Fixture(
            queued=await create_run(client, "plan_cancel_queued", tree),
            running=await create_run(client, "plan_cancel_running", tree),
            passed=await create_run(client, "plan_cancel_passed", tree),
            failed=await create_run(client, "plan_cancel_failed", tree),
            repeat=await create_run(client, "plan_cancel_repeat", tree),
            race=await create_run(client, "plan_cancel_race", tree),
            orphan_environment=await create_run(client, "plan_cancel_env", tree),
            tiny=await create_run(
                client,
                "plan_cancel_tiny",
                [scenario(key="scn_only", index=0, steps=1, assertions=1)],
            ),
        )
        seeded = await seed_states(fixture)

        await check_queued_cancel(client, report, fixture)
        await check_running_cancel(client, report, fixture, seeded)
        await check_terminal_cancel(client, report, fixture)
        await check_repeat_cancel(client, report, fixture)
        await check_unknown_runs(client, report)
        await check_concurrency(client, report, fixture)
        await check_environment_gone(client, report, fixture)
        await check_statements(client, report, fixture)
        await check_leaks(client, report, fixture)


async def check_queued_cancel(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """``queued`` -> ``cancelled``: the transition, the event, and the numbers."""
    run_id = fixture.queued

    report.equal("the fixture run starts queued", (await run_state(run_id))["status"], "queued")
    report.check("...with no started_at", (await run_state(run_id))["started_at"] is None)

    before = (await detail(client, run_id)).json()
    report.equal("...and an empty stream", before["lastSeq"], 0)
    report.check("...and no event rows", await event_rows(run_id) == [])

    response = await cancel(client, run_id)
    report.equal("queued cancel returns 200", response.status_code, 200)

    body = response.json()
    report.equal("the body carries the shared run fields", sorted(body.keys()), sorted(RUN_FIELDS))
    report.check("the id is the run that was addressed", body["id"] == run_id)
    report.equal("status is cancelled", body["status"], "cancelled")
    report.check("startedAt is still null", body["startedAt"] is None, body["startedAt"])
    report.check("finishedAt is set", body["finishedAt"] is not None)
    report.equal("durationMs is 0, not null", body["durationMs"], 0)
    report.check("failure is null", body["failure"] is None, body["failure"])
    report.equal("summary is unchanged by cancelling", body["summary"], before["run"]["summary"])
    report.equal(
        "summary agrees with an independent count",
        body["summary"],
        await expected_summary(run_id),
    )

    snapshot = (await detail(client, run_id)).json()
    report.equal("the cancel body is exactly the detail's run", body, snapshot["run"])
    report.equal("lastSeq moved to 1", snapshot["lastSeq"], 1)
    report.equal("the run keeps its variable names", body["variableKeys"], [SECRET_NAME])
    report.check("no variables field is echoed", "variables" not in response.text)

    events = await event_rows(run_id)
    report.equal("exactly one event was written", len(events), 1)

    if events:
        first = events[0]
        report.equal("the event is run.cancelled", first["event_type"], "run.cancelled")
        report.equal("its seq is 1 for an empty stream", first["seq"], 1)
        report.equal(
            "its payload carries finishedAt and durationMs and nothing else",
            sorted(first["payload"].keys()),
            ["durationMs", "finishedAt"],
        )
        report.equal("the payload's durationMs is 0", first["payload"]["durationMs"], 0)
        report.equal(
            "the payload's finishedAt is the run's finishedAt",
            instant(first["payload"]["finishedAt"]),
            instant(body["finishedAt"]),
        )
        report.check(
            "the payload does not repeat the columns",
            not ({"runId", "seq", "at"} & set(first["payload"])),
            first["payload"],
        )

    after = await run_state(run_id)
    report.equal("the row is cancelled", after["status"], "cancelled")
    report.check("the row has a finished_at", after["finished_at"] is not None)
    report.check("the row still has no started_at", after["started_at"] is None)
    report.check("the row carries no error code", after["error_code"] is None)

    # Cancelling is a statement about the run, not about the tree: the steps and
    # scenarios are left exactly as the create path wrote them, and the future
    # executor owns the skipped/pending rules.
    report.check(
        "run_steps were not rewritten",
        set(await step_statuses(run_id)) == {"pending"},
        await step_statuses(run_id),
    )
    report.check(
        "run_scenarios were not rewritten",
        set(await scenario_statuses(run_id)) == {"pending"},
        await scenario_statuses(run_id),
    )


async def check_running_cancel(
    client: httpx.AsyncClient, report: Report, fixture: Fixture, seeded: Seeded
) -> None:
    """``running`` -> ``cancelled``: the lifetime is measured, not defaulted."""
    run_id = fixture.running

    response = await cancel(client, run_id)
    report.equal("running cancel returns 200", response.status_code, 200)

    body = response.json()
    report.equal("status is cancelled", body["status"], "cancelled")
    report.equal(
        "startedAt is the one the run already had",
        instant(body["startedAt"]),
        seeded.running_started_at,
    )
    report.check("finishedAt is set", body["finishedAt"] is not None)

    measured = round((instant(body["finishedAt"]) - instant(body["startedAt"])).total_seconds() * 1000)
    report.equal("durationMs is the measured lifetime", body["durationMs"], measured)
    report.check(
        "...which includes the head start the run was given",
        body["durationMs"] >= RUNNING_STARTED_AGO_MS,
        body["durationMs"],
    )
    report.check("failure is null", body["failure"] is None, body["failure"])

    report.check(
        "a stale error code on the row was cleared",
        (await run_state(run_id))["error_code"] is None,
    )

    snapshot = (await detail(client, run_id)).json()
    events = await event_rows(run_id)
    report.equal("the detail agrees with the cancel body", snapshot["run"]["durationMs"], body["durationMs"])
    report.equal("the detail agrees on finishedAt", snapshot["run"]["finishedAt"], body["finishedAt"])

    if events:
        report.equal(
            "the run.cancelled payload agrees with the cancel body",
            events[-1]["payload"]["durationMs"],
            body["durationMs"],
        )
        report.equal(
            "the payload's finishedAt agrees too",
            instant(events[-1]["payload"]["finishedAt"]),
            instant(body["finishedAt"]),
        )


async def check_terminal_cancel(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """A run that has finished is returned, not restated."""
    for name, run_id in (("passed", fixture.passed), ("failed", fixture.failed)):
        before = (await detail(client, run_id)).json()

        response = await cancel(client, run_id)
        report.equal(f"{name}: cancel returns 200", response.status_code, 200)

        body = response.json()
        report.equal(f"{name}: the status is unchanged", body["status"], name)
        report.equal(f"{name}: the body is the state it already had", body, before["run"])
        report.equal(f"{name}: no event was written", await count_events(run_id), 0)
        report.equal(f"{name}: lastSeq is unchanged", (await detail(client, run_id)).json()["lastSeq"], before["lastSeq"])

    failed_body = (await detail(client, fixture.failed)).json()["run"]
    report.check(
        "failed: the run keeps its own failure",
        failed_body["failure"] is not None,
        failed_body["failure"],
    )


async def check_repeat_cancel(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """A second cancel is the same answer, and not a second event."""
    run_id = fixture.repeat

    report.equal("the fixture already has two events", await max_seq(run_id), 2)

    first = await cancel(client, run_id)
    report.equal("the first cancel returns 200", first.status_code, 200)

    first_body = first.json()
    report.equal("status is cancelled", first_body["status"], "cancelled")
    report.equal("the event took the next seq", await max_seq(run_id), 3)
    report.equal("lastSeq is 3", (await detail(client, run_id)).json()["lastSeq"], 3)
    report.equal("exactly one run.cancelled event exists", await count_events(run_id, "run.cancelled"), 1)

    again = await cancel(client, run_id)
    report.equal("cancelling again returns 200", again.status_code, 200)

    body = again.json()
    report.equal("the second cancel does not transition", body["status"], "cancelled")
    report.equal("the second cancel reports the same run", body, first_body)
    report.equal("the second cancel writes no event", await max_seq(run_id), 3)
    report.equal("the event count is unchanged", await count_events(run_id), 3)
    report.equal(
        "lastSeq is unchanged",
        (await detail(client, run_id)).json()["lastSeq"],
        3,
    )


async def check_unknown_runs(client: httpx.AsyncClient, report: Report) -> None:
    """A run that does not exist, and an id that could not be one."""
    response = await cancel(client, str(uuid.uuid4()))
    report.equal("cancelling an unknown run is 404", response.status_code, 404)

    payload = response.json()
    report.equal("the 404 carries the run-not-found code", payload.get("code"), "run-not-found")
    report.equal(
        "the 404 carries a renderable sentence",
        payload.get("messageKey"),
        "console.runs.errors.notFound",
    )
    report.check("the 404 omits params rather than sending null", "params" not in payload, payload)

    malformed = await client.post("/api/runs/not-a-uuid/cancel")
    report.equal("an id that cannot be a UUID is 404, not 500", malformed.status_code, 404)
    report.equal("a malformed id gets the same code", malformed.json().get("code"), "run-not-found")
    report.equal(
        "a malformed id gets the same sentence",
        malformed.json().get("messageKey"),
        "console.runs.errors.notFound",
    )


class RaceProbe:
    """Records the two statements a race turns on, in the order they were issued.

    The invariant checks below would also pass for a read-then-write
    implementation if the two requests happened to run one after the other --
    the second would see a finished run and stop, writing nothing.  This is what
    says the check was not vacuous: two cancel UPDATEs issued before either
    transaction's event INSERT means the second one arrived while the first was
    still uncommitted, which is precisely the window in which a naive
    implementation writes a second event and collides on ``uq_run_events_run_seq``.
    """

    def __init__(self) -> None:
        self.sequence: list[str] = []
        self._listening = False

    def _record(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if statement.startswith("UPDATE test_runs"):
            self.sequence.append("update")
        elif statement.startswith("INSERT INTO run_events"):
            self.sequence.append("event")

    def __enter__(self) -> RaceProbe:
        event.listen(engine.sync_engine, "before_cursor_execute", self._record)
        self._listening = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._listening:
            event.remove(engine.sync_engine, "before_cursor_execute", self._record)
            self._listening = False

    def overlapped(self) -> bool:
        updates = [index for index, kind in enumerate(self.sequence) if kind == "update"]
        events = [index for index, kind in enumerate(self.sequence) if kind == "event"]

        return len(updates) >= 2 and bool(events) and updates[1] < events[0]


async def check_concurrency(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """Two cancels at once: one transition, one event, no 500.

    This is the check the conditional UPDATE exists for.  A read-then-write
    implementation passes every other check in this file and fails here: both
    requests would see ``queued``, both would write ``run.cancelled``, and the
    second ``seq`` would collide on ``uq_run_events_run_seq``.

    It is run three times, because the outcome depends on the two requests
    actually overlapping -- and the probe at the end is what proves that at
    least one of them did.
    """
    tree = [
        scenario(key="scn_a", index=0, steps=2, assertions=1),
        scenario(key="scn_b", index=1, steps=1, assertions=1),
    ]
    run_ids = [
        fixture.race,
        await create_run(client, "plan_cancel_race_two", tree),
        await create_run(client, "plan_cancel_race_three", tree),
    ]

    overlapped = False

    for position, run_id in enumerate(run_ids, start=1):
        label = f"race {position}"
        probe = RaceProbe()

        with probe:
            first, second = await asyncio.gather(cancel(client, run_id), cancel(client, run_id))

        overlapped = overlapped or probe.overlapped()

        report.check(
            f"{label}: neither cancel is a server error",
            first.status_code < 500 and second.status_code < 500,
            [first.status_code, second.status_code],
        )
        report.equal(
            f"{label}: both cancels answer 200",
            [first.status_code, second.status_code],
            [200, 200],
        )
        report.equal(f"{label}: the run ends cancelled", (await run_state(run_id))["status"], "cancelled")
        report.equal(f"{label}: exactly one event was written", await count_events(run_id), 1)
        report.equal(
            f"{label}: ...and it is the run.cancelled event",
            await count_events(run_id, "run.cancelled"),
            1,
        )
        report.equal(
            f"{label}: no seq was duplicated or skipped",
            await max_seq(run_id),
            await count_events(run_id),
        )
        report.check(
            f"{label}: both answers describe the same run",
            first.json() == second.json(),
            [first.json().get("durationMs"), second.json().get("durationMs")],
        )

    report.check(
        "the two cancels really did overlap in flight",
        overlapped,
        "no attempt interleaved: a serialised run would pass the checks above "
        "without exercising the conditional UPDATE at all",
    )


async def check_environment_gone(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """The environment policy is inherited, and a body that cannot be built writes nothing.

    ``test_runs.environment_id`` is nullable ``SET NULL`` while the contract's
    ``environmentId`` is a required string.  Cancel answers that the way the list
    and the detail do -- a 500 naming the run, never a fabricated id -- and this
    check pins the second half of it: because the body is built before the
    commit, the refused response leaves the run untouched and writes no event.
    """
    run_id = fixture.orphan_environment
    await null_environment(run_id)

    response = await cancel(client, run_id)
    report.equal(
        "a run with no environment row is a 500, not a fabricated id",
        response.status_code,
        500,
    )

    payload = response.json()
    report.equal("...with the internal-error code", payload.get("code"), "internal-error")
    report.check(
        "...naming the run in details",
        payload.get("details", {}).get("runId") == run_id,
        payload,
    )
    report.equal(
        "...and the run is left exactly as it was",
        (await run_state(run_id))["status"],
        "queued",
    )
    report.equal(
        "...with no cancellation event behind the error",
        await count_events(run_id),
        0,
    )


async def check_statements(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """A cancel is a fixed number of statements, whatever the tree holds."""
    one = await create_run(
        client,
        "plan_cancel_statement_one",
        [scenario(key="scn_one", index=0, steps=1, assertions=1)],
    )
    many = await create_run(
        client,
        "plan_cancel_statement_many",
        [
            scenario(key=f"scn_{index}", index=index, steps=2, assertions=1)
            for index in range(3)
        ],
    )

    await cancel(client, fixture.tiny)  # warm: never count a connection's first statement

    with StatementCounter() as counter:
        counter.reset()
        await cancel(client, one)
        one_statements = len(counter.statements)

        counter.reset()
        await cancel(client, many)
        many_statements = len(counter.statements)
        many_selects = len(counter.selects())

        counter.reset()
        await cancel(client, many)
        repeat_statements = len(counter.statements)

    report.equal(
        "a bigger tree costs the same as a smaller one",
        many_statements,
        one_statements,
    )
    # Five, not four, since the executor became a second event producer: the
    # shared writer takes the run's row lock (``SELECT ... FOR UPDATE``) before it
    # numbers an event, so two producers for one run cannot allocate the same
    # seq.  One extra read per event written is the whole cost of that.
    report.equal("a first cancel is five statements", one_statements, 7)
    report.equal("...of which three are reads", many_selects, 5)
    report.equal("a repeat cancel writes no event", repeat_statements, 5)


async def check_leaks(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """Every body this endpoint can produce, scanned for what must not be in it."""
    run_ids = (
        fixture.queued,
        fixture.running,
        fixture.passed,
        fixture.failed,
        fixture.repeat,
        fixture.race,
    )

    bodies = [(await cancel(client, run_id)).text for run_id in run_ids]
    bodies.append((await cancel(client, str(uuid.uuid4()))).text)

    report.check(
        "no secret value appears in any cancel body",
        not [text for text in bodies if SECRET_VALUE in text],
    )
    report.check(
        "no body carries a variables field",
        not [text for text in bodies if '"variables"' in text],
    )
    report.check(
        "every successful body still carries variableKeys",
        all('"variableKeys"' in text for text in bodies[: len(run_ids)]),
    )

    internal = await internal_uuids()
    leaked = sorted({value for text in bodies for value in internal if value in text})
    report.check("no internal UUID appears in any cancel body", not leaked, leaked)

    payloads = [
        json.dumps(row["payload"], ensure_ascii=False)
        for run_id in run_ids
        for row in await event_rows(run_id)
    ]
    payload_leaks = sorted({value for value in internal if any(value in p for p in payloads)})
    report.check("no internal UUID appears in any event payload", not payload_leaks, payload_leaks)
    report.check(
        "no secret value appears in any event payload",
        not [payload for payload in payloads if SECRET_VALUE in payload],
    )


# --------------------------------------------------------------------------- #
# Direct SQL: the states the API cannot produce, and what it must have written
# --------------------------------------------------------------------------- #


async def seed_states(fixture: Fixture) -> Seeded:
    """Put the runs into the states a cancel has to tell apart.

    The create path writes every run as ``queued`` with no timestamps, and that
    is the only state it can produce -- there is no executor -- so ``running``
    and the two terminal outcomes are reached here or not at all.  The
    ``running`` run also gets an ``error_code``, which is the one way to show
    that a cancellation clears a failure instead of inheriting it.
    """
    running_started_at = datetime.now(timezone.utc) - timedelta(
        milliseconds=RUNNING_STARTED_AGO_MS
    )
    terminal_started = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE test_runs SET status = 'running', started_at = :started, "
                "error_code = 'not-executable', "
                "error_message = 'a failure a cancellation has to clear' WHERE id = :id"
            ),
            {"started": running_started_at, "id": uuid.UUID(fixture.running)},
        )
        await connection.execute(
            text(
                "UPDATE test_runs SET status = 'passed', started_at = :started, "
                "finished_at = :finished WHERE id = :id"
            ),
            {
                "started": terminal_started,
                "finished": terminal_started + timedelta(seconds=2, milliseconds=500),
                "id": uuid.UUID(fixture.passed),
            },
        )
        await connection.execute(
            text(
                "UPDATE test_runs SET status = 'failed', started_at = :started, "
                "finished_at = :finished, error_code = 'not-executable', "
                "error_message = 'the step names no endpoint' WHERE id = :id"
            ),
            {
                "started": terminal_started,
                "finished": terminal_started + timedelta(milliseconds=1500),
                "id": uuid.UUID(fixture.failed),
            },
        )

        # Two events already in the stream, so the cancel event has a seq to take.
        for seq, event_type in ((1, "run.started"), (2, "step.started")):
            await connection.execute(
                text(
                    "INSERT INTO run_events (id, run_id, seq, event_type, payload) "
                    "VALUES (:id, :run, :seq, :type, CAST('{}' AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "run": uuid.UUID(fixture.repeat),
                    "seq": seq,
                    "type": event_type,
                },
            )

    return Seeded(running_started_at=running_started_at)


async def run_state(run_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, started_at, finished_at, error_code, error_message "
                    "FROM test_runs WHERE id = :id"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().one()

    return dict(row)


async def event_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT seq, event_type, payload FROM run_events "
                    "WHERE run_id = :id ORDER BY seq"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def max_seq(run_id: str) -> int:
    async with AsyncSessionLocal() as session:
        highest = (
            await session.execute(
                text("SELECT max(seq) FROM run_events WHERE run_id = :id"),
                {"id": uuid.UUID(run_id)},
            )
        ).scalar_one()

    return int(highest or 0)


async def count_events(run_id: str, event_type: str | None = None) -> int:
    clause = "run_id = :id" + (" AND event_type = :type" if event_type else "")
    parameters: dict[str, Any] = {"id": uuid.UUID(run_id)}
    if event_type:
        parameters["type"] = event_type

    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM run_events WHERE {clause}"), parameters
                )
            ).scalar_one()
        )


async def step_statuses(run_id: str) -> list[str]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT run_steps.status FROM run_steps JOIN run_scenarios "
                    "ON run_scenarios.id = run_steps.run_scenario_id "
                    "WHERE run_scenarios.run_id = :id"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).scalars().all()

    return list(rows)


async def scenario_statuses(run_id: str) -> list[str]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text("SELECT status FROM run_scenarios WHERE run_id = :id"),
                {"id": uuid.UUID(run_id)},
            )
        ).scalars().all()

    return list(rows)


async def null_environment(run_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE test_runs SET environment_id = NULL WHERE id = :id"),
            {"id": uuid.UUID(run_id)},
        )


async def expected_summary(run_id: str) -> dict[str, int]:
    """The summary, computed by SQL that shares no code with the service."""
    async with AsyncSessionLocal() as session:
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

    return {
        "scenarios": row["scenarios"],
        "steps": row["steps"],
        "assertions": row["assertions"],
        "passedSteps": row["passed_steps"],
        "failedSteps": row["failed_steps"],
        "passedAssertions": row["passed_assertions"],
        "failedAssertions": row["failed_assertions"],
    }


PROJECT_RUNS = (
    "SELECT id FROM test_runs WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)"
)
PROJECT_SCENARIOS = f"SELECT id FROM run_scenarios WHERE run_id IN ({PROJECT_RUNS})"

INTERNAL_UUID_QUERIES: tuple[str, ...] = (
    "SELECT id::text FROM projects WHERE public_id = :project",
    "SELECT id::text FROM environments WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)",
    "SELECT id::text FROM api_specs WHERE project_id = "
    "(SELECT id FROM projects WHERE public_id = :project)",
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
external id.  Everything else -- the project's, the environment's, the spec's,
the plan's, and every scenario, step, assertion, evidence and event row -- must
not appear in a body this endpoint can produce.
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

    print("verifying POST /api/runs/{run_id}/cancel\n")

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
