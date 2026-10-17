"""The run as an HTTP resource: the event stream, and stopping a run.

C17 proved the executor writes the right rows.  This file is about the two things
the *outside* sees and C17 never exercised: the event endpoints a client actually
calls, and the cancel endpoint that stops a run.

**The HTTP surface is real.**  Every request here goes through
NaN
NaN
NaN
NaN

**The stream is read as a stream.**  httpx.ASGITransport implements
NaN
NaN
NaN
NaN

**The cancel is the product's.**  POST /api/runs/{id}/cancel is called over HTTP
NaN
NaN
NaN
NaN

Nothing here talks to a real API: the executor's httpx.AsyncClient is replaced by a
NaN
NaN
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import uuid
from datetime import datetime, timedelta, timezone
from itertools import chain
from typing import Any, AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from backend.app import create_app
from backend.db.models.project import Environment
from backend.db.models.result import RunAssertion, RunEvent, RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.db.models.user import GuestSession
from backend.schemas.run import RunCreateRequest
from backend.services import guest_session, run_executor, runs
from backend.services.guest_session import hash_token

# The C17 module built the plan fixtures; reusing them keeps one definition of the
# orders document, the derived spec id and the plan tree.
from tests.test_run_execution import (
    ASSERT_STEP,
    CREATE_STEP,
    ENVIRONMENT_ID,
    EXTRACT_STEP,
    PLAN_ID,
    READ_STEP,
    SCENARIO_KEY,
    _plan_payload,
    _project_public_id,
    _run_body,
    _step_rows,
)

pytestmark = pytest.mark.anyio

FROZEN_EVENT_TYPES = frozenset(
    {
        "run.started",
        "step.started",
        "step.completed",
        "assertion.completed",
        "step.failed",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)

GUEST_HEADER = "X-Guest-Session"
GUEST_WRONG_CODE = "guest-session-required"

# Every HTTP read is bounded.  The stream ends by itself for a terminal run; the
# timeout exists so a regression fails the test rather than hanging the suite.
HTTP_TIMEOUT = 30.0


@asynccontextmanager
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    """A real ASGI client for the real app: no network, but the whole stack."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://c18", timeout=HTTP_TIMEOUT
    ) as client:
        yield client


async def _seed_owner(fixtures, stack) -> tuple[str, uuid.UUID]:
    """A guest session whose token this file knows, owning the project.

    The shared fixtures build a guest and a project with a random token this test
    could not present.  The run routes answer 404 for a run the caller does not own
    -- by design, so an id cannot be guessed -- so the project has to belong to the
    guest that will authenticate.  Only the guest and the project are new; the spec
    and the environment come from the shared fixtures.
    """
    from backend.db.models.project import Project

    token = guest_session.generate_token()
    now = datetime.now(timezone.utc)
    guest = GuestSession(
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
        revoked_at=None,
    )
    fixtures.session.add(guest)
    await fixtures._keep(GuestSession, guest)

    project = Project(
        guest_session_id=guest.id,
        public_id="c18prj_" + uuid.uuid4().hex[:12],
        name="C18 project",
        description="Created by backend/tests; deleted by its own cleanup.",
    )
    fixtures.session.add(project)
    await fixtures._keep(Project, project)
    await fixtures.commit()
    return token, project.id


async def _seed_environment(fixtures, project_id: uuid.UUID) -> uuid.UUID:
    row = Environment(
        project_id=project_id,
        public_id=ENVIRONMENT_ID,
        name="C18 environment",
        kind="development",
        base_url="http://127.0.0.1:9",
    )
    fixtures.session.add(row)
    return await fixtures._keep(Environment, row)


async def _create_run(fixtures, project_id: uuid.UUID, monkeypatch, *, body: dict[str, Any] | None = None):
    """Create a run through the service, with scheduling suppressed.

    The HTTP create route is C17 territory and it schedules the executor, which
    would race the tests below.  Suppressing scheduling keeps this file about the
    stream and the cancel; the run rows, the snapshot and the events are the
    product's.
    """
    if body is None:
        await _seed_environment(fixtures, project_id)
        await fixtures.commit()
        body = _run_body(await _project_public_id(fixtures, project_id))

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    response = await runs.create_run(
        fixtures.session,
        project_id=body["projectId"],
        payload=RunCreateRequest.model_validate(body),
    )
    return uuid.UUID(str(response.id))


async def _event_rows(session, run_id: uuid.UUID) -> list[RunEvent]:
    return list(
        (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            )
        ).scalars()
    )


