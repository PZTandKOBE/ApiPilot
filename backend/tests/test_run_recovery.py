"""Startup recovery, phase one: the five cases that need no executor.

Every test here calls recover_queued_runs() directly -- it has no route, and the point
is the decision it makes, not the HTTP surface.  None of them can reach a target API:
the old queued run is closed without ever being scheduled, the fresh queued run is not
scheduled either (T3 deliberately stays out until the executor-isolation review), and a
running run is never touched.

Isolation: the scratch database is selected in conftest.py before any backend import
and re-checked there; fixtures create their own ids in one session and are read back
through a second one; cleanup deletes exactly those ids.  No other database is read or
written, and no credential is ever touched.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
import pytest

from backend.db.models.result import RunAssertion, RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.services import run_executor
from backend.services.run_executor import (
    EXECUTOR_FAILED,
    RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS,
    recover_queued_runs,
)

pytestmark = pytest.mark.anyio

# Well past the window; named so a future default change cannot turn an orphan fixture
# into a run that gets scheduled.
OLD_ENOUGH_SECONDS = 20_000


def test_default_window_is_what_this_file_assumes() -> None:
    """The fixtures below encode the 300s default; fail loudly if it ever changes."""
    if RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS != 300.0:
        raise RuntimeError(
            "this file assumes a 300s window, the code now says "
            f"{RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS!r}"
        )
    if not OLD_ENOUGH_SECONDS > RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS:
        raise RuntimeError("the orphan fixture is no longer past the window")


def test_unset_window_env_yields_the_default() -> None:
    """A missing setting is the default, not zero and not unlimited."""
    if os.getenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV) is not None:
        raise RuntimeError("this test assumes the window env var is unset")
    if run_executor.recovery_max_age_seconds() != RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS:
        raise RuntimeError("unset env should yield the default window")


# --------------------------------------------------------------------------- #
# T1 -- nothing to recover
# --------------------------------------------------------------------------- #


async def test_t1_no_non_terminal_runs_yields_empty_counts(fixtures, read_session) -> None:
    """A clean database: no queued or running run anywhere, nothing is written."""
    before = await fixtures.count_events(read_session)

    counts = await recover_queued_runs()

    if counts != {}:
        raise AssertionError(f"expected no work at all, got {counts!r}")
    if await fixtures.count_events(read_session) != before:
        raise AssertionError("recovery wrote an event with nothing to recover")


# --------------------------------------------------------------------------- #
# T2 -- an orphaned queued run
# --------------------------------------------------------------------------- #


async def test_t2_old_queued_run_is_closed_with_one_failed_event(
    fixtures, stack, read_session
) -> None:
    """Past the window and never started: failed, settled, exactly one run.failed."""
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    counts = await recover_queued_runs()
    if counts.get("closed") != 1:
        raise AssertionError(f"expected one closed run, got {counts!r}")

    closed = await fixtures.reload(read_session, run_id)

    if closed.status != "failed":
        raise AssertionError(f"run status is {closed.status!r}, expected failed")
    if closed.error_code != EXECUTOR_FAILED:
        raise AssertionError(f"error_code is {closed.error_code!r}")
    if closed.finished_at is None:
        raise AssertionError("finished_at was not set")
    if closed.started_at is not None:
        raise AssertionError("started_at must stay NULL: this run never started")
    # The sentence must name the *configured window*, not the age of this fixture:
    # "queued for more than 300s ... Threshold RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS".
    message = closed.error_message or ""
    if f"{int(RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS)}s" not in message:
        raise AssertionError(f"error_message should name the window: {message!r}")
    if run_executor.RUN_RECOVERY_MAX_AGE_ENV not in message:
        raise AssertionError(f"error_message should name the threshold env: {message!r}")

    events = await fixtures.events(read_session, run_id)
    types = [event.event_type for event in events]
    if types != ["run.failed"]:
        raise AssertionError(f"expected exactly one run.failed, got {types}")
    if events[0].seq != 1:
        raise AssertionError(f"the first event should take seq 1, got {events[0].seq}")

    payload = events[0].payload
    if payload.get("durationMs") != 0:
        raise AssertionError("a run that never started has no duration")
    failure = payload.get("failure") or {}
    if not failure.get("detail"):
        raise AssertionError("the run.failed payload carries no failure detail")
    if failure.get("message") is None:
        raise AssertionError("the run.failed payload carries no failure message")


# --------------------------------------------------------------------------- #
# T4 -- queued, but already has run.started
# --------------------------------------------------------------------------- #


async def test_t4_queued_run_with_a_started_event_is_left_alone(
    fixtures, stack, read_session
) -> None:
    """Inconsistent data is not an orphan: report it and change nothing."""
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.started_event(run_id)
    await fixtures.commit()

    before = await fixtures.reload(read_session, run_id)
    snapshot = (
        before.status,
        before.started_at,
        before.finished_at,
        before.error_code,
        before.error_message,
    )

    counts = await recover_queued_runs()
    if counts.get("inconsistent") != 1:
        raise AssertionError(f"expected one inconsistent run, got {counts!r}")

    after = await fixtures.reload(read_session, run_id)
    if (
        after.status,
        after.started_at,
        after.finished_at,
        after.error_code,
        after.error_message,
    ) != snapshot:
        raise AssertionError("an inconsistent run must not be written to")

    events = await fixtures.events(read_session, run_id)
    if [event.event_type for event in events] != ["run.started"]:
        raise AssertionError("the existing event stream changed")


# --------------------------------------------------------------------------- #
# T8 -- RUN_EXECUTOR_DISABLED
# --------------------------------------------------------------------------- #


async def test_t8_disabled_executor_skips_before_opening_a_session(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """With the executor off, recovery must not even open a session.

    The decoy is a queued run old enough that recovery would certainly close it, so
    "nothing happened" cannot be explained by "there was nothing to do".
    """
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    opened: list[int] = []

    def counting_factory(*args, **kwargs):
        opened.append(1)
        raise AssertionError("recovery opened a session while the executor was disabled")

    monkeypatch.setattr(run_executor, "AsyncSessionLocal", counting_factory)
    monkeypatch.setenv(run_executor.EXECUTOR_DISABLED_ENV, "1")

    try:
        counts = await recover_queued_runs()
    finally:
        monkeypatch.undo()

    if counts != {}:
        raise AssertionError(f"disabled recovery must report nothing, got {counts!r}")
    if opened:
        raise AssertionError("the session factory was called")

    untouched = await fixtures.reload(read_session, run_id)
    if untouched.status != "queued":
        raise AssertionError(f"the decoy run was modified: {untouched.status!r}")
    if untouched.error_code is not None or untouched.finished_at is not None:
        raise AssertionError("the decoy run gained a failure")
    if await fixtures.events(read_session, run_id) != []:
        raise AssertionError("the decoy run gained an event")


# --------------------------------------------------------------------------- #
# T10 -- running
# --------------------------------------------------------------------------- #


async def test_t10_running_run_is_never_touched(fixtures, stack, read_session) -> None:
    """Recovery does not judge liveness -- by design, and on purpose.

    This asserts the deliberate gap, not a finished feature: reliable recovery of a
    running run needs an executor lease or heartbeat that does not exist yet.
    """
    run_id = await fixtures.run(stack, status="running", started_at=datetime.now(timezone.utc))
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    before = await fixtures.reload(read_session, run_id)
    snapshot = (before.status, before.started_at, before.finished_at, before.error_code)

    counts = await recover_queued_runs()
    if counts.get("running") != 1:
        raise AssertionError(f"expected one running run left alone, got {counts!r}")

    after = await fixtures.reload(read_session, run_id)
    if (after.status, after.started_at, after.finished_at, after.error_code) != snapshot:
        raise AssertionError("a running run must not be written to")
    if await fixtures.events(read_session, run_id) != []:
        raise AssertionError("recovery wrote an event for a running run")




def test_disable_flag_did_not_leak_into_the_process() -> None:
    """Guard rail: the T8 flag is gone by the time later tests run."""
    if os.getenv(run_executor.EXECUTOR_DISABLED_ENV):
        raise AssertionError("RUN_EXECUTOR_DISABLED leaked out of its test")

# --------------------------------------------------------------------------- #
# T3 -- inside the window: the run is re-scheduled, not closed
# --------------------------------------------------------------------------- #


async def test_t3_young_queued_run_is_rescheduled_and_finishes_without_http(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """A queued run inside the window is handed to the executor, and runs to the end.

    The run has no scenarios on purpose.  ``_load_tree`` returns an empty list, so
    the executor commits ``run.started``, skips the scenario loop entirely and commits
    ``run.completed``.

    Note what the empty tree does *not* do: the ``httpx.AsyncClient`` at
    ``run_executor.py:1491`` is still constructed, because it is opened before the
    loop, not inside it.  The client is therefore built and left unused -- and that is
    exactly the claim under test: "no request is sent".   The client is replaced here
    by one whose ``send`` raises, so a future refactor that starts a request fails
    this test instead of reaching the network, and the count of constructions is
    asserted so the run cannot pass by never reaching that line at all.
    """
    run_id = await fixtures.run(stack)  # queued, started_at NULL, no run.started
    await fixtures.commit()

    # 1. HTTP may be *constructed* (it is, see the docstring) but never *used*:
    #    every send refuses, so any attempt to reach a target fails this test rather
    #    than the network.
    real_async_client = httpx.AsyncClient
    built: list[object] = []

    class _UnusedClient(real_async_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(self)

        async def send(self, *args, **kwargs):
            raise AssertionError("the executor tried to send an HTTP request")

    monkeypatch.setattr(httpx, "AsyncClient", _UnusedClient)

    # 2. Capture the exact task the scheduler creates, so the wait is on this run
    #    rather than on a sleep or on a count of global tasks.
    real_create_task = asyncio.create_task
    created: list[asyncio.Task] = []

    def capture(coro, **kwargs):
        task = real_create_task(coro, **kwargs)
        created.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", capture)

    if run_id in run_executor._RUNNING_TASKS:
        raise AssertionError("the executor was already running this id before recovery")

    try:
        counts = await recover_queued_runs()

        if counts.get("rescheduled") != 1:
            raise AssertionError(f"expected one rescheduled run, got {counts!r}")
        if "closed" in counts:
            raise AssertionError(f"a run inside the window must not be closed: {counts!r}")

        executor = [t for t in created if t.get_name() == f"run-executor-{run_id}"]
        if len(executor) != 1:
            raise AssertionError(
                f"expected exactly one executor task for this run, got {len(executor)}"
            )

        background = executor[0]
        if background.done():
            raise AssertionError("the executor finished before the wait could observe it")

        # 3. Deterministic wait: this task, no timeout, no polling.
        await background

        if not background.done():
            raise AssertionError("the executor task did not finish")
        if background.cancelled():
            raise AssertionError("the executor task was cancelled instead of finishing")
        if background.exception() is not None:
            raise AssertionError(f"the executor task raised {background.exception()!r}")

        # 4. Final state and event stream, read through a fresh session.
        finished = await fixtures.reload(read_session, run_id)
        if finished.status != "passed":
            raise AssertionError(f"expected the empty run to pass, got {finished.status!r}")
        if finished.started_at is None or finished.finished_at is None:
            raise AssertionError("a finished run carries both timestamps")
        if finished.finished_at < finished.started_at:
            raise AssertionError("finished_at precedes started_at")
        if finished.error_code is not None:
            raise AssertionError(f"a passed run has no error code: {finished.error_code!r}")

        events = await fixtures.events(read_session, run_id)
        types = [event.event_type for event in events]
        if types != ["run.started", "run.completed"]:
            raise AssertionError(f"expected run.started then run.completed, got {types}")
        if [event.seq for event in events] != [1, 2]:
            raise AssertionError(f"seq must be dense from 1, got {[e.seq for e in events]}")
        if "run.failed" in types:
            raise AssertionError("a rescheduled run must not end in run.failed")

        frozen = {
            "run.started",
            "step.started",
            "step.completed",
            "assertion.completed",
            "step.failed",
            "run.completed",
            "run.failed",
            "run.cancelled",
        }
        unknown = [t for t in types if t not in frozen]
        if unknown:
            raise AssertionError(f"events outside the frozen contract: {unknown}")

        # 5. The run row and the stream have to agree with each other.
        if events[0].payload.get("startedAt") is None:
            raise AssertionError("run.started carries no startedAt")
        completed_at = events[1].payload.get("finishedAt")
        if completed_at is None:
            raise AssertionError("run.completed carries no finishedAt")
        if events[1].payload.get("durationMs") is None:
            raise AssertionError("run.completed carries no durationMs")

        # 6. The client was built (so the executor really reached :1491) and used
        #    zero times.
        if len(built) != 1:
            raise AssertionError(f"expected exactly one client for this run, got {len(built)}")

        # 7. The registry the executor maintains must have released this run.
        if run_id in run_executor._RUNNING_TASKS:
            raise AssertionError("the finished run is still registered as running")
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        leaked = [t for t in pending if t.get_name().startswith("run-executor-")]
        if leaked:
            raise AssertionError(f"executor tasks are still pending: {[t.get_name() for t in leaked]}")
    finally:
        # Release the spies before teardown deletes rows, and never leave a task
        # behind for the next test to trip over.
        monkeypatch.undo()
        for task in created:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass


# --------------------------------------------------------------------------- #
# T11 -- an unusable window value must fall back, never become unlimited
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    ["0", "-5", "not-a-number", " "],
    ids=["zero", "negative", "garbage", "spaces"],
)
def test_t11_unusable_window_values_fall_back_to_the_default(raw, monkeypatch) -> None:
    """Every unusable RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS value yields the default.

    The expensive failure would be a zero or negative window: with ``age > window``
    always true, every queued run becomes an orphan and live ones get closed.  The
    implemented guard is ``value <= 0`` for the numeric forms, and a refused
    conversion for the rest.
    """
    monkeypatch.setenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV, raw)

    if os.getenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV) != raw:
        raise AssertionError("the env var this test set is not the one being read")

    actual = run_executor.recovery_max_age_seconds()
    if actual != RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS:
        raise AssertionError(
            f"{run_executor.RUN_RECOVERY_MAX_AGE_ENV}={raw!r} produced {actual!r}, "
            f"expected the default {RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS!r}"
        )


def test_t11_env_var_does_not_leak_between_cases() -> None:
    """Guard rail: the parametrised T11 cases must not leave a window behind."""
    leftover = os.getenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV)
    if leftover is not None:
        raise AssertionError(
            f"{run_executor.RUN_RECOVERY_MAX_AGE_ENV} leaked out of its test: {leftover!r}"
        )
    if run_executor.recovery_max_age_seconds() != RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS:
        raise AssertionError("with the env var absent the default window must apply")


# --------------------------------------------------------------------------- #
# T7 -- calling recovery twice must not close or settle the same run twice
# --------------------------------------------------------------------------- #


async def test_t7_recovery_is_idempotent_for_an_already_closed_run(
    fixtures, stack, read_session
) -> None:
    """The second pass is a no-op: no new event, no second settlement.

    Written as a behaviour test rather than a return-value check.  This run is the
    only non-terminal row in the database, so the first pass must close it; the
    second must find it already terminal -- the candidate query filters on the
    active statuses, so a closed run is not even looked at.
    """
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    first = await recover_queued_runs()
    if first.get("closed") != 1:
        raise AssertionError(f"the first pass should close exactly one run, got {first!r}")
    if "terminal" in first:
        raise AssertionError(f"the first pass saw a terminal run: {first!r}")

    closed = await fixtures.reload(read_session, run_id)
    if closed.status != "failed":
        raise AssertionError(f"after the first pass the run is {closed.status!r}")

    after_first = await fixtures.events(read_session, run_id)
    first_types = [event.event_type for event in after_first]
    first_seqs = [event.seq for event in after_first]
    first_snapshot = (
        closed.status,
        closed.started_at,
        closed.finished_at,
        closed.error_code,
        closed.error_message,
    )
    if first_types != ["run.failed"]:
        raise AssertionError(f"the first pass should leave one run.failed, got {first_types}")
    if first_seqs != [1]:
        raise AssertionError(f"the first pass should leave seq 1, got {first_seqs}")

    second = await recover_queued_runs()
    if second.get("closed"):
        raise AssertionError(f"the second pass closed something again: {second!r}")
    if second.get("rescheduled"):
        raise AssertionError(f"the second pass rescheduled a terminal run: {second!r}")
    if second.get("inconsistent"):
        raise AssertionError(f"the second pass called a closed run inconsistent: {second!r}")
    reported = list(second)
    if reported not in ([], ["terminal"]):
        raise AssertionError(f"the second pass reported unexpected work: {second!r}")

    after_second = await fixtures.reload(read_session, run_id)
    if (
        after_second.status,
        after_second.started_at,
        after_second.finished_at,
        after_second.error_code,
        after_second.error_message,
    ) != first_snapshot:
        raise AssertionError("the second pass changed the run row")

    again = await fixtures.events(read_session, run_id)
    if [event.event_type for event in again] != first_types:
        raise AssertionError("the second pass changed the event stream")
    if [event.seq for event in again] != first_seqs:
        raise AssertionError("the second pass changed the seq sequence")
    if len(again) != 1:
        raise AssertionError(f"expected exactly one event after both passes, got {len(again)}")


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# T11b -- non-finite windows (inf / nan) must be refused, not silently unlimited
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    ["1e999", "inf", "Infinity", "nan", "NaN", "-inf"],
    ids=["overflow", "inf", "Infinity", "nan", "NaN", "-inf"],
)
def test_t11b_non_finite_windows_fall_back_to_the_default(raw, monkeypatch, caplog) -> None:
    """inf and nan are refused like any other unusable window, and they warn.

    Regression for the C6 finding: ``float("1e999")`` is ``inf`` and ``inf <= 0`` is
    false, so before the ``math.isfinite`` guard the value was returned as-is.  An
    infinite window makes ``age > window`` false forever, so recovery silently stops
    closing orphans -- it fails open, which is the expensive direction.
    """
    monkeypatch.setenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV, raw)

    if os.getenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV) != raw:
        raise AssertionError("the env var this test set is not the one being read")

    with caplog.at_level(logging.WARNING, logger=run_executor.__name__):
        actual = run_executor.recovery_max_age_seconds()

    if actual != RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS:
        raise AssertionError(
            f"{run_executor.RUN_RECOVERY_MAX_AGE_ENV}={raw!r} produced {actual!r}, "
            f"expected the default {RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS!r}"
        )
    if not any(record.levelno >= logging.WARNING for record in caplog.records):
        raise AssertionError(f"{raw!r} was refused without a warning")


def test_t11b_finite_positive_windows_are_still_honoured(monkeypatch) -> None:
    """The guard must not swallow the values it is supposed to accept."""
    for raw, expected in (("60", 60.0), ("0.5", 0.5), ("300", 300.0), ("86400", 86400.0)):
        monkeypatch.setenv(run_executor.RUN_RECOVERY_MAX_AGE_ENV, raw)
        actual = run_executor.recovery_max_age_seconds()
        if actual != expected:
            raise AssertionError(f"{raw!r} produced {actual!r}, expected {expected!r}")
        if actual == RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS and raw != "300":
            raise AssertionError(f"{raw!r} silently collapsed into the default")


from sqlalchemy import delete, select, update

from backend.db.models.result import RunAssertion, RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun

# --------------------------------------------------------------------------- #
# T5 -- two concurrent recoveries race for the same orphan
# --------------------------------------------------------------------------- #


async def _seed_child_rows(fixtures, run_id) -> dict:
    """One scenario, one pending step and one pending assertion under this run.

    Returns the ids so the caller can clean up and can read the rows back.  Built
    here rather than in conftest because only these two tests need a run tree, and
    conftest is deliberately left untouched.
    """
    session = fixtures.session
    scenario = RunScenario(
        run_id=run_id,
        scenario_key="c8-scenario",
        name={"text": "T6 scratch scenario"},
        risk_level="low",
        sort_order=0,
        status="pending",
    )
    session.add(scenario)
    await session.flush()

    step = RunStep(
        run_scenario_id=scenario.id,
        step_key="c8-step",
        description={"text": "T6 scratch step"},
        step_type="request",
        method="GET",
        path="/c8",
        sort_order=0,
        status="pending",
    )
    session.add(step)
    await session.flush()

    assertion = RunAssertion(
        run_scenario_id=scenario.id,
        run_step_id=step.id,
        assertion_key="c8-assertion",
        assertion_type="status",
        target="status",
        expected_value=200,
        status="pending",
    )
    session.add(assertion)
    await session.commit()
    return {"scenario": scenario.id, "step": step.id, "assertion": assertion.id}


async def _drop_child_rows(fixtures, *id_sets: dict) -> None:
    """Remove exactly the rows these tests made, children first.

    Takes one or more id sets so a test with several scenarios can clean up in a single
    call; the single-argument form is what T6 already uses.
    """
    session = fixtures.session
    for ids in id_sets:
        await session.execute(
            delete(RunAssertion).where(RunAssertion.id == ids["assertion"])
        )
        await session.execute(delete(RunStep).where(RunStep.id == ids["step"]))
        await session.execute(delete(RunScenario).where(RunScenario.id == ids["scenario"]))
    await session.commit()


async def test_t5_concurrent_recoveries_close_the_orphan_exactly_once(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Two real recoveries meet on one orphan: one claims it, one loses the race.

    The synchronisation point is a barrier installed at the top of
    ``_claim_orphaned_queued``.  Every candidate has already been selected by both
    callers before either reaches it, so the barrier releases both into the same
    conditional UPDATE at the same moment -- the real statement, in the real
    transaction, against the real database.  No sleep, no mocked outcome.
    """
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    barrier = asyncio.Barrier(2)
    claim_attempts: list[int] = []
    real_claim = run_executor._claim_orphaned_queued

    async def claim_after_barrier(session, *, run_id, max_age_seconds):
        claim_attempts.append(1)
        await barrier.wait()
        return await real_claim(session, run_id=run_id, max_age_seconds=max_age_seconds)

    monkeypatch.setattr(run_executor, "_claim_orphaned_queued", claim_after_barrier)

    results = await asyncio.gather(
        recover_queued_runs(),
        recover_queued_runs(),
        return_exceptions=True,
    )
    monkeypatch.undo()

    if len(claim_attempts) != 2:
        raise AssertionError(
            f"both callers must reach the claim: {len(claim_attempts)} attempts, {results!r}"
        )
    for result in results:
        if isinstance(result, BaseException):
            raise AssertionError(f"a recovery call raised {result!r}")

    closed = [r for r in results if r.get("closed") == 1]
    lost = [r for r in results if r.get("lost-race") == 1]
    if len(closed) != 1:
        raise AssertionError(f"exactly one caller must close the run; got {results!r}")
    if len(lost) != 1:
        raise AssertionError(f"exactly one caller must lose the race; got {results!r}")
    # Regression guard for the C9 classification fix: a real race is still a race,
    # and it must not have been relabelled as an error by that fix.
    if any(r.get("error") for r in results):
        raise AssertionError(f"a lost race must not be reported as error; got {results!r}")

    final = await fixtures.reload(read_session, run_id)
    if final.status != "failed":
        raise AssertionError(f"the run should end failed, not {final.status!r}")
    if final.error_code != EXECUTOR_FAILED:
        raise AssertionError(f"unexpected error_code {final.error_code!r}")

    events = await fixtures.events(read_session, run_id)
    if [event.event_type for event in events] != ["run.failed"]:
        raise AssertionError(f"expected one run.failed, got {[e.event_type for e in events]}")
    if [event.seq for event in events] != [1]:
        raise AssertionError(f"seq must not repeat or skip: {[e.seq for e in events]}")

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    leaked = [t for t in pending if t.get_name().startswith("run-executor-")]
    if leaked:
        raise AssertionError(f"executor tasks are still pending: {[t.get_name() for t in leaked]}")


