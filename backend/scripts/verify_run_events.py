"""End-to-end verification of ``GET /api/runs/{run_id}/events`` (7.2-D).

The same shape as ``verify_list_runs.py``, ``verify_get_run.py`` and
``verify_cancel_run.py``: no test framework, a real PostgreSQL, the real ASGI
app, the real exception handlers, and runs created by the real create endpoint.
Nothing is mocked, so a wrong ``WHERE`` clause or a missing order fails here
rather than in a browser.

Every check runs; a failure is reported and the run continues, so one broken
assertion does not hide the rest.  Exit code is the number of failures.

    python scripts/verify_run_events.py

It writes a project of its own (``prj_verify_events``), reads it, and deletes it
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

PROJECT_PUBLIC_ID = "prj_verify_events"
ENVIRONMENT_PUBLIC_ID = "env_verify_events"
BASE_URL = "http://verify.test/api"

GUEST_TOKEN = "run-events-guest-session"
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

SPEC_TITLE = "Verify Events API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Events API","version":"1.0.0"},'
    '"paths":{"/verify":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

SECRET_VALUE = "s3cr3t-events-do-not-echo"
SECRET_NAME = "VERIFY_TOKEN"

EVENT_FIELDS = ["at", "eventType", "payload", "runId", "seq"]
"""The five fields a replay record carries, in the contract's spelling.

``run_events.id`` is deliberately not among them: it is an internal UUID, and an
event is identified by ``(runId, seq)``.
"""

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
"""A fixed clock for the seeded events.

Fixed rather than "now" so the ordering check can say something exact: the three
events of the ordered run are written with timestamps that run *against* their
``seq`` values, and a sort by ``created_at`` would return them backwards.
"""


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

    def seqs(self, label: str, body: Any, expected: list[int]) -> None:
        actual = [item.get("seq") for item in body] if isinstance(body, list) else body
        self.equal(label, actual, expected)


def instant(value: str) -> datetime:
    """An ISO 8601 string as an instant, so ``Z`` and ``+00:00`` compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def scenario(key: str, index: int, steps: int) -> dict[str, Any]:
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
        "assertions": [],
    }


def plan_payload(plan_id: str) -> dict[str, Any]:
    return {
        "id": plan_id,
        "projectId": PROJECT_PUBLIC_ID,
        "specId": SPEC_ID,
        "name": {"text": "Verify events plan"},
        "goal": {"text": "Produce a stream to replay"},
        "riskLevel": "medium",
        "status": "approved",
        "scenarios": [scenario("scn_a", 0, 2)],
        "source": "generated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "rejectedAt": None,
        "rejectionReason": None,
    }


async def ensure_fixture() -> None:
    """Create the probe project and its environment; every run comes from the API.

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
                    "name": "Verify run events",
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

    ``test_runs`` takes ``run_scenarios``, ``run_steps``, ``run_assertions``,
    ``run_evidence`` and ``run_events`` with it; the plans and the spec are
    deleted before the project because ``test_runs.plan_id`` is ``NO ACTION``.
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


async def create_run(client: httpx.AsyncClient, plan_id: str) -> str:
    response = await client.post(
        f"/api/projects/{PROJECT_PUBLIC_ID}/runs",
        json={
            "projectId": PROJECT_PUBLIC_ID,
            "planId": plan_id,
            "plan": plan_payload(plan_id),
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


async def replay(
    client: httpx.AsyncClient, run_id: str, query: str = ""
) -> httpx.Response:
    return await client.get(f"/api/runs/{run_id}/events{query}")


async def cancel(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    return await client.post(f"/api/runs/{run_id}/cancel")


# --------------------------------------------------------------------------- #
# Statement counting
# --------------------------------------------------------------------------- #


class StatementCounter:
    """Counts the SQL the app actually issues, and how.

    Replay has two properties that only a statement-level view can check: that
    the ``seq`` filter and the order are the database's rather than Python's, and
    that the endpoint writes nothing at all.
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

    def writes(self) -> list[str]:
        return [
            s
            for s in self.statements
            if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]

    def events_selects(self) -> list[str]:
        return [s for s in self.selects() if "run_events" in s]


@dataclass
class Fixture:
    """The runs this script created, each one written by the real POST endpoint."""

    silent: str
    ordered: str
    cancelled: str
    tail: str
    isolated_a: str
    isolated_b: str


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