async def _scenario_rows(session, run_id: uuid.UUID) -> list[RunScenario]:
    return list(
        (
            await session.execute(
                select(RunScenario)
                .where(RunScenario.run_id == run_id)
                .order_by(RunScenario.sort_order, RunScenario.scenario_key)
            )
        ).scalars()
    )


class _ScriptedClient(httpx.AsyncClient):
    """The executor's client, answering from a script.

    `before` runs before the response is returned, which is where the cancel test
    parks the executor on the wire.  `sent` is the order the executor called in.
    """

    sent: list[httpx.Request] = []
    before: Any = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(self._answer)
        super().__init__(*args, **kwargs)

    @property
    def _is_the_executors(self) -> bool:
        return isinstance(self._transport, httpx.MockTransport)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        """Never used: send() answers the executor instead."""
        raise AssertionError("the synchronous handler must not be used")

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        # Clients that brought their own transport -- this test's ASGI client, for
        # one -- go to the real implementation.  Only the client the executor builds
        # itself, which has no transport of its own, is answered from the script.
        if not self._is_the_executors:
            return await super().send(request, **kwargs)

        type(self).sent.append(request)
        if type(self).before is not None:
            await type(self).before(request)
        if request.method == "GET" and request.url.path == "/orders/order_1":
            return httpx.Response(200, json={"orderId": "order_1", "status": "open"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": "order_2"})
        return httpx.Response(404, json={"error": "unexpected target"})


def _install_scripted_client(monkeypatch, before=None) -> type[_ScriptedClient]:
    _ScriptedClient.sent = []
    _ScriptedClient.before = before
    monkeypatch.setattr(httpx, "AsyncClient", _ScriptedClient)
    return _ScriptedClient


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """The frames a client would act on: id, event name and the decoded data."""
    frames: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or not line:
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if "data" in fields:
            frames.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return frames


# NaN #
# 1. The event list over HTTP
# NaN #


async def test_event_list_route_returns_the_stored_history(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """GET /api/runs/{id}/events with a real guest session.

    The route, the auth dependency and the response model are all exercised; the
    comparison is against the rows, so a response that dropped or reordered
    anything fails here.
    """
    token, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)
    await run_executor.execute_run(run_id)

    stored = await _event_rows(read_session, run_id)
    assert stored, "the run produced no events to read"

    async with app_client() as client:
        response = await client.get(
            f"/api/runs/{run_id}/events", headers={GUEST_HEADER: token}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["seq"] for item in body] == [event.seq for event in stored]
    # The wire names it eventType; the payload lands next to it, unmodified.
    assert [item["eventType"] for item in body] == [
        event.event_type for event in stored
    ]


async def test_event_list_route_honours_from_seq(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """fromSeq is an inclusive resume point, over HTTP."""
    token, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)
    await run_executor.execute_run(run_id)

    stored = await _event_rows(read_session, run_id)
    cursor = stored[2].seq

    async with app_client() as client:
        response = await client.get(
            f"/api/runs/{run_id}/events",
            params={"fromSeq": cursor},
            headers={GUEST_HEADER: token},
        )

    assert response.status_code == 200, response.text
    assert [item["seq"] for item in response.json()] == [
        event.seq for event in stored if event.seq >= cursor
    ]


@pytest.mark.parametrize("headers", [{}, {GUEST_HEADER: "not-a-real-token"}], ids=["missing", "invalid"])
async def test_event_list_route_refuses_without_a_valid_guest_session(
    fixtures, stack, monkeypatch, headers
) -> None:
    """No session, or a token that does not exist, is the contract's refusal."""
    _, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)

    async with app_client() as client:
        response = await client.get(f"/api/runs/{run_id}/events", headers=headers)

    assert response.status_code == 401, response.text
    assert response.json()["code"] == GUEST_WRONG_CODE


# NaN #
# 2. The SSE stream, read as a stream
# NaN #


async def _read_stream(client, run_id, headers) -> tuple[httpx.Response, str]:
    """Read a whole stream, bounded, and hand back the response and its frames.

    aiter_lines is used so the frames arrive as they are yielded rather than after
    the response closes; the timeout is the guard against a stream that forgets to
    end.
    """
    async def _read() -> tuple[httpx.Response, str]:
        async with client.stream(
            "GET", f"/api/runs/{run_id}/events/stream", headers=headers
        ) as response:
            body = "".join([chunk async for chunk in response.aiter_text()])
            return response, body

    return await asyncio.wait_for(_read(), timeout=HTTP_TIMEOUT)


async def test_sse_stream_returns_the_contract_frames(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The stream, over HTTP, for a run that has already finished.

    A terminal run is the finite case: the stream yields what is stored and then
    ends by itself, which is what makes it readable in a test at all.
    """
    token, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)
    await run_executor.execute_run(run_id)

    stored = await _event_rows(read_session, run_id)

    async with app_client() as client:
        response, body = await _read_stream(client, run_id, {GUEST_HEADER: token})
        status = response.status_code
        media = response.headers.get("content-type", "")

    assert status == 200, body
    assert media.startswith("text/event-stream"), media

    frames = _parse_sse(body)
    assert frames, "the stream carried no frames"

    # id is the seq, event repeats the type, data is the stored event.
    assert [frame["id"] for frame in frames] == [event.seq for event in stored]
    assert [frame["event"] for frame in frames] == [event.event_type for event in stored]
    for frame, event in zip(frames, stored):
        assert frame["data"]["seq"] == event.seq
        assert frame["data"]["type"] == event.event_type

    assert frames[0]["event"] == "run.started"
    assert frames[-1]["event"] == "run.completed"


async def test_sse_stream_resumes_from_last_event_id(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Last-Event-ID is a receipt: the stream resumes one past it.

    Both ends of the range are checked: a cursor in the middle returns the tail
    without repeating what it acknowledges, and a cursor at the last event returns
    nothing at all.
    """
    token, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)
    await run_executor.execute_run(run_id)

    stored = await _event_rows(read_session, run_id)
    assert len(stored) >= 3, "this test needs a stream with a middle"

    acked = stored[2]
    last = stored[-1]

    async with app_client() as client:
        first, body = await _read_stream(client, run_id, {GUEST_HEADER: token})
        resumed, resumed_body = await _read_stream(
            client, run_id, {GUEST_HEADER: token, "Last-Event-ID": str(acked.seq)}
        )
        ended, ended_body = await _read_stream(
            client, run_id, {GUEST_HEADER: token, "Last-Event-ID": str(last.seq)}
        )

    assert first.status_code == 200 and resumed.status_code == 200
    assert ended.status_code == 200

    first_frames = _parse_sse(body)
    resumed_frames = _parse_sse(resumed_body)
    ended_frames = _parse_sse(ended_body)

    # The acknowledgement is not repeated, and nothing after it is lost.
    assert [frame["id"] for frame in first_frames] == [event.seq for event in stored]
    assert [frame["id"] for frame in resumed_frames] == [
        event.seq for event in stored if event.seq > acked.seq
    ]
    assert not any(frame["id"] <= acked.seq for frame in resumed_frames)
    assert [frame["id"] for frame in ended_frames] == []


async def test_sse_stream_refuses_without_a_valid_guest_session(
    fixtures, stack, monkeypatch
) -> None:
    """An unauthenticated stream is refused before any frame is produced."""
    _, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)

    async with app_client() as client:
        response = await client.get(f"/api/runs/{run_id}/events/stream")

    assert response.status_code == 401, response.text
    assert response.json()["code"] == GUEST_WRONG_CODE


