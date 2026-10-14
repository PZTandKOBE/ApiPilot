"""End-to-end verification of ``GET /api/runs/{run_id}/events/stream`` (7.2-E).

The same shape as the other four scripts -- a real PostgreSQL, the real app, the
real exception handlers, runs created by the real create endpoint -- with one
difference that the phase forced: **the standard test client cannot read this
response**.

``httpx.ASGITransport` collects the whole body before it hands back a response
(``ASGIResponseStream`` joins its chunks and yields once), which is the wrong
shape for a stream that ends when a run does: the request would never return.
``StreamClient`` below speaks the ASGI protocol directly instead -- the same
messages uvicorn sends and reads -- so a frame can be observed as it is
produced, and a client disconnect can be *delivered* rather than guessed at.
Everything that is not a stream still goes through httpx.

Every check runs; a failure is reported and the run continues, so one broken
assertion does not hide the rest.  Exit code is the number of failures.

    python scripts/verify_run_events_stream.py

It writes a project of its own (``prj_verify_stream``), reads it, and deletes it
again -- including on failure.  It does not touch any other project's rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
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
from backend.services import runs  # noqa: E402
from backend.services.spec_identity import hash_string, slugify  # noqa: E402

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_verify_stream"
ENVIRONMENT_PUBLIC_ID = "env_verify_stream"
BASE_URL = "http://verify.test/api"

GUEST_TOKEN = "run-events-stream-guest-session"
# The fixture inserts the digest the service computes for the token it names:
# the plaintext column is gone (Phase 8.5 Step 2), and these rows are ownership
# anchors for the fixture -- no business route reads an identity yet.
GUEST_TOKEN_HASH = hashlib.sha256(GUEST_TOKEN.encode("utf-8")).hexdigest()

# Every request this suite makes carries the fixture guest's token: the
# business routes verify a guest session (Phase 8.5 Step 3), and a suite that
# sent nothing would be measuring 401s.
GUEST_HEADERS = {"X-Guest-Session": GUEST_TOKEN}

# A second, entirely separate identity -- a real row, not the first guest's token
# under another name.  Access control is only measurable between two principals:
# asking the fixture guest for its own run proves nothing about somebody else.
OTHER_GUEST_TOKEN = "run-events-stream-other-guest-session"
OTHER_GUEST_TOKEN_HASH = hashlib.sha256(OTHER_GUEST_TOKEN.encode("utf-8")).hexdigest()
OTHER_GUEST_HEADERS = {"X-Guest-Session": OTHER_GUEST_TOKEN}

# A syntactically fine token that names no row.  Kept distinct from "no header"
# because the two travel different code paths into the same refusal.
UNKNOWN_GUEST_HEADERS = {"X-Guest-Session": "run-events-stream-token-that-names-nothing"}
"""Reused from ``seed_dev_data.py``: a project needs an owner and there is no
auth yet.  Created here if the seed has not been run."""

SPEC_TITLE = "Verify Stream API"
SPEC_DOCUMENT = (
    '{"openapi":"3.0.3","info":{"title":"Verify Stream API","version":"1.0.0"},'
    '"paths":{"/verify":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
)
SPEC_SLUG = f"{slugify(SPEC_TITLE)}_{hash_string(SPEC_DOCUMENT)}"
SPEC_ID = f"spec_{SPEC_SLUG}"

SECRET_VALUE = "s3cr3t-stream-do-not-echo"
SECRET_NAME = "VERIFY_TOKEN"

FRAME_FIELDS = ["at", "runId", "seq", "type"]
"""The fields every frame owns, plus whatever the payload contributes."""

BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
"""A fixed clock for the seeded events, so an order can be asserted exactly."""

STREAM_PATH = "/api/runs/{run_id}/events/stream"


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

    def seqs(self, label: str, frames: list[Frame], expected: list[int]) -> None:
        self.equal(label, [frame.event_id for frame in frames], expected)


def instant(value: str) -> datetime:
    """An ISO 8601 string as an instant, so ``Z`` and ``+00:00`` compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# A hand-driven ASGI client, for the one response that never ends
# --------------------------------------------------------------------------- #


@dataclass
class Frame:
    """One parsed SSE frame."""

    raw: str
    comment: str | None = None
    event: str | None = None
    event_id: int | None = None
    data: dict[str, Any] | None = None

    @property
    def is_ping(self) -> bool:
        return self.comment is not None


def parse_frames(text: str) -> tuple[list[Frame], str]:
    """Split every complete frame out of a buffer, and return what is left.

    Frames are separated by a blank line, so an incomplete tail is simply put
    back: a stream is read in pieces and a piece is not a frame.
    """
    frames: list[Frame] = []

    while "\n\n" in text:
        block, text = text.split("\n\n", 1)

        comment: str | None = None
        name: str | None = None
        event_id: int | None = None
        data_lines: list[str] = []

        for line in block.split("\n"):
            if line.startswith(":"):
                comment = line[1:].strip()
            elif line.startswith("id:"):
                event_id = int(line[3:].strip())
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        frames.append(
            Frame(
                raw=block,
                comment=comment,
                event=name,
                event_id=event_id,
                data=json.loads("\n".join(data_lines)) if data_lines else None,
            )
        )

    return frames, text


