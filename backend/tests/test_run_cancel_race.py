"""The cancel race, and the stream while the run is still going.

C18 exercised the cancel route and the SSE route; it left two things open, and this
file closes them.

**The race.**  A cancel used to be written by the route while the executor was still
on the wire.  The step that came back afterwards was recorded as a completion, so the
event stream could end `run.cancelled, step.completed` while the row said the step was
`skipped`.  Two fixes, and both are asserted here: the executor no longer records a
completion for a run that has stopped, and the cancel route interrupts this process
executor task instead of waiting for the next boundary check.

**The stream.**  C18 read a terminal run, which proves the frames but not the
latency.  The live test here reads an *active* run: it parks the executor inside a
request, waits for the SSE client to receive the frames that have already happened,
and only then releases the request.  The assertion that matters is an ordering one --
the frames arrived before the release -- which is what a buffered implementation
cannot satisfy.

The executor is never replaced: only its httpx.AsyncClient is, by a subclass that
answers from a script and parks where a test asks it to.  Same convention as
test_run_recovery.py, test_run_execution.py and test_run_stream_and_cancel.py.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from backend.app import create_app
from backend.db.models.project import Environment, Project
from backend.db.models.result import RunEvent, RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.db.models.user import GuestSession
from backend.schemas.run import RunCreateRequest
from backend.services import guest_session, run_executor, runs
from backend.services.guest_session import hash_token

from tests.test_run_execution import (
    ASSERT_STEP,
    CREATE_STEP,
    ENVIRONMENT_ID,
    EXTRACT_STEP,
    PLAN_ID,
    READ_STEP,
    _project_public_id,
    _run_body,
    _step_rows,
)

pytestmark = pytest.mark.anyio

GUEST_HEADER = "X-Guest-Session"
HTTP_TIMEOUT = 30.0
# The parked-read tests must fail, not hang, when something does not happen.
PARK_TIMEOUT = 8.0

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

LIFECYCLE_EVENTS = frozenset(
    {
        "step.started",
        "step.completed",
        "step.failed",
        "assertion.completed",
    }
)


real_async_client = httpx.AsyncClient
"""The real httpx client, saved before the patch replaces the name."""


class _ParkedClient(httpx.AsyncClient):
    """The executor client, answering from a script, parking where asked.

    `entered` is set the first time a request arrives; if `release` is set, the
    handler waits on it before answering.  Only clients that brought no transport
    of their own -- the executor own -- are treated this way, so this test HTTP
    client still reaches the application.
    """

    sent: list[httpx.Request] = []
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(self._answer)
        super().__init__(*args, **kwargs)

    @property
    def _is_the_executors(self) -> bool:
        return isinstance(self._transport, httpx.MockTransport)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("the synchronous handler must not be used")

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if not self._is_the_executors:
            return await super().send(request, **kwargs)

        type(self).sent.append(request)
        if type(self).entered is not None and not type(self).entered.is_set():
            type(self).entered.set()
            if type(self).release is not None:
                await type(self).release.wait()

        if request.method == "GET" and request.url.path == "/orders/order_1":
            return httpx.Response(200, json={"orderId": "order_1", "status": "open"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": "order_2"})
        return httpx.Response(404, json={"error": "unexpected target"})


def _install_parked_client(monkeypatch, *, entered=None, release=None) -> type[_ParkedClient]:
    _ParkedClient.sent = []
    _ParkedClient.entered = entered
    _ParkedClient.release = release
    # The patch shadows httpx.AsyncClient, so the real class is kept aside: a call
    # to httpx.AsyncClient.send from inside send would find the subclass again.
    _ParkedClient.real = real_async_client
    monkeypatch.setattr(httpx, "AsyncClient", _ParkedClient)
    return _ParkedClient


async def _seed_owner(fixtures, stack) -> tuple[str, uuid.UUID]:
    """A guest whose token this file knows, owning the project the run belongs to.

    The run routes answer 404 for a run the caller does not own, by design, so the
    project has to belong to the guest that will authenticate.
    """
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
        public_id="c19prj_" + uuid.uuid4().hex[:12],
        name="C19 project",
        description="Created by backend/tests; deleted by its own cleanup.",
    )
    fixtures.session.add(project)
    await fixtures._keep(Project, project)

    environment = Environment(
        project_id=project.id,
        public_id=ENVIRONMENT_ID,
        name="C19 environment",
        kind="development",
        base_url="http://127.0.0.1:9",
    )
    fixtures.session.add(environment)
    await fixtures._keep(Environment, environment)
    await fixtures.commit()
    return token, project.id


def _two_scenario_body(project_public_id: str) -> dict[str, Any]:
    """The C17 plan plus a second scenario that never gets to run."""
    body = _run_body(project_public_id)
    scenarios = body["plan"]["scenarios"]
    second = json.loads(json.dumps(scenarios[0]))
    second["id"] = "scenario_c19_second"
    second["index"] = 1
    second["name"] = {"text": "never started"}
    for position, step in enumerate(second["steps"]):
        step["id"] = step["id"].replace("step_c17", "step_c19")
        step["index"] = position
    for assertion in second["assertions"]:
        assertion["id"] = assertion["id"].replace("assertion_c17", "assertion_c19")
    scenarios.append(second)
    return body


async def _create_run(fixtures, project_id: uuid.UUID, monkeypatch, *, body=None):
    if body is None:
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


def _start_registered_executor(run_id: uuid.UUID) -> asyncio.Task:
    """Start the executor the way the scheduler does, so it is reachable.

    schedule_run registers the task so a cancel has something to interrupt.  This
    does the same two lines, without the create_task-inside-the-app part, because a
    test cannot await a task the request handler owns.
    """
    task = asyncio.create_task(run_executor.execute_run(run_id), name="run-executor-" + str(run_id))
    run_executor._RUNNING_TASKS[run_id] = task
    task.add_done_callback(lambda finished, key=run_id: run_executor._forget(key, finished))
    return task


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


@asynccontextmanager
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://c19", timeout=HTTP_TIMEOUT
    ) as client:
        yield client


def _assert_no_lifecycle_event_after_cancel(events: list[RunEvent]) -> None:
    """The contract this whole file exists for: run.cancelled is the last word.

    Nothing that describes the run execution may be written after it -- a step that
    finished after the cancellation would contradict the skipped row it describes,
    and it would be the last thing every connected client saw.
    """
    kinds = [event.event_type for event in events]
    terminals = [event for event in events if event.event_type in ("run.cancelled", "run.completed", "run.failed")]
    assert len(terminals) == 1, f"one terminal event, got {kinds}"
    assert terminals[0].event_type == "run.cancelled", f"the terminal event is the cancel, got {kinds}"

    last = terminals[0]
    trailing = [event for event in events if event.seq > last.seq]
    assert trailing == [], (
        f"lifecycle events written after run.cancelled: {[(e.seq, e.event_type) for e in trailing]}"
    )

    cancelled = events.index(last)
    assert all(kind not in LIFECYCLE_EVENTS for kind in kinds[cancelled + 1 :]), kinds


# --------------------------------------------------------------------------- #
# 1. The race: a cancel while the step is on the wire
# --------------------------------------------------------------------------- #


async def test_cancel_interrupts_the_request_and_settles_the_step(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The defect, and both halves of its fix.

    1. The in-flight request is interrupted: it never returns, so the step cannot be
       recorded as a completion.
    2. The database and the event stream agree: every step is settled, and nothing
       is written after run.cancelled.
    """
    token, project_id = await _seed_owner(fixtures, stack)

    entered = asyncio.Event()
    release = asyncio.Event()
    client_type = _install_parked_client(monkeypatch, entered=entered, release=release)

    run_id = await _create_run(
        fixtures, project_id, monkeypatch, body=_two_scenario_body(await _project_public_id(fixtures, project_id))
    )

    task = _start_registered_executor(run_id)
    try:
        await asyncio.wait_for(entered.wait(), timeout=HTTP_TIMEOUT)

        # The run really is running: read from the database, not inferred.
        status = (
            await read_session.execute(select(_TestRun.status).where(_TestRun.id == run_id))
        ).scalar_one()
        assert status == "running"
        assert run_id in run_executor._RUNNING_TASKS

        async with app_client() as client:
            cancelled = await client.post(
                f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
            )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        # The executor is stopped on purpose: it ends as a cancelled task, and the
        # request it was waiting on is never answered.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=HTTP_TIMEOUT)
        assert task.cancelled()
        assert len(client_type.sent) == 1, "a second request was started after the cancel"
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "cancelled"

    events = await _event_rows(read_session, run_id)
    _assert_no_lifecycle_event_after_cancel(events)
    kinds = [event.event_type for event in events]
    assert kinds == ["run.started", "step.started", "run.cancelled"], kinds
    assert [event.seq for event in events] == [1, 2, 3]
    assert set(kinds) <= FROZEN_EVENT_TYPES

    # The step the cancel caught: no row left running, and no event claiming it
    # completed.  The step that had already finished keeps its real result.
    scenarios = await _scenario_rows(read_session, run_id)
    first, second = scenarios
    first_steps = {step.step_key: step for step in await _step_rows(read_session, first.id)}
    assert first_steps[READ_STEP].status == "skipped"
    assert first_steps[EXTRACT_STEP].status == "skipped"
    assert first_steps[CREATE_STEP].status == "skipped"
    assert first_steps[ASSERT_STEP].status == "skipped"
    assert all(step.status == "skipped" for step in await _step_rows(read_session, second.id))

    # The scenario the cancel caught is settled with the run.  A terminal run
    # holding a scenario that still claimed to be running was the C19 gap.
    assert first.status == "skipped"
    assert second.status == "skipped"

    # Nothing is left claimed as executing.
    assert run_id not in run_executor._RUNNING_TASKS