# NaN #
# 3. Cancelling a run that is genuinely running
# NaN #


def _two_scenario_body(project_public_id: str) -> dict[str, Any]:
    """The C17 plan plus a second scenario that never gets to run."""
    body = _run_body(project_public_id)
    scenarios = body["plan"]["scenarios"]
    second = json.loads(json.dumps(scenarios[0]))
    second["id"] = "scenario_c18_second"
    second["index"] = 1
    second["name"] = {"text": "never started"}
    for position, step in enumerate(second["steps"]):
        step["id"] = step["id"].replace("step_c17", "step_c18")
        step["index"] = position
    for assertion in second["assertions"]:
        assertion["id"] = assertion["id"].replace("assertion_c17", "assertion_c18")
    scenarios.append(second)
    return body


async def test_cancel_over_http_stops_a_running_run(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Cancel while the executor is on the wire, and check what settles."""
    token, project_id = await _seed_owner(fixtures, stack)
    await _seed_environment(fixtures, project_id)
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, project_id)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def before(request: httpx.Request) -> None:
        # Only the first call parks: the executor must be mid-step, not mid-flight
        # for every request it will ever make.
        if not entered.is_set():
            entered.set()
            await release.wait()

    client_type = _install_scripted_client(monkeypatch, before=before)
    run_id = await _create_run(fixtures, project_id, monkeypatch, body=_two_scenario_body(public_id))

    executor = asyncio.create_task(run_executor.execute_run(run_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=HTTP_TIMEOUT)

        # The run really is running: this is read from the database, not assumed.
        running = (
            await read_session.execute(select(_TestRun.status).where(_TestRun.id == run_id))
        ).scalar_one()
        assert running == "running"

        requests_before_cancel = len(client_type.sent)

        async with app_client() as client:
            cancelled = await client.post(
                f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
            )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        release.set()
        await asyncio.wait_for(executor, timeout=HTTP_TIMEOUT)
    finally:
        release.set()
        if not executor.done():
            executor.cancel()
            await asyncio.gather(executor, return_exceptions=True)

    # -- the run --
    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "cancelled"
    assert run.finished_at is not None
    assert run.error_code is None

    # -- the events --
    events = await _event_rows(read_session, run_id)
    kinds = [event.event_type for event in events]
    assert kinds.count("run.cancelled") == 1
    assert "run.completed" not in kinds
    assert "run.failed" not in kinds
    # Exactly one terminal event for the run, and it is the cancellation.
    terminal = ["run.cancelled", "run.completed", "run.failed"]
    assert [kind for kind in kinds if kind in terminal] == ["run.cancelled"]

    # The executor writes the settling step.completed for the step the cancel
    # caught on the wire, and that frame can land on either side of run.cancelled:
    # the terminal event is written by the cancel route in its own transaction
    # while the step is still finishing.  The frozen contract fixes the event
    # names and a dense seq, not an ordering between a concurrent cancel and an
    # in-flight step.  What is invariant -- and asserted here -- is that the
    # executor announced exactly one step, it was stopped there, and no second
    # terminal event was written.
    assert kinds.count("step.started") == 1, (
        "the executor announced one step before it was stopped"
    )
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert set(kinds) <= FROZEN_EVENT_TYPES

    # -- the tree --
    scenarios = await _scenario_rows(read_session, run_id)
    assert len(scenarios) == 2
    first, second = scenarios

    # The scenario the cancel caught is settled with the rest of the run.  A terminal
    # run holding a scenario that still claimed to be running was the C19 gap;
    # _settle_unfinished now settles a started scenario too (C20).
    assert first.status == "skipped"
    # The scenario that never began is settled to skipped.
    assert second.status == "skipped"

    first_steps = {step.step_key: step for step in await _step_rows(read_session, first.id)}
    # The step the cancel caught on the wire: announced, then interrupted.  C19 made
    # the cancel stop the request instead of waiting for it, so this step is skipped
    # rather than passed, and its completion is never announced.  The case where a
    # step really did finish first is covered by
    # test_run_cancel_race.py::test_cancel_between_steps_keeps_finished_work_and_stops_the_rest.
    assert first_steps[READ_STEP].status == "skipped"
    assert first_steps[EXTRACT_STEP].status == "skipped"
    assert first_steps[CREATE_STEP].status == "skipped"
    assert first_steps[ASSERT_STEP].status == "skipped"

    second_steps = await _step_rows(read_session, second.id)
    assert all(step.status == "skipped" for step in second_steps)

    assertions = list(
        (
            await read_session.execute(
                select(RunAssertion).where(RunAssertion.run_scenario_id == first.id)
            )
        ).scalars()
    )
    assert all(item.status != "passed" for item in assertions), (
        "a cancelled run must not report asserts it never judged as passed"
    )

    # -- the execution --
    assert run_id not in run_executor._RUNNING_TASKS
    assert len(client_type.sent) == requests_before_cancel, (
        "the cancelled run sent more requests after the cancel"
    )


async def test_cancelling_a_finished_run_changes_nothing(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Cancelling twice is not an error and not a second transition.

    The same endpoint is used before and after the run finishes, so the two halves
    of the route's promise -- 200 either way, one transition at most -- are both
    observed rather than inferred.
    """
    token, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)

    # Cancel a queued run: queued -> cancelled, no steps ever started.
    async with app_client() as client:
        first = await client.post(
            f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
        )
        second = await client.post(
            f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
        )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.json()["status"] == "cancelled"

    events = await _event_rows(read_session, run_id)
    assert [event.event_type for event in events] == ["run.cancelled"]

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "cancelled"
    # A run cancelled before it started never started.
    assert run.started_at is None


async def test_cancel_refuses_without_a_valid_guest_session(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Somebody else's run cannot be stopped by guessing its id."""
    _, project_id = await _seed_owner(fixtures, stack)
    _install_scripted_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)

    async with app_client() as client:
        response = await client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 401, response.text
    assert response.json()["code"] == GUEST_WRONG_CODE

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "queued", "an unauthenticated cancel changed the run"
    assert await _event_rows(read_session, run_id) == []