# --------------------------------------------------------------------------- #
# T6 -- a failure while writing the event must roll the whole repair back
# --------------------------------------------------------------------------- #


async def _snapshot_tree(read_session, run_id, ids) -> dict:
    """Row states that the recovery transaction would change if it committed."""
    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    scenario = (
        await read_session.execute(
            select(RunScenario).where(RunScenario.id == ids["scenario"])
        )
    ).scalar_one()
    step = (
        await read_session.execute(select(RunStep).where(RunStep.id == ids["step"]))
    ).scalar_one()
    assertion = (
        await read_session.execute(
            select(RunAssertion).where(RunAssertion.id == ids["assertion"])
        )
    ).scalar_one()
    return {
        "run": (run.status, run.started_at, run.finished_at, run.error_code, run.error_message),
        "scenario": scenario.status,
        "step": step.status,
        "assertion": assertion.status,
    }


async def test_t6_event_write_failure_rolls_back_the_whole_repair(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The claim, the settlement and the event are one unit, or none of them is.

    ``append_run_event`` is replaced *inside run_executor* -- the reference the
    recovery path actually calls -- with a stub that fails.  It is installed after
    the claim has already updated the run and after ``_settle_unfinished`` has
    already marked the pending child rows, so the failure lands in the middle of a
    transaction that has done real work.  The stub records that the settlement had
    already run, which is what proves the failure happened at the intended point
    rather than before the transaction started.
    """
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    ids = await _seed_child_rows(fixtures, run_id)
    try:
        before = await _snapshot_tree(read_session, run_id, ids)
        if before["run"][0] != "queued":
            raise AssertionError(f"the fixture must start queued, got {before['run'][0]!r}")

        settle_calls: list[int] = []
        settle_rowcounts: list[int] = []
        real_settle = run_executor._settle_unfinished

        async def settle_spy(session, target_run_id) -> None:
            result_step = await session.execute(
                update(RunStep)
                .where(RunStep.run_scenario_id == ids["scenario"], RunStep.status == "pending")
                .values(status="skipped")
            )
            settle_calls.append(1)
            settle_rowcounts.append(int(result_step.rowcount or 0))
            await real_settle(session, target_run_id)

        async def failing_append(session, *, run_id, event_type, payload):
            if not settle_calls:
                raise AssertionError(
                    "the event writer was reached before the settlement ran"
                )
            raise RuntimeError("C8 injected failure: event write failed")

        monkeypatch.setattr(run_executor, "_settle_unfinished", settle_spy)
        monkeypatch.setattr(run_executor, "append_run_event", failing_append)

        counts = await recover_queued_runs()
        monkeypatch.undo()

        if not settle_calls:
            raise AssertionError("the settlement was never reached")
        if not settle_rowcounts or settle_rowcounts[0] != 1:
            raise AssertionError(
                f"the settlement did not touch a row (rowcounts={settle_rowcounts!r})"
            )
        if counts.get("closed"):
            raise AssertionError(f"a failed close must not report closed: {counts!r}")
        # C8 found that this path used to report "lost-race" -- the same word a genuine
        # lost race produces -- because _close_orphaned_queued swallowed the exception
        # and returned False.  C9 gave it a third outcome (None) so a rolled-back
        # transaction is counted as an error instead of as somebody else winning.
        if counts != {"error": 1}:
            raise AssertionError(
                f"a rolled-back repair must be counted as error, not lost-race: {counts!r}"
            )
        if counts.get("lost-race"):
            raise AssertionError(
                f"a real transaction failure must never be reported as lost-race: {counts!r}"
            )

        events = await fixtures.events(read_session, run_id)
        if events:
            raise AssertionError(f"a rolled-back repair must leave no event: {events!r}")

        after = await _snapshot_tree(read_session, run_id, ids)
        if after != before:
            raise AssertionError(
                "the transaction was not rolled back: "
                f"before={before!r} after={after!r}"
            )

        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        leaked = [t for t in pending if t.get_name().startswith("run-executor-")]
        if leaked:
            raise AssertionError(
                f"executor tasks are still pending: {[t.get_name() for t in leaked]}"
            )
    finally:
        monkeypatch.undo()
        await _drop_child_rows(fixtures, ids)


# --------------------------------------------------------------------------- #
# T12 -- resolved assertions keep their verdict; only unfinished work is settled
# --------------------------------------------------------------------------- #


async def _seed_mixed_tree(fixtures, run_id, resolved_status: str) -> dict:
    """Two scenarios: one still pending, one holding an already-judged assertion.

    ``_settle_unfinished`` skips assertions whose status is passed or failed and settles
    everything else, so the second scenario is where a careless broad update would show
    up.  ``resolved_status`` is the verdict that must survive the repair.
    """
    session = fixtures.session

    pending = RunScenario(
        run_id=run_id,
        scenario_key="c10-pending",
        name={"text": "still pending"},
        risk_level="low",
        sort_order=0,
        status="pending",
    )
    session.add(pending)
    await session.flush()

    pending_step = RunStep(
        run_scenario_id=pending.id,
        step_key="c10-pending-step",
        description={"text": "never ran"},
        step_type="request",
        method="GET",
        path="/c10",
        sort_order=0,
        status="pending",
    )
    session.add(pending_step)
    await session.flush()

    pending_assertion = RunAssertion(
        run_scenario_id=pending.id,
        run_step_id=pending_step.id,
        assertion_key="c10-pending-assertion",
        assertion_type="status",
        target="status",
        expected_value=200,
        status="pending",
    )
    session.add(pending_assertion)

    judged = RunScenario(
        run_id=run_id,
        scenario_key="c10-judged",
        name={"text": "already judged"},
        risk_level="low",
        sort_order=1,
        status="passed",
    )
    session.add(judged)
    await session.flush()

    judged_step = RunStep(
        run_scenario_id=judged.id,
        step_key="c10-judged-step",
        description={"text": "ran to completion"},
        step_type="request",
        method="GET",
        path="/c10/judged",
        sort_order=0,
        status="passed",
    )
    session.add(judged_step)
    await session.flush()

    judged_assertion = RunAssertion(
        run_scenario_id=judged.id,
        run_step_id=judged_step.id,
        assertion_key="c10-judged-assertion",
        assertion_type="status",
        target="status",
        expected_value=200,
        actual_value=200,
        status=resolved_status,
    )
    session.add(judged_assertion)
    await session.commit()

    return {
        "pending": {"scenario": pending.id, "step": pending_step.id, "assertion": pending_assertion.id},
        "judged": {"scenario": judged.id, "step": judged_step.id, "assertion": judged_assertion.id},
    }


async def _read_states(read_session, ids: dict) -> dict:
    """The three statuses the settlement could touch, plus the verdict row itself."""
    scenario = (
        await read_session.execute(
            select(RunScenario).where(RunScenario.id == ids["scenario"])
        )
    ).scalar_one()
    step = (
        await read_session.execute(select(RunStep).where(RunStep.id == ids["step"]))
    ).scalar_one()
    assertion = (
        await read_session.execute(
            select(RunAssertion).where(RunAssertion.id == ids["assertion"])
        )
    ).scalar_one()
    return {
        "scenario": scenario.status,
        "step": step.status,
        "assertion": assertion.status,
        "assertion_expected": assertion.expected_value,
        "assertion_actual": assertion.actual_value,
        "assertion_type": assertion.assertion_type,
        "assertion_target": assertion.target,
        "assertion_step_id": assertion.run_step_id,
    }


@pytest.mark.parametrize("resolved_status", ["passed", "failed"], ids=["passed", "failed"])
async def test_t12_resolved_assertions_keep_their_verdict(
    fixtures, stack, read_session, resolved_status
) -> None:
    """A repair settles what never ran and leaves a judged assertion exactly as it was.

    The real recovery path runs here -- claim, settlement, event, commit -- with no
    monkeypatching at all.  The interesting row is the one whose verdict is already in:
    ``_settle_unfinished`` filters it out with ``status NOT IN (passed, failed)``, and
    this test is what keeps that filter honest.
    """
    run_id = await fixtures.run(stack)
    await fixtures.backdate_run(run_id, OLD_ENOUGH_SECONDS)
    await fixtures.commit()

    ids = await _seed_mixed_tree(fixtures, run_id, resolved_status)
    try:
        before_pending = await _read_states(read_session, ids["pending"])
        before_judged = await _read_states(read_session, ids["judged"])
        if before_judged["assertion"] != resolved_status:
            raise AssertionError(f"fixture did not store the verdict: {before_judged!r}")
        if before_pending["assertion"] != "pending":
            raise AssertionError(f"fixture should start pending: {before_pending!r}")

        counts = await recover_queued_runs()
        if counts.get("closed") != 1:
            raise AssertionError(f"the orphan should have been closed: {counts!r}")

        finished = await fixtures.reload(read_session, run_id)
        if finished.status != "failed":
            raise AssertionError(f"the run should end failed, got {finished.status!r}")
        if finished.error_code != EXECUTOR_FAILED:
            raise AssertionError(f"unexpected error_code {finished.error_code!r}")

        after_pending = await _read_states(read_session, ids["pending"])
        if after_pending["assertion"] != "skipped":
            raise AssertionError(
                f"an unfinished assertion must be settled to skipped: {after_pending!r}"
            )
        if after_pending["step"] != "skipped":
            raise AssertionError(f"an unfinished step must be settled: {after_pending!r}")
        if after_pending["scenario"] != "skipped":
            raise AssertionError(f"a pending scenario must be settled: {after_pending!r}")

        after_judged = await _read_states(read_session, ids["judged"])
        if after_judged["assertion"] != resolved_status:
            raise AssertionError(
                f"a resolved assertion was rewritten: expected {resolved_status!r}, "
                f"found {after_judged['assertion']!r}"
            )
        for field in (
            "assertion_expected",
            "assertion_actual",
            "assertion_type",
            "assertion_target",
            "assertion_step_id",
        ):
            if after_judged[field] != before_judged[field]:
                raise AssertionError(
                    f"the judged assertion had {field} rewritten: "
                    f"{before_judged[field]!r} -> {after_judged[field]!r}"
                )
        if after_judged["scenario"] != before_judged["scenario"]:
            raise AssertionError("a passed scenario must not be settled")
        if after_judged["step"] != before_judged["step"]:
            raise AssertionError("a passed step must not be settled")

        events = await fixtures.events(read_session, run_id)
        types = [event.event_type for event in events]
        if types != ["run.failed"]:
            raise AssertionError(f"expected exactly one run.failed, got {types}")
        if [event.seq for event in events] != [1]:
            raise AssertionError(f"seq must be dense: {[e.seq for e in events]}")
    finally:
        await _drop_child_rows(fixtures, ids["pending"], ids["judged"])