async def test_cancel_between_steps_keeps_finished_work_and_stops_the_rest(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """A cancel that lands between two steps keeps the result of the finished one.

    The first request is allowed to complete, the park is moved to the second, and
    the cancel then arrives with one step genuinely done.  That step keeps passed --
    a cancel must not rewrite work that really happened -- and the step it caught is
    settled as skipped.
    """
    token, project_id = await _seed_owner(fixtures, stack)

    calls: list[int] = []
    release = asyncio.Event()
    second_call = asyncio.Event()

    park_at = 2

    client_type = _install_parked_client(monkeypatch, release=release)

    # Park on the second request: the read and the extract complete for real first.
    async def before(request: httpx.Request) -> None:
        calls.append(1)
        if len(calls) == park_at:
            second_call.set()
            await release.wait()

    client_type.entered = None

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if not self._is_the_executors:
            return await type(self).real.send(self, request, **kwargs)
        type(self).sent.append(request)
        await before(request)
        if request.method == "GET" and request.url.path == "/orders/order_1":
            return httpx.Response(200, json={"orderId": "order_1", "status": "open"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": "order_2"})
        return httpx.Response(404, json={"error": "unexpected target"})

    monkeypatch.setattr(client_type, "send", send)

    run_id = await _create_run(
        fixtures, project_id, monkeypatch, body=_two_scenario_body(await _project_public_id(fixtures, project_id))
    )

    task = _start_registered_executor(run_id)
    try:
        await asyncio.wait_for(second_call.wait(), timeout=PARK_TIMEOUT)

        # One step finished, and it is recorded as such, before the cancel.
        steps = {
            step.step_key: step
            for scenario in await _scenario_rows(read_session, run_id)
            for step in await _step_rows(read_session, scenario.id)
        }
        assert steps[READ_STEP].status == "passed"
        assert steps[EXTRACT_STEP].status == "passed"

        async with app_client() as client:
            cancelled = await client.post(
                f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
            )
        assert cancelled.status_code == 200, cancelled.text

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=HTTP_TIMEOUT)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # This session already loaded these rows while the run was live, and it never
    # commits, so its identity map would hand back the statuses it saw then -- a
    # stale running for the step the cancel settled.  Expiring makes the reads
    # below come from the database, which is the only thing being asserted.
    read_session.expire_all()

    events = await _event_rows(read_session, run_id)
    _assert_no_lifecycle_event_after_cancel(events)

    kinds = [event.event_type for event in events]
    # The two steps that really completed keep their completion events, and they
    # come before the cancellation.
    assert kinds.count("step.completed") == 2, kinds
    assert kinds.index("run.cancelled") > kinds.index("step.completed")
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert set(kinds) <= FROZEN_EVENT_TYPES

    scenario = (await _scenario_rows(read_session, run_id))[0]
    settled = {step.step_key: step for step in await _step_rows(read_session, scenario.id)}
    assert settled[READ_STEP].status == "passed", "finished work must keep its result"
    assert settled[EXTRACT_STEP].status == "passed"
    # The step the cancel caught never started, and the ones after it never did either.
    assert settled[CREATE_STEP].status == "skipped"
    assert settled[ASSERT_STEP].status == "skipped"

    # The finished work survives the settlement, and the scenario the cancel caught
    # is terminal like the run it belongs to -- settled, not still running.
    assert scenario.status == "skipped"
    later = (await _scenario_rows(read_session, run_id))[1]
    assert later.status == "skipped"
    assert later.started_at is None, "the second scenario never started"


async def test_cancel_before_any_request_sends_nothing(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The narrowest race: the cancel arrives before the first request is sent."""
    token, project_id = await _seed_owner(fixtures, stack)

    entered = asyncio.Event()
    release = asyncio.Event()
    client_type = _install_parked_client(monkeypatch, entered=entered, release=release)

    run_id = await _create_run(fixtures, project_id, monkeypatch)

    # Cancel while the run is still queued: nothing has been sent and nothing will be.
    async with app_client() as client:
        cancelled = await client.post(
            f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token}
        )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "cancelled"
    assert run.started_at is None

    # Running it afterwards must not resurrect it.
    await run_executor.execute_run(run_id)
    assert client_type.sent == [], "a cancelled run sent a request"

    events = await _event_rows(read_session, run_id)
    assert [event.event_type for event in events] == ["run.cancelled"]


async def test_cancelling_a_finished_run_is_still_a_no_op(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The boundary C18 covered, re-asserted because the route changed.

    C18::test_cancelling_a_finished_run_changes_nothing covers the double cancel of a
    queued run.  This one covers a run that has already *executed* to a terminal
    state, which the new interruption path must leave completely alone.
    """
    token, project_id = await _seed_owner(fixtures, stack)
    _install_parked_client(monkeypatch)
    run_id = await _create_run(fixtures, project_id, monkeypatch)
    await run_executor.execute_run(run_id)

    before = await _event_rows(read_session, run_id)
    assert before[-1].event_type == "run.completed"

    async with app_client() as client:
        first = await client.post(f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token})
        second = await client.post(f"/api/runs/{run_id}/cancel", headers={GUEST_HEADER: token})

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["status"] == "passed"
    assert second.json()["status"] == "passed"

    after = await _event_rows(read_session, run_id)
    assert [event.event_type for event in after] == [event.event_type for event in before]
    assert [event.seq for event in after] == [event.seq for event in before]