class StreamClient:
    """A streaming client for one response: real ASGI in, frames out.

    Three things it does that the ordinary client cannot: it reads frames as
    they arrive rather than at the end of the response, it notices the response
    finishing, and it can push ``http.disconnect`` into the request's receive
    channel so a client that walks away is a fact rather than a hope.
    """

    def __init__(
        self,
        app: Any,
        path: str,
        *,
        query: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._app = app
        self._path = path
        self._query = query.lstrip("?").encode()
        # The session header every real stream request carries (Phase 8.5
        # Step 3): a raw ASGI client bypasses the AsyncClient defaults, and a
        # stream opened without it is a 401 rather than a stream.  Passing an
        # explicit dict replaces the default rather than adding to it, which is
        # what makes an unauthenticated request expressible at all -- merging
        # would hand every "no credential" case the fixture's token back.
        # An explicit dict replaces the default instead of being merged into it,
        # because otherwise "no credential" is not expressible: a caller asking
        # for an unauthenticated request would silently be handed the fixture's
        # token.  Every caller that wants the token and something else passes
        # "GUEST_HEADERS | extra", which says so.
        self._headers = list((GUEST_HEADERS if headers is None else headers).items())
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._request_sent = False
        self._buffer = ""
        self._pending: list[Frame] = []
        self._updated = asyncio.Event()
        self._started = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.completed = False
        self.raw = ""
        self.errors: list[BaseException] = []

    async def __aenter__(self) -> StreamClient:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": self._query,
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in self._headers],
            "server": ("verify", 80),
            "client": ("127.0.0.1", 12345),
        }

        async def receive() -> dict[str, Any]:
            if not self._request_sent:
                self._request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}

            return await self._incoming.get()

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = int(message["status"])
                self.headers = {
                    key.decode().lower(): value.decode()
                    for key, value in message.get("headers", [])
                }
                self._started.set()
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    decoded = chunk.decode("utf-8")
                    self.raw += decoded
                    self._buffer += decoded
                    frames, self._buffer = parse_frames(self._buffer)
                    self._pending.extend(frames)
                if not message.get("more_body", False):
                    self.completed = True
                self._updated.set()

        async def run() -> None:
            try:
                await self._app(scope, receive, send)
            except BaseException as exc:  # recorded, never raised into the test
                self.errors.append(exc)
            finally:
                self._updated.set()

        self._task = asyncio.create_task(run())
        await asyncio.wait_for(self._started.wait(), timeout=5.0)

        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def read(self, *, want: int = 1, timeout: float = 3.0) -> list[Frame]:
        """Wait for up to ``want`` more frames, the end of the stream, or the deadline."""
        deadline = time.monotonic() + timeout

        while len(self._pending) < want and not self.completed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            self._updated.clear()
            try:
                await asyncio.wait_for(self._updated.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break

        taken = self._pending[:want]
        del self._pending[: len(taken)]

        return taken

    async def drain(self, *, timeout: float = 3.0) -> list[Frame]:
        """Everything the stream has to say before it stops talking or ends."""
        await self.wait_closed(timeout=timeout)

        taken = list(self._pending)
        self._pending.clear()

        return taken

    async def wait_closed(self, *, timeout: float = 3.0) -> bool:
        """Whether the server finished the response within the deadline."""
        deadline = time.monotonic() + timeout

        while not self.completed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            self._updated.clear()
            try:
                await asyncio.wait_for(self._updated.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return False

        return True

    async def disconnect(self) -> None:
        """Tell the application the client is gone, the way a socket close does."""
        self._incoming.put_nowait({"type": "http.disconnect"})

    @property
    def finished(self) -> bool:
        """Whether the application call has returned."""
        return self._task is not None and self._task.done()

    async def wait_finished(self, *, timeout: float = 1.0) -> bool:
        """Whether the application call returns within the deadline."""
        if self._task is None:
            return True

        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            return True

        return True

    async def aclose(self) -> None:
        """Leave the way a browser does: say goodbye, and only then pull the plug.

        The disconnect is delivered first so the server's loop gets the chance to
        notice and return on its own.  Cancelling straight away would work too --
        it is what a dropped socket looks like -- but it tears the loop down
        inside a database call, which is noise in the server log rather than a
        behaviour anybody is testing.
        """
        if self._task is None or self._task.done():
            return

        await self.disconnect()

        if await self.wait_finished(timeout=0.8):
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


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
        "name": {"text": "Verify stream plan"},
        "goal": {"text": "Produce a stream to follow"},
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
                    "name": "Verify run event stream",
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


async def remove_other_guest() -> None:
    """Delete the second identity this suite created, and nothing else.

    Only a session that owns no project is removed: a project is somebody's work,
    and a foreign key that refuses to orphan one is the database saying so.  The
    fixture guest is deliberately left alone -- it predates this script, and
    "cleanup_fixture" has always kept it.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM guest_sessions WHERE token_hash = :digest "
                "AND NOT EXISTS ("
                "SELECT 1 FROM projects WHERE projects.guest_session_id = guest_sessions.id"
                ")"
            ),
            {"digest": OTHER_GUEST_TOKEN_HASH},
        )


async def cleanup_fixture() -> None:
    """Remove the probe project and everything under it, in dependency order.

    ``test_runs`` takes ``run_scenarios``, ``run_steps``, ``run_assertions``,
    ``run_evidence`` and ``run_events`` with it; the plan and the spec go before
    the project because ``test_runs.plan_id`` is ``NO ACTION``.
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


def stream_path(run_id: str) -> str:
    return STREAM_PATH.format(run_id=run_id)


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


async def cancel(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    return await client.post(f"/api/runs/{run_id}/cancel")


async def replay(client: httpx.AsyncClient, run_id: str, query: str = "") -> httpx.Response:
    return await client.get(f"/api/runs/{run_id}/events{query}")


# --------------------------------------------------------------------------- #
# Statement counting
# --------------------------------------------------------------------------- #


class StatementCounter:
    """Counts the SQL the app actually issues, so a loop can be caught spinning."""

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


@dataclass
class Fixture:
    """The runs this script created, each one written by the real POST endpoint."""

    silent: str
    replay3: str
    replay5: str
    ordered: str
    live: str
    drained: str
    emptied: str
    unknown_type: str
    odd_payload: str


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


async def run_checks(report: Report) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://verify", headers=GUEST_HEADERS) as client:
        fixture = Fixture(
            silent=await create_run(client, "plan_stream_silent"),
            replay3=await create_run(client, "plan_stream_replay3"),
            replay5=await create_run(client, "plan_stream_replay5"),
            ordered=await create_run(client, "plan_stream_ordered"),
            live=await create_run(client, "plan_stream_live"),
            drained=await create_run(client, "plan_stream_drained"),
            emptied=await create_run(client, "plan_stream_emptied"),
            unknown_type=await create_run(client, "plan_stream_unknown"),
            odd_payload=await create_run(client, "plan_stream_odd"),
        )
        await seed_events(fixture)

        # Two runs that are already over before anything connects: one with an
        # event to drain, one with nothing at all.
        await cancel(client, fixture.drained)
        await cancel(client, fixture.emptied)
        await delete_events(fixture.emptied)

        try:
            await check_headers(app, report, fixture)
            await check_access_control(app, report, fixture)
            await check_replay(app, report, fixture)
            await check_resume(app, report, fixture)
            await check_bad_header(client, report, fixture)
            await check_validation(client, report, fixture)
            await check_unknown_runs(client, report)
            await check_live_cancel(client, app, report, fixture)
            await check_terminal_close(app, report, fixture)
            await check_stays_open(app, report, fixture)
            await check_heartbeat(app, report, fixture)
            await check_disconnect(app, report, fixture)
            await check_ordering(app, report, fixture)
            await check_isolation(app, report, fixture)
            await check_frame_shape(client, app, report, fixture)
            await check_odd_payloads(app, report, fixture)
            await check_unknown_type(app, report, fixture)
            await check_polling_cost(app, report, fixture)
            await check_leaks(client, app, report, fixture)
        finally:
            runs.SSE_POLL_INTERVAL_SECONDS = 0.5
            runs.SSE_HEARTBEAT_SECONDS = 30.0


def refusal_body(stream: StreamClient) -> dict[str, Any]:
    """A refusal parsed as JSON, or an empty object if it was not one.

    A refused request never becomes a stream, so what came back is the ordinary
    error envelope.  Returning an empty object rather than raising keeps the
    assertion that follows the thing that reports the difference.
    """
    try:
        parsed = json.loads(stream.raw)
    except (ValueError, TypeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


async def check_access_control(
    app: Any, report: Report, fixture: Fixture
) -> None:
    """Who is allowed to open this stream, measured against a second identity.

    Every other check in this suite sends the fixture guest's token, so the
    dependency that verifies one is exercised by all of them and *asserted* by
    none: a route that had forgotten to ask for an identity would still answer 200
    to every request this script makes.  The three refusals below are the missing
    half, and the cross-guest one is the only case that can distinguish "this
    route checks identity" from "this route checks ownership".

    The second guest is a real row with its own token, created here and removed in
    the "finally".  It owns nothing, which is the point: the fixture guest's run
    must be unreachable from it.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM guest_sessions WHERE token_hash = :digest"),
            {"digest": OTHER_GUEST_TOKEN_HASH},
        )
        await connection.execute(
            text(
                "INSERT INTO guest_sessions (id, token_hash, expires_at, last_seen_at) "
                "VALUES (:id, :digest, now() + interval '30 days', now())"
            ),
            {"id": uuid.uuid4(), "digest": OTHER_GUEST_TOKEN_HASH},
        )

    target = stream_path(fixture.replay3)

    try:
        # 1. No credential at all.  A real stream request carries the header; one
        #    that does not must be answered before a byte of the run is written.
        # Entering the client waits for the response head (StreamClient.__aenter__),
        # so by this line the status is known and no frame was ever produced.
        async with StreamClient(app, target, headers={}) as stream:  # no credential at all
            status = stream.status

        report.equal("a stream with no guest session is 401", status, 401)
        report.check(
            "...and is not an event stream",
            "text/event-stream" not in (stream.headers.get("content-type") or ""),
            stream.headers.get("content-type"),
        )
        report.check(
            "...and delivers no frame at all",
            parse_frames(stream.raw)[0] == [],
            stream.raw[:200],
        )
        report.check(
            "...and does not name the run it refused",
            fixture.replay3 not in stream.raw,
            stream.raw[:200],
        )

        body = refusal_body(stream)
        report.equal(
            "...and carries the guest-session-required code",
            body.get("code"),
            "guest-session-required",
        )
        report.equal(
            "...and a sentence the console can render",
            body.get("messageKey"),
            "console.runs.errors.unauthorized",
        )

        # 2. A credential that names nothing.  Unknown, expired and revoked
        #    tokens are one answer by contract, so this is not a second status.
        async with StreamClient(app, target, headers=UNKNOWN_GUEST_HEADERS) as stream:
            unknown_status = stream.status

        report.equal("a stream with an unknown guest session is 401", unknown_status, 401)
        report.check(
            "...and is not an event stream",
            "text/event-stream" not in (stream.headers.get("content-type") or ""),
            stream.headers.get("content-type"),
        )
        report.check(
            "...and delivers no frame at all",
            parse_frames(stream.raw)[0] == [],
            stream.raw[:200],
        )

        unknown_body = refusal_body(stream)
        report.equal(
            "...and is answered exactly like a missing one",
            unknown_body.get("code"),
            body.get("code"),
        )

        # 3. Somebody else's run, with a real identity of its own.  The answer is
        #    the one an unknown run gets, because a distinct status would turn this
        #    route into a way of asking whether a run exists.
        async with StreamClient(
            app, target, headers=OTHER_GUEST_HEADERS
        ) as stream:
            cross_status = stream.status

        report.equal("another guest's run is 404, not 403", cross_status, 404)
        report.check(
            "...and is not an event stream",
            "text/event-stream" not in (stream.headers.get("content-type") or ""),
            stream.headers.get("content-type"),
        )
        report.check(
            "...and delivers none of the owner's events",
            parse_frames(stream.raw)[0] == [],
            stream.raw[:200],
        )
        cross_body = refusal_body(stream)
        details = cross_body.get("details") or {}

        # What must not leak is anything *about* the other guest's run.  The id in
        # "details" is the one the caller itself put in the path -- test_runs has no
        # public id, so the path id is the row key, and echoing it back says only
        # what the caller already knew.  What would leak is a different id, or a
        # field describing a run this caller may not see.
        report.check(
            "...and names only the run the caller asked about",
            details.get("runId") == fixture.replay3,
            cross_body,
        )
        report.check(
            "...and says nothing else about it",
            set(details) <= {"runId"},
            cross_body,
        )
        report.equal(
            "...and answers with the run-not-found code",
            cross_body.get("code"),
            "run-not-found",
        )
        report.equal(
            "...and the same sentence an unknown run gets",
            cross_body.get("messageKey"),
            "console.runs.errors.notFound",
        )

        # 4. The owner, unchanged: the refusals above must not have been bought by
        #    making the stream harder to reach for the guest who does own it.
        async with StreamClient(app, target, query="?fromSeq=1") as stream:
            owner_status = stream.status
            owner_frames = await stream.read(want=1, timeout=3.0)

        report.equal("the owner still gets a stream", owner_status, 200)
        report.check(
            "...and still receives its events",
            [frame.event_id for frame in owner_frames] == [1],
            [frame.event_id for frame in owner_frames],
        )
    finally:
        await remove_other_guest()


async def check_headers(app: Any, report: Report, fixture: Fixture) -> None:
    """A stream is a stream on the wire, or it is a very slow JSON response."""
    async with StreamClient(app, stream_path(fixture.silent)) as stream:
        report.equal("the stream answers 200", stream.status, 200)
        report.equal(
            "the content type is an event stream",
            stream.headers.get("content-type"),
            "text/event-stream; charset=utf-8",
        )
        report.equal("...that must not be cached", stream.headers.get("cache-control"), "no-cache")
        report.equal(
            "...nor buffered by a proxy", stream.headers.get("x-accel-buffering"), "no"
        )
        report.equal(
            "...and that holds the connection open",
            stream.headers.get("connection"),
            "keep-alive",
        )
        report.check("no exception escaped the app", not stream.errors, stream.errors)


async def check_replay(app: Any, report: Report, fixture: Fixture) -> None:
    """The events that already exist arrive first, in order, on one connection."""
    async with StreamClient(app, stream_path(fixture.replay3), query="?fromSeq=1") as stream:
        frames = await stream.read(want=3, timeout=3.0)

        report.seqs("fromSeq=1 replays the whole stream", frames, [1, 2, 3])
        report.check(
            "...without the run having to finish first",
            not stream.completed,
            stream.completed,
        )
        report.equal(
            "every frame names an event type", [frame.event for frame in frames], ["step.started"] * 3
        )


async def check_resume(app: Any, report: Report, fixture: Fixture) -> None:
    """fromSeq is inclusive, Last-Event-ID is a receipt, and fromSeq wins."""
    async with StreamClient(app, stream_path(fixture.replay3), query="?fromSeq=2") as stream:
        report.seqs("fromSeq=2 starts at 2", await stream.read(want=2, timeout=3.0), [2, 3])

    async with StreamClient(app, stream_path(fixture.replay3), query="?fromSeq=3") as stream:
        report.seqs("fromSeq=3 is inclusive of 3", await stream.read(want=1, timeout=3.0), [3])

    async with StreamClient(app, stream_path(fixture.replay3), query="?fromSeq=4") as stream:
        report.equal("fromSeq past the end sends nothing", await stream.read(want=1, timeout=0.8), [])
        report.check("...and leaves the stream open", not stream.completed)

    async with StreamClient(
        app,
        stream_path(fixture.replay5),
        headers=GUEST_HEADERS | {"Last-Event-ID": "3"},
    ) as stream:
        report.seqs(
            "Last-Event-ID=3 resumes at 4",
            await stream.read(want=2, timeout=3.0),
            [4, 5],
        )

    async with StreamClient(
        app,
        stream_path(fixture.replay5),
        headers=GUEST_HEADERS | {"Last-Event-ID": "0"},
    ) as stream:
        report.seqs(
            "Last-Event-ID=0 is a client that has seen nothing",
            await stream.read(want=5, timeout=3.0),
            [1, 2, 3, 4, 5],
        )

    async with StreamClient(
        app,
        stream_path(fixture.replay5),
        query="?fromSeq=4",
        headers=GUEST_HEADERS | {"Last-Event-ID": "1"},
    ) as stream:
        report.seqs(
            "fromSeq wins over Last-Event-ID",
            await stream.read(want=2, timeout=3.0),
            [4, 5],
        )


async def check_bad_header(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """A resume point that is not a sequence number is refused, not ignored."""
    for value in ("abc", "-1", "1.5", ""):
        response = await client.get(
            stream_path(fixture.emptied), headers={"Last-Event-ID": value}
        )
        body = response.json()

        report.equal(f"Last-Event-ID={value!r} is rejected", response.status_code, 400)
        report.check(
            f"Last-Event-ID={value!r} answers with the error envelope",
            isinstance(body, dict),
            body,
        )

        if not isinstance(body, dict):
            continue

        report.equal(f"Last-Event-ID={value!r} carries the code", body.get("code"), "invalid-request")
        report.equal(
            f"Last-Event-ID={value!r} carries a renderable sentence",
            body.get("messageKey"),
            "console.runs.errors.loadFailed",
        )
        report.check(
            f"Last-Event-ID={value!r} names the field it refused",
            isinstance(body.get("details"), list)
            and body["details"]
            and body["details"][0].get("field") == "Last-Event-ID",
            body.get("details"),
        )
        report.check(f"Last-Event-ID={value!r} sends no params", "params" not in body, body)


async def check_validation(client: httpx.AsyncClient, report: Report, fixture: Fixture) -> None:
    """fromSeq is validated by the same machinery as everywhere else."""
    for query in ("?fromSeq=0", "?fromSeq=-1", "?fromSeq=abc", "?fromSeq=1.5"):
        response = await client.get(f"{stream_path(fixture.emptied)}{query}")
        body = response.json()

        report.equal(f"{query} is rejected", response.status_code, 422)
        report.check(f"{query} answers with the error envelope", isinstance(body, dict), body)

        if not isinstance(body, dict):
            continue

        report.equal(f"{query} carries the code", body.get("code"), "invalid-request")
        report.equal(
            f"{query} reports a load failure, not a failed create",
            body.get("messageKey"),
            "console.runs.errors.loadFailed",
        )
        report.check(
            f"{query} does not echo the request",
            "body" not in body and "params" not in body,
            body,
        )


async def check_unknown_runs(client: httpx.AsyncClient, report: Report) -> None:
    """The 404 is the one every other run route gives, and it happens first."""
    response = await client.get(stream_path(str(uuid.uuid4())))
    report.equal("an unknown run is 404", response.status_code, 404)

    body = response.json()
    report.equal("the 404 carries the run-not-found code", body.get("code"), "run-not-found")
    report.equal(
        "the 404 carries a renderable sentence",
        body.get("messageKey"),
        "console.runs.errors.notFound",
    )
    report.check("the 404 omits params rather than sending null", "params" not in body, body)

    malformed = await client.get(stream_path("not-a-uuid"))
    report.equal("an id that cannot be a UUID is 404, not 500", malformed.status_code, 404)
    report.equal("a malformed id gets the same code", malformed.json().get("code"), "run-not-found")
    report.equal(
        "a malformed id gets the same sentence",
        malformed.json().get("messageKey"),
        "console.runs.errors.notFound",
    )


async def check_live_cancel(
    client: httpx.AsyncClient, app: Any, report: Report, fixture: Fixture
) -> None:
    """The one event this service can really produce, delivered while connected."""
    async with StreamClient(app, stream_path(fixture.live), query="?fromSeq=1") as stream:
        first = await stream.read(want=1, timeout=3.0)
        report.seqs("the stream opens with the event that already existed", first, [1])
        report.equal(
            "...which is not the cancellation yet",
            first[0].event if first else None,
            "step.started",
        )

        pending = asyncio.create_task(cancel(client, fixture.live))
        arriving = await stream.read(want=1, timeout=5.0)
        response = await pending

        report.equal("cancelling while connected returns 200", response.status_code, 200)

        body = response.json()
        report.seqs("the cancellation is delivered live", arriving, [2])

        if arriving:
            frame = arriving[0]
            data = frame.data or {}

            report.equal("...as run.cancelled", frame.event, "run.cancelled")
            report.equal("...whose data agrees", data.get("type"), "run.cancelled")
            report.equal("...with the run's own durationMs", data.get("durationMs"), body["durationMs"])
            report.equal(
                "...and its finishedAt instant",
                instant(str(data.get("finishedAt"))),
                instant(body["finishedAt"]),
            )
            report.check("...and no eventType key", "eventType" not in data, sorted(data))
        else:
            report.check("...as run.cancelled", False, "no frame arrived")

        report.check(
            "the stream then closes by itself",
            await stream.wait_closed(timeout=5.0),
            "still open after the terminal event",
        )
        report.check("no exception escaped the app", not stream.errors, stream.errors)


async def check_terminal_close(app: Any, report: Report, fixture: Fixture) -> None:
    """A finished run says what it has and hangs up -- without a heartbeat."""
    async with StreamClient(app, stream_path(fixture.drained), query="?fromSeq=1") as stream:
        frames = await stream.drain(timeout=3.0)

        report.seqs("a finished run replays what it has", frames, [1])
        report.check("...and then the server ends the response", stream.completed)
        report.check(
            "...without a heartbeat standing in for an event",
            all(not frame.is_ping for frame in frames),
            [frame.raw for frame in frames],
        )
        report.check("no exception escaped the app", not stream.errors, stream.errors)

    async with StreamClient(app, stream_path(fixture.emptied)) as stream:
        frames = await stream.drain(timeout=2.0)

        report.equal("a finished run with nothing to say sends nothing", frames, [])
        report.check("...and closes immediately", stream.completed)


async def check_stays_open(app: Any, report: Report, fixture: Fixture) -> None:
    """A run that has not finished keeps the connection, even in silence."""
    async with StreamClient(app, stream_path(fixture.silent)) as stream:
        frames = await stream.read(want=1, timeout=0.8)

        report.equal("a queued run with no events sends nothing yet", frames, [])
        report.check("...and stays connected", not stream.completed, stream.completed)
        report.check("no exception escaped the app", not stream.errors, stream.errors)


async def check_heartbeat(app: Any, report: Report, fixture: Fixture) -> None:
    """A quiet stream says so, on its own interval, and says nothing else."""
    report.equal(
        "the production poll interval is half a second",
        runs.SSE_POLL_INTERVAL_SECONDS,
        0.5,
    )
    report.equal(
        "the production heartbeat is thirty seconds",
        runs.SSE_HEARTBEAT_SECONDS,
        30.0,
    )

    before = await event_count(fixture.silent)
    runs.SSE_POLL_INTERVAL_SECONDS = 0.05
    runs.SSE_HEARTBEAT_SECONDS = 0.25

    try:
        async with StreamClient(app, stream_path(fixture.silent)) as stream:
            # One window long enough for several heartbeats and many polls: the
            # first says they happen, the second says they are not per-poll.
            frames = await stream.read(want=100, timeout=1.2)
            pings = [frame for frame in frames if frame.is_ping]

            report.check("a quiet stream says something", len(pings) >= 3, len(pings))
            report.check(
                "...on its own interval rather than every poll",
                len(pings) <= 8,
                len(pings),
            )
            report.check(
                "...as SSE comments, not events",
                all(frame.event is None and frame.data is None for frame in pings),
                [frame.raw for frame in pings],
            )
            report.check(
                "...with no id to resume from",
                all(frame.event_id is None for frame in pings),
                [frame.raw for frame in pings],
            )
            report.check("no exception escaped the app", not stream.errors, stream.errors)
    finally:
        runs.SSE_POLL_INTERVAL_SECONDS = 0.5
        runs.SSE_HEARTBEAT_SECONDS = 30.0

    report.equal(
        "a heartbeat is not an event: the row count is unchanged",
        await event_count(fixture.silent),
        before,
    )


async def check_disconnect(app: Any, report: Report, fixture: Fixture) -> None:
    """A client that walks away stops the queries instead of leaving them running."""
    runs.SSE_POLL_INTERVAL_SECONDS = 0.05

    try:
        stream = StreamClient(app, stream_path(fixture.silent))

        async with stream:
            with StatementCounter() as counter:
                counter.reset()
                await stream.read(want=1, timeout=0.4)
                while_listening = len(counter.selects())

                await stream.disconnect()
                await asyncio.sleep(0.4)

                counter.reset()
                await asyncio.sleep(0.4)
                after_disconnect = len(counter.selects())

        report.check(
            "the stream polls while a client is listening",
            while_listening >= 2,
            while_listening,
        )
        report.equal("...and stops polling once the client is gone", after_disconnect, 0)
        report.check(
            "...by the application call returning",
            await stream.wait_finished(timeout=1.5),
            "the stream is still running",
        )
        report.check("no exception escaped the app", not stream.errors, stream.errors)
    finally:
        runs.SSE_POLL_INTERVAL_SECONDS = 0.5


async def check_ordering(app: Any, report: Report, fixture: Fixture) -> None:
    """seq is the order -- not insertion order, and not the stored timestamps."""
    async with StreamClient(app, stream_path(fixture.ordered), query="?fromSeq=1") as stream:
        frames = await stream.read(want=3, timeout=3.0)

    report.seqs("events arrive in seq order", frames, [1, 2, 3])

    stamps = [instant(str((frame.data or {}).get("at"))) for frame in frames]
    report.check(
        "...even though the stored timestamps run backwards",
        stamps == sorted(stamps, reverse=True),
        [str(stamp) for stamp in stamps],
    )


async def check_isolation(app: Any, report: Report, fixture: Fixture) -> None:
    """One run's stream never carries another run's events."""
    async with StreamClient(app, stream_path(fixture.replay3), query="?fromSeq=1") as stream:
        frames = await stream.read(want=3, timeout=3.0)

        report.equal(
            "every frame names the run that was addressed",
            sorted({(frame.data or {}).get("runId") for frame in frames}),
            [fixture.replay3],
        )
        report.check("the other run's id never appears", fixture.replay5 not in stream.raw)


async def check_frame_shape(
    client: httpx.AsyncClient, app: Any, report: Report, fixture: Fixture
) -> None:
    """The frame is the frontend's RunEvent, and it says what replay says."""
    async with StreamClient(app, stream_path(fixture.live), query="?fromSeq=1") as stream:
        frames = await stream.drain(timeout=3.0)

    report.seqs("the finished run replays as two frames", frames, [1, 2])
    report.check(
        "every id is the seq itself",
        all(isinstance(frame.event_id, int) for frame in frames),
        [frame.event_id for frame in frames],
    )

    records = {
        item["seq"]: item
        for item in (await replay(client, fixture.live, "?fromSeq=1")).json()
    }
    report.equal("replay and stream see the same number of events", len(records), len(frames))

    for frame in frames:
        data = frame.data or {}
        stored = records.get(int(frame.event_id or 0), {})

        report.equal(f"seq {frame.event_id}: the frame names the run", data.get("runId"), fixture.live)
        report.equal(
            f"seq {frame.event_id}: the frame's type is the record's eventType",
            data.get("type"),
            stored.get("eventType"),
        )
        report.equal(
            f"seq {frame.event_id}: the frame's at is the record's at, character for character",
            data.get("at"),
            stored.get("at"),
        )
        report.equal(f"seq {frame.event_id}: the payload is flattened, not nested", "payload" in data, False)

    cancelled = next((frame for frame in frames if frame.event == "run.cancelled"), None)

    if cancelled is None:
        report.check("the cancellation frame is there to inspect", False, "no run.cancelled frame")
    else:
        data = cancelled.data or {}
        stored = records[int(cancelled.event_id or 0)]

        report.equal(
            "the cancellation frame carries exactly the union's fields",
            sorted(data),
            sorted([*FRAME_FIELDS, *stored["payload"]]),
        )
        report.equal(
            "...with the payload's values",
            {key: data.get(key) for key in stored["payload"]},
            stored["payload"],
        )
        report.check("...and no eventType", "eventType" not in data, sorted(data))


async def check_odd_payloads(app: Any, report: Report, fixture: Fixture) -> None:
    """Payloads the union cannot express are carried, not dropped and not fatal."""
    async with StreamClient(app, stream_path(fixture.odd_payload), query="?fromSeq=1") as stream:
        frames = await stream.read(want=3, timeout=3.0)
        report.check("no exception escaped the app", not stream.errors, stream.errors)

    report.seqs("all three odd payloads still arrive", frames, [1, 2, 3])

    if len(frames) != 3:
        return

    array_frame, null_frame, collision_frame = frames
    array_data = array_frame.data or {}
    null_data = null_frame.data or {}
    collision_data = collision_frame.data or {}

    report.equal("a list payload travels whole under payload", array_data.get("payload"), [1, 2, 3])
    report.check(
        "...and does not become the frame",
        array_data.get("type") == "step.started",
        sorted(array_data),
    )
    report.check(
        "a null payload is carried rather than crashing the stream",
        "payload" in null_data and null_data["payload"] is None,
        null_data,
    )
    report.equal("a payload cannot forge the seq", collision_data.get("seq"), 3)
    report.equal("...nor the event type", collision_data.get("type"), "step.started")
    report.equal("...nor the run", collision_data.get("runId"), fixture.odd_payload)
    report.check("...nor the timestamp", collision_data.get("at") != "nope", collision_data.get("at"))
    report.equal("...and keeps every key the frame does not own", collision_data.get("kept"), "yes")


async def check_unknown_type(app: Any, report: Report, fixture: Fixture) -> None:
    """An event type this service has never heard of is streamed, not turned into a 500."""
    async with StreamClient(app, stream_path(fixture.unknown_type), query="?fromSeq=1") as stream:
        frames = await stream.read(want=2, timeout=3.0)
        report.check("an unknown event type is still delivered", not stream.errors, stream.errors)

    report.seqs("both events arrive", frames, [1, 2])

    if len(frames) != 2:
        return

    future, weird = frames

    report.equal("the SSE event name is the stored type", future.event, "future.event")
    report.equal("...and so is the discriminant", (future.data or {}).get("type"), "future.event")
    report.equal("...with its payload flattened", (future.data or {}).get("note"), "from a later phase")

    report.equal(
        "a type carrying a line break is sanitised on the event line",
        weird.event,
        "weird name",
    )
    report.equal(
        "...and kept verbatim in the data",
        (weird.data or {}).get("type"),
        "weird\nname",
    )
    report.check("...without splitting the frame in two", weird.raw.count("event:") == 1, weird.raw)


async def check_polling_cost(app: Any, report: Report, fixture: Fixture) -> None:
    """Production timing again: about one read per interval, and never a spin."""
    async with StreamClient(app, stream_path(fixture.silent)) as stream:
        with StatementCounter() as counter:
            counter.reset()
            await stream.read(want=1, timeout=1.2)
            selects = counter.selects()

        report.check("an idle stream reads a few times a second", 2 <= len(selects) <= 5, len(selects))
        report.check("...and never spins", len(selects) < 8, len(selects))
        report.check(
            "...one statement per pass, with the run and its events in the same read",
            all("run_events" in statement and "test_runs" in statement for statement in selects),
            selects[:1],
        )


async def check_leaks(client: httpx.AsyncClient, app: Any, report: Report, fixture: Fixture) -> None:
    """Every stream this endpoint can produce, scanned for what must not be in it."""
    talking = (fixture.replay3, fixture.live, fixture.unknown_type, fixture.odd_payload)
    texts: list[str] = []

    for run_id in talking:
        async with StreamClient(app, stream_path(run_id), query="?fromSeq=1") as stream:
            await stream.read(want=1, timeout=1.0)
            texts.append(stream.raw)

    async with StreamClient(app, stream_path(fixture.drained), query="?fromSeq=1") as stream:
        await stream.drain(timeout=3.0)
        texts.append(stream.raw)

    report.check("the streams had something to scan", all(texts), [len(text) for text in texts])
    report.check(
        "no secret value appears in any stream",
        not [text for text in texts if SECRET_VALUE in text],
    )
    report.check(
        "no stream carries a variables field",
        not [text for text in texts if '"variables"' in text],
    )
    report.check(
        "no stream carries the replay record's own key",
        not [text for text in texts if "eventType" in text],
    )
    report.check(
        "the runId that is sent is the external one",
        all(run_id in texts[index] for index, run_id in enumerate(talking)),
    )

    internal = await internal_uuids()
    leaked = sorted({value for text in texts for value in internal if value in text})
    report.check("no internal UUID appears in any stream", not leaked, leaked)

    event_ids = await event_ids_for_project()
    report.check(
        "no run_events.id appears in any stream",
        not [value for text in texts for value in event_ids if value in text],
        event_ids,
    )


# --------------------------------------------------------------------------- #
# Direct SQL: the streams the API cannot write yet, and the keys it must not leak
# --------------------------------------------------------------------------- #


async def seed_events(fixture: Fixture) -> None:
    """Write the streams this service cannot write yet.

    Only a cancellation produces an event today, and it produces exactly one, so
    every other stream -- the ordered one, the five-event one, the payloads the
    union cannot express -- is written by hand.  The ordered run is written out of
    order and with timestamps that run against the sequence, so an implementation
    that sorted by anything but ``seq`` would be caught here.
    """
    await insert_events(
        fixture.replay3,
        [
            (1, "step.started", {"index": 1}, BASE),
            (2, "step.started", {"index": 2}, BASE + timedelta(seconds=1)),
            (3, "step.started", {"index": 3}, BASE + timedelta(seconds=2)),
        ],
    )
    await insert_events(
        fixture.replay5,
        [
            (seq, "step.started", {"index": seq}, BASE + timedelta(seconds=seq))
            for seq in range(1, 6)
        ],
    )
    await insert_events(
        fixture.ordered,
        [
            (3, "step.completed", {"index": 3}, BASE - timedelta(hours=2)),
            (1, "step.started", {"index": 1}, BASE),
            (2, "assertion.completed", {"index": 2}, BASE - timedelta(hours=1)),
        ],
    )
    await insert_events(
        fixture.live,
        [(1, "step.started", {"index": 1}, BASE)],
    )
    await insert_events(
        fixture.unknown_type,
        [
            (1, "future.event", {"note": "from a later phase"}, BASE),
            (2, "weird\nname", {"note": "a name no protocol field can hold"}, BASE),
        ],
    )
    await insert_events(
        fixture.odd_payload,
        [
            (1, "step.started", [1, 2, 3], BASE),
            (2, "step.started", None, BASE),
            (3, "step.started", {"seq": 99, "type": "bogus", "runId": "nope", "at": "nope", "kept": "yes"}, BASE),
        ],
    )


async def insert_events(
    run_id: str, events: list[tuple[int, str, Any, datetime]]
) -> None:
    async with engine.begin() as connection:
        for seq, event_type, payload, at in events:
            await connection.execute(
                text(
                    "INSERT INTO run_events (id, run_id, seq, event_type, payload, created_at) "
                    "VALUES (:id, :run, :seq, :type, CAST(:payload AS jsonb), :at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "run": uuid.UUID(run_id),
                    "seq": seq,
                    "type": event_type,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "at": at,
                },
            )


async def delete_events(run_id: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM run_events WHERE run_id = :id"), {"id": uuid.UUID(run_id)}
        )


async def event_count(run_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM run_events WHERE run_id = :id"),
                    {"id": uuid.UUID(run_id)},
                )
            ).scalar_one()
        )


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

``test_runs.id`` is the run's external id and is *supposed* to be in a frame -- it
is the ``runId`` of every event.  ``run_events.id`` is checked separately, because
a frame that grew one is the mistake this endpoint is most likely to make.
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

    print("verifying GET /api/runs/{run_id}/events/stream\n")

    try:
        await ensure_fixture()
        await run_checks(report)
    finally:
        await cleanup_fixture()
        # The second identity is this suite's own, so it leaves with the rest.
        await remove_other_guest()
        await engine.dispose()

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