async def run_checks(report: Report) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
        fixture = Fixture(
            silent=await create_run(client, "plan_events_silent"),
            ordered=await create_run(client, "plan_events_ordered"),
            cancelled=await create_run(client, "plan_events_cancelled"),
            tail=await create_run(client, "plan_events_tail"),
            isolated_a=await create_run(client, "plan_events_isolated_a"),
            isolated_b=await create_run(client, "plan_events_isolated_b"),
        )
        await seed_events(fixture)

        await check_empty(client, report, fixture)
        await check_replay(client, report, fixture)
        await check_ordering(client, report, fixture)
        await check_cancelled_event(client, report, fixture)
        await check_tail_after_cancel(client, report, fixture)
        await check_isolation(client, report, fixture)
        await check_unknown_runs(client, report)
        await check_validation(client, report, fixture)
        await check_queries(client, report, fixture)
        await check_leaks(client, report, fixture)


async def check_empty(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """A run that exists and has said nothing is an empty collection, not a 404."""
    run_id = fixture.silent

    response = await replay(client, run_id)
    report.equal("a run with no events is 200", response.status_code, 200)

    body = response.json()
    report.check("...and a bare array", isinstance(body, list), type(body).__name__)
    report.equal("...which is empty", body, [])
    report.equal("...and fromSeq=1 is empty too", (await replay(client, run_id, "?fromSeq=1")).json(), [])

    snapshot = (await client.get(f"/api/runs/{run_id}")).json()
    report.equal("the detail agrees the stream is empty", snapshot["lastSeq"], 0)


async def check_replay(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """fromSeq is inclusive, defaults to the whole stream, and is a database filter."""
    run_id = fixture.ordered

    response = await replay(client, run_id)
    report.equal("the replay returns 200", response.status_code, 200)

    body = response.json()
    report.check("the body is a bare array, with no envelope", isinstance(body, list), type(body).__name__)
    report.seqs("with no fromSeq the whole stream comes back", body, [1, 2, 3])
    report.equal("...three records", len(body), 3)

    report.seqs("fromSeq=1 is the whole stream", (await replay(client, run_id, "?fromSeq=1")).json(), [1, 2, 3])
    report.seqs("fromSeq=2 drops the first event", (await replay(client, run_id, "?fromSeq=2")).json(), [2, 3])
    report.seqs("fromSeq=3 is inclusive of 3", (await replay(client, run_id, "?fromSeq=3")).json(), [3])
    report.seqs("one past the end is empty, not an error", (await replay(client, run_id, "?fromSeq=4")).json(), [])
    report.seqs("far past the end is empty too", (await replay(client, run_id, "?fromSeq=999")).json(), [])

    # --- the record itself ---------------------------------------------- #
    first = body[0]
    report.equal("a record carries exactly the five contract fields", sorted(first.keys()), EVENT_FIELDS)
    report.check("...and no id", "id" not in first, sorted(first.keys()))
    report.equal("runId is the run that was addressed", first["runId"], run_id)
    report.check("seq is an integer", isinstance(first["seq"], int), type(first["seq"]).__name__)
    report.check("at is an ISO-8601 string", isinstance(first["at"], str))
    report.equal("eventType is the stored event_type", first["eventType"], "step.started")

    # --- against the database -------------------------------------------- #
    stored = {row["seq"]: row for row in await event_rows(run_id)}
    mismatched = [
        item["seq"]
        for item in body
        if item["eventType"] != stored[item["seq"]]["event_type"]
        or instant(item["at"]) != stored[item["seq"]]["created_at"]
        or item["payload"] != stored[item["seq"]]["payload"]
    ]
    report.check("every record matches its stored row", not mismatched, mismatched)


async def check_ordering(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """``seq`` is the order, and it is not ``created_at`` wearing a disguise."""
    run_id = fixture.ordered

    body = (await replay(client, run_id)).json()
    report.seqs("the events come back in seq order", body, [1, 2, 3])

    stamps = [instant(item["at"]) for item in body]
    report.check(
        "the stored timestamps run against the sequence",
        stamps == sorted(stamps, reverse=True),
        [item["at"] for item in body],
    )
    report.check(
        "...so the order cannot be a timestamp sort",
        stamps[0] > stamps[-1],
        [item["at"] for item in body],
    )
    report.check(
        "the sequence increases",
        [item["seq"] for item in body] == sorted(item["seq"] for item in body),
    )


async def check_cancelled_event(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """The one event this service writes is replayable, field for field."""
    run_id = fixture.cancelled

    report.equal("the run starts with an empty stream", (await replay(client, run_id)).json(), [])

    cancelled = await cancel(client, run_id)
    report.equal("cancelling it returns 200", cancelled.status_code, 200)

    cancelled_run = cancelled.json()
    body = (await replay(client, run_id)).json()

    report.equal("the cancellation is now the whole stream", len(body), 1)

    if body:
        event = body[0]
        report.equal("the record carries exactly the five fields", sorted(event.keys()), EVENT_FIELDS)
        report.equal("the event is run.cancelled", event["eventType"], "run.cancelled")
        report.equal("it took seq 1 on an empty stream", event["seq"], 1)
        report.equal("the run it names is the run addressed", event["runId"], run_id)
        report.check("at is present", event["at"] is not None)
        stored = await event_rows(run_id)
        report.equal(
            "the payload is the stored payload, untouched",
            event["payload"],
            stored[0]["payload"] if stored else None,
        )
        report.equal(
            "the payload carries the writer's fields and nothing else",
            sorted(event["payload"].keys()),
            ["durationMs", "finishedAt"],
        )
        report.equal("the payload's durationMs is the run's", event["payload"]["durationMs"], 0)
        report.equal(
            "the payload's finishedAt is the run's instant",
            instant(event["payload"]["finishedAt"]),
            instant(cancelled_run["finishedAt"]),
        )
        report.check(
            "the row's own timestamp is the same instant as the event it records",
            instant(event["at"]) == instant(cancelled_run["finishedAt"]),
            [event["at"], cancelled_run["finishedAt"]],
        )

    snapshot = (await client.get(f"/api/runs/{run_id}")).json()
    report.equal("the detail's lastSeq sees the same event", snapshot["lastSeq"], 1)
    report.equal("fromSeq=2 has nothing left to replay", (await replay(client, run_id, "?fromSeq=2")).json(), [])
    report.seqs("fromSeq=1 still returns it", (await replay(client, run_id, "?fromSeq=1")).json(), [1])


async def check_tail_after_cancel(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """The resume path: a snapshot's mark, then exactly the tail after it."""
    run_id = fixture.tail

    report.seqs("the run starts with two events", (await replay(client, run_id)).json(), [1, 2])

    report.equal("cancelling it returns 200", (await cancel(client, run_id)).status_code, 200)

    report.seqs("the whole stream is three events", (await replay(client, run_id)).json(), [1, 2, 3])

    tail = (await replay(client, run_id, "?fromSeq=3")).json()
    report.seqs("fromSeq=3 replays only the new event", tail, [3])
    report.equal(
        "...and it is the cancellation",
        tail[0]["eventType"] if tail else None,
        "run.cancelled",
    )
    report.seqs("fromSeq=2 replays the last two", (await replay(client, run_id, "?fromSeq=2")).json(), [2, 3])
    report.equal("the detail's lastSeq is the last seq", (await client.get(f"/api/runs/{run_id}")).json()["lastSeq"], 3)


async def check_isolation(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """One run's replay never carries another run's events."""
    first = await replay(client, fixture.isolated_a)
    second = await replay(client, fixture.isolated_b)

    a = first.json()
    b = second.json()

    report.equal("run a has exactly its own event", [item["runId"] for item in a], [fixture.isolated_a])
    report.equal("run b has exactly its own event", [item["runId"] for item in b], [fixture.isolated_b])
    report.check("run b's id is absent from run a's body", fixture.isolated_b not in first.text)
    report.check("run a's id is absent from run b's body", fixture.isolated_a not in second.text)
    report.equal(
        "a nested payload survives the round trip untouched",
        a[0]["payload"] if a else None,
        NESTED_PAYLOAD,
    )


async def check_unknown_runs(client: httpx.AsyncClient, report: Report) -> None:
    """A run that does not exist, and an id that could not be one."""
    response = await replay(client, str(uuid.uuid4()))
    report.equal("an unknown run is 404", response.status_code, 404)

    payload = response.json()
    report.equal("the 404 carries the run-not-found code", payload.get("code"), "run-not-found")
    report.equal(
        "the 404 carries a renderable sentence",
        payload.get("messageKey"),
        "console.runs.errors.notFound",
    )
    report.check("the 404 omits params rather than sending null", "params" not in payload, payload)

    malformed = await replay(client, "not-a-uuid")
    report.equal("an id that cannot be a UUID is 404, not 500", malformed.status_code, 404)
    report.equal("a malformed id gets the same code", malformed.json().get("code"), "run-not-found")
    report.equal(
        "a malformed id gets the same sentence",
        malformed.json().get("messageKey"),
        "console.runs.errors.notFound",
    )

    with_query = await replay(client, "not-a-uuid", "?fromSeq=2")
    report.equal("...and the same with a fromSeq", with_query.status_code, 404)


async def check_validation(
    client: httpx.AsyncClient, report: Report, fixture: Fixture
) -> None:
    """A ``fromSeq`` below 1 is the shared 422, not an error shape of its own."""
    for query in ("?fromSeq=0", "?fromSeq=-1", "?fromSeq=abc", "?fromSeq=1.5"):
        response = await replay(client, fixture.ordered, query)
        body = response.json()

        report.equal(f"{query} is rejected", response.status_code, 422)
        report.check(f"{query} answers with the error envelope", isinstance(body, dict), body)

        if not isinstance(body, dict):
            continue

        payload = body
        report.equal(f"{query} carries the code", payload.get("code"), "invalid-request")
        report.equal(
            f"{query} reports a load failure, not a failed create",
            payload.get("messageKey"),
            "console.runs.errors.loadFailed",
        )
        report.check(f"{query} carries the validation details", "details" in payload, payload)
        report.check(
            f"{query} does not echo the request",
            "body" not in payload and "params" not in payload,
            payload,
        )

    report.equal("fromSeq=1 is still accepted", (await replay(client, fixture.ordered, "?fromSeq=1")).status_code, 200)


async def check_queries(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """Two statements, both reads, with the filter and the order in the SQL."""
    await replay(client, fixture.ordered)  # warm: never count a connection's first statement

    with StatementCounter() as counter:
        counter.reset()
        await replay(client, fixture.ordered)
        three_events = counter.selects()
        writes = counter.writes()
        event_statements = counter.events_selects()

        counter.reset()
        await replay(client, fixture.isolated_a)
        one_event = counter.selects()

        counter.reset()
        await replay(client, fixture.silent)
        no_events = counter.selects()

    report.equal("a three-event replay is two statements", len(three_events), 4)
    report.equal("no N+1: a one-event replay costs the same two", len(one_event), len(three_events))
    report.equal("an empty replay costs the same two", len(no_events), len(three_events))
    report.check("the replay writes nothing at all", not writes, writes)

    report.equal("exactly one statement reads run_events", len(event_statements), 1)
    if event_statements:
        statement = " ".join(event_statements[0].split())
        report.check("the filter is in the SQL", "run_events.seq >=" in statement, statement)
        report.check("the order is in the SQL", "ORDER BY run_events.seq" in statement, statement)
        report.check("no pagination crept in", "LIMIT" not in statement.upper(), statement)

    report.check(
        "the other statement is the existence check on test_runs",
        any("test_runs" in statement for statement in three_events if "run_events" not in statement),
        three_events,
    )


async def check_leaks(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """Every replay body, scanned for what must not be in it."""
    run_ids = (
        fixture.silent,
        fixture.ordered,
        fixture.cancelled,
        fixture.tail,
        fixture.isolated_a,
        fixture.isolated_b,
    )

    bodies = [(await replay(client, run_id)).text for run_id in run_ids]
    bodies.append((await replay(client, str(uuid.uuid4()))).text)

    report.check(
        "no secret value appears in any replay body",
        not [text for text in bodies if SECRET_VALUE in text],
    )
    report.check(
        "no body carries a variables field",
        not [text for text in bodies if '"variables"' in text],
    )

    internal = await internal_uuids()
    leaked = sorted({value for text in bodies for value in internal if value in text})
    report.check("no internal UUID appears in any replay body", not leaked, leaked)

    event_ids = await event_ids_for_project()
    report.check(
        "no run_events.id appears, even though the rows exist",
        not [value for text in bodies for value in event_ids if value in text],
        event_ids,
    )
    report.check(
        "every record's runId is the run that was addressed",
        all(
            run_id in body_text
            for run_id, body_text in zip(run_ids, bodies)
            if run_id != fixture.silent
        ),
        run_ids,
    )
    report.check(
        "a run with no events carries no id at all, because it has no records",
        bodies[0].strip() == "[]",
        bodies[0],
    )


# --------------------------------------------------------------------------- #
# Direct SQL: the streams the API cannot write yet, and the keys it must not leak
# --------------------------------------------------------------------------- #

NESTED_PAYLOAD: dict[str, Any] = {
    "nested": {"items": [1, 2, 3], "ok": True},
    "count": 7,
    "label": "x",
    "empty": None,
    "unicode": "订单-确认",
}
"""A payload with every shape JSONB keeps and a naive re-serialisation would spoil.

It is written through the create-free path and compared back by value: if replay
re-encoded the payload -- escaped the non-ASCII, dropped the null, flattened the
nesting -- this is the check that says so.
"""


async def seed_events(fixture: Fixture) -> None:
    """Write the streams the API cannot write yet.

    The only event this service produces is ``run.cancelled``, and a cancellation
    produces exactly one, so every multi-event stream here is written by hand.
    The ordered run is deliberately written out of order *and* with timestamps
    that run against the sequence: whatever the endpoint returns has to be
    ``seq`` order, and a sort by ``created_at`` or by physical row order would
    answer differently.
    """
    await insert_events(
        fixture.ordered,
        [
            {
                "seq": 3,
                "event_type": "step.completed",
                "payload": {"step": 3},
                "at": BASE - timedelta(hours=2),
            },
            {
                "seq": 1,
                "event_type": "step.started",
                "payload": {"step": 1},
                "at": BASE,
            },
            {
                "seq": 2,
                "event_type": "assertion.completed",
                "payload": {"step": 2},
                "at": BASE - timedelta(hours=1),
            },
        ],
    )
    await insert_events(
        fixture.tail,
        [
            {
                "seq": 1,
                "event_type": "run.started",
                "payload": {"stage": "started"},
                "at": BASE,
            },
            {
                "seq": 2,
                "event_type": "step.started",
                "payload": {"stage": "stepping"},
                "at": BASE + timedelta(seconds=1),
            },
        ],
    )
    await insert_events(
        fixture.isolated_a,
        [
            {
                "seq": 1,
                "event_type": "step.started",
                "payload": NESTED_PAYLOAD,
                "at": BASE,
            }
        ],
    )
    await insert_events(
        fixture.isolated_b,
        [{"seq": 1, "event_type": "step.started", "payload": {"owner": "b"}, "at": BASE}],
    )


async def insert_events(run_id: str, events: list[dict[str, Any]]) -> None:
    async with engine.begin() as connection:
        for item in events:
            await connection.execute(
                text(
                    "INSERT INTO run_events (id, run_id, seq, event_type, payload, created_at) "
                    "VALUES (:id, :run, :seq, :type, CAST(:payload AS jsonb), :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "run": uuid.UUID(run_id),
                    "seq": item["seq"],
                    "type": item["event_type"],
                    "payload": json.dumps(item["payload"], ensure_ascii=False),
                    "at": item["at"],
                },
            )


async def event_rows(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT seq, event_type, payload, created_at FROM run_events "
                    "WHERE run_id = :id ORDER BY seq"
                ),
                {"id": uuid.UUID(run_id)},
            )
        ).mappings().all()

    return [dict(row) for row in rows]


async def event_ids_for_project() -> list[str]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id::text FROM run_events WHERE run_id IN "
                    "(SELECT id FROM test_runs WHERE project_id = "
                    "(SELECT id FROM projects WHERE public_id = :project))"
                ),
                {"project": PROJECT_PUBLIC_ID},
            )
        ).scalars().all()

    return list(rows)


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
)
"""Every internal key of the probe project except the two the contract allows.

``test_runs.id`` is the run's external id and is *supposed* to be in the body --
it is the ``runId`` of every record.  ``run_events.id`` is checked separately,
because a replay record that grew an ``id`` field is the specific mistake this
endpoint is most likely to make.
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

    print("verifying GET /api/runs/{run_id}/events\n")

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
