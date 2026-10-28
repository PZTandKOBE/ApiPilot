"""The deterministic run loop: an approved plan becomes a snapshot, and runs.

A run is created from a submitted plan, fanned out into run_* rows, executed by the
product own executor and recorded as events.  This file walks that chain and keeps
the four claims apart, because each can hold while the next one fails:

1. **The run was created** -- a test_runs row exists in queued.
2. **The snapshot is correct** -- run_scenarios / run_steps / run_assertions mirror
   the plan, including the method and path the executor will call.
3. **The executor actually ran** -- the real _execute walked the scenarios and sent
   the requests it was told to send.
4. **The events are the run real history** -- written by append_run_event, seq
   dense from 1, and readable again through the module the events route calls.

Nothing here talks to a real API.  The executor is not replaced: it constructs its
own httpx.AsyncClient at run_executor.py:1492, and this file swaps that class for a
subclass carrying httpx.MockTransport.  Every other line of the executor -- status
transitions, variable resolution, assertion evaluation, evidence, events, settlement
-- is the production one.  That is the same convention test_run_recovery.py uses.

Approval is exercised through the service own gate, runs._check_approval: the plan
submitted here carries status="approved" because that is what the current contract
requires a client to state.  See the C16 record for why that is a client-side
authority and not a server-side one.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from backend.db.models.agent import TestAssertion as _TestAssertion
from backend.db.models.agent import TestPlan as _TestPlan
from backend.db.models.agent import TestScenario as _TestScenario
from backend.db.models.agent import TestStep as _TestStep
from backend.db.models.project import Environment
from backend.db.models.result import RunAssertion, RunEvent, RunScenario, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.schemas.run import RunCreateRequest
from backend.services import agent as agent_service
from backend.services import run_executor, runs
from backend.services.agent import derive_spec_identity, probe_document

pytestmark = pytest.mark.anyio

ORDERS_DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/orders/{orderId}": {
            "get": {
                "summary": "Read one order",
                "responses": {
                    "200": {
                        "description": "the order",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "status"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/orders": {
            "post": {
                "summary": "Create an order",
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id"],
                                    "properties": {"id": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
    },
}

# The slug is derived from the document the same way the service derives it -- the
# identity is a function of the document, not a constant, and guessing it produces a
# specId the service refuses.  Deriving it here means this file cannot drift.
ORDERS_TEXT = json.dumps(ORDERS_DOCUMENT)
ORDERS_IDENTITY = derive_spec_identity(
    spec_document=ORDERS_TEXT, spec_id="spec_probe", facts=probe_document(ORDERS_TEXT)
)
ORDERS_SLUG = ORDERS_IDENTITY.slug
ORDERS_SPEC_ID = "spec_" + ORDERS_SLUG
PLAN_ID = "plan_c17_orders"
ENVIRONMENT_ID = "env_c17_orders"
BASE_URL = "http://127.0.0.1:9"

# The scenario as designed.  Three steps, in this order, so ordering is observable:
# a read, an extract that names the variable a later step consumes, and a create.
SCENARIO_KEY = "scenario_c17_orders"
READ_STEP = "step_c17_read"
EXTRACT_STEP = "step_c17_extract"
CREATE_STEP = "step_c17_create"
ASSERT_STEP = "step_c17_assert"
ASSERTION_KEY = "assertion_c17_status"

READ_PATH = "/orders/order_1"
CREATE_PATH = "/orders?for={{orderId}}"


def _plan_payload(status: str = "approved") -> dict[str, Any]:
    """A plan that satisfies the frozen PlanPayload contract, field for field."""
    return {
        "id": PLAN_ID,
        "projectId": "PLACEHOLDER",
        "specId": ORDERS_SPEC_ID,
        "name": {"text": "C17 orders plan"},
        "goal": {"text": "read an order and create one"},
        "riskLevel": "low",
        "status": status,
        "source": "generated",
        "generatedAt": "2026-10-16T00:00:00Z",
        "approvedAt": "2026-10-16T00:00:01Z" if status == "approved" else None,
        "scenarios": [
            {
                "id": SCENARIO_KEY,
                "index": 0,
                "name": {"text": "read then create"},
                "description": {"text": "two requests, one extraction"},
                "expected": {"text": "both calls succeed"},
                "riskLevel": "low",
                "steps": [
                    {
                        "id": READ_STEP,
                        "index": 0,
                        "kind": "request",
                        "description": {"text": "read order 1"},
                        "endpointId": None,
                        "method": "GET",
                        "path": READ_PATH,
                        "produces": None,
                        "consumes": [],
                    },
                    {
                        "id": EXTRACT_STEP,
                        "index": 1,
                        "kind": "extract",
                        "description": {"text": "keep the order id"},
                        "endpointId": None,
                        "method": None,
                        "path": None,
                        "produces": "orderId",
                        "consumes": [],
                    },
                    {
                        "id": CREATE_STEP,
                        "index": 2,
                        "kind": "request",
                        "description": {"text": "create an order for that id"},
                        "endpointId": None,
                        "method": "POST",
                        "path": CREATE_PATH,
                        "produces": None,
                        "consumes": ["orderId"],
                    },
                    {
                        "id": ASSERT_STEP,
                        "index": 3,
                        "kind": "assert",
                        "description": {"text": "check the create"},
                        "endpointId": None,
                        "method": None,
                        "path": None,
                        "produces": None,
                        "consumes": [],
                    },
                ],
                "assertions": [
                    {
                        "id": ASSERTION_KEY,
                        "kind": "status",
                        "target": "status",
                        "expected": "201",
                        "description": {"text": "the create answers 201"},
                    }
                ],
            }
        ],
    }


def _run_body(
    project_public_id: str,
    *,
    status: str = "approved",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = plan if plan is not None else _plan_payload(status)
    plan["projectId"] = project_public_id
    return {
        "projectId": project_public_id,
        "planId": PLAN_ID,
        "plan": plan,
        "specId": ORDERS_SPEC_ID,
        "specDocument": ORDERS_TEXT,
        "environmentId": ENVIRONMENT_ID,
        "variables": {},
        "baseUrl": BASE_URL,
    }


async def _seed_environment(fixtures, project_id: uuid.UUID) -> uuid.UUID:
    """The run names an environment, and the service looks it up inside the project."""
    row = Environment(
        project_id=project_id,
        public_id=ENVIRONMENT_ID,
        name="C17 environment",
        kind="development",
        base_url=BASE_URL,
    )
    fixtures.session.add(row)
    return await fixtures._keep(Environment, row)


async def _project_public_id(fixtures, project_id: uuid.UUID) -> str:
    from backend.db.models.project import Project

    return (
        await fixtures.session.execute(
            select(Project.public_id).where(Project.id == project_id)
        )
    ).scalar_one()


class _RecordingClient(httpx.AsyncClient):
    """The real client, answering from a script and remembering what it was asked.

    The executor builds this class itself; replacing the class is the whole
    intervention.  Every request the executor makes is appended to sent in the
    order it was made, which is what makes execution order assertable.
    """

    sent: list[httpx.Request] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.pop("transport", None)
        super().__init__(*args, transport=httpx.MockTransport(self._answer), **kwargs)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        type(self).sent.append(request)
        if request.method == "GET" and request.url.path == "/orders/order_1":
            return httpx.Response(200, json={"orderId": "order_1", "status": "open"})
        if request.method == "GET" and request.url.path == "/posts":
            return httpx.Response(200, json=[{"id": 101, "userId": 8, "title": "example"}])
        if request.method == "GET" and request.url.path == "/posts/101":
            return httpx.Response(200, json={"id": 101, "userId": 8, "title": "example"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": "order_2"})
        return httpx.Response(404, json={"error": "unexpected target"})


def _install_client(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingClient]:
    """Point the executor at the recording client for this test only."""
    _RecordingClient.sent = []
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    return _RecordingClient


async def _create_run(
    fixtures,
    stack,
    monkeypatch,
    *,
    status: str = "approved",
    plan: dict[str, Any] | None = None,
):
    """Create a run through the service, without letting it execute yet.

    runs.create_run schedules the executor as its last act.  Scheduling is
    suppressed so the snapshot can be inspected in its queued state, which is the
    state the create path promises to return in.
    """
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()

    public_id = await _project_public_id(fixtures, stack["project"])
    payload = RunCreateRequest.model_validate(
        _run_body(public_id, status=status, plan=plan)
    )

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    response = await runs.create_run(
        fixtures.session, project_id=public_id, payload=payload
    )
    return uuid.UUID(str(response.id))


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


async def _step_rows(session, scenario_id: uuid.UUID) -> list[RunStep]:
    return list(
        (
            await session.execute(
                select(RunStep)
                .where(RunStep.run_scenario_id == scenario_id)
                .order_by(RunStep.sort_order, RunStep.step_key)
            )
        ).scalars()
    )


async def _event_rows(session, run_id: uuid.UUID) -> list[RunEvent]:
    return list(
        (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- #
# 1. The run is created, and the snapshot mirrors the plan
# --------------------------------------------------------------------------- #


async def test_run_creation_snapshots_the_plan_tree(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """Create a run and read the rows back: counts, order, keys, method/path."""
    run_id = await _create_run(fixtures, stack, monkeypatch)

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "queued", "a freshly created run waits to be executed"
    assert run.started_at is None
    assert run.base_url == BASE_URL
    assert run.plan_name["text"] == "C17 orders plan"

    scenarios = await _scenario_rows(read_session, run_id)
    assert len(scenarios) == 1
    scenario = scenarios[0]
    assert scenario.scenario_key == SCENARIO_KEY
    assert scenario.status == "pending"
    assert scenario.sort_order == 0

    steps = await _step_rows(read_session, scenario.id)
    assert [step.step_key for step in steps] == [
        READ_STEP,
        EXTRACT_STEP,
        CREATE_STEP,
        ASSERT_STEP,
    ], "the snapshot must keep the step order the plan declared"
    assert [step.sort_order for step in steps] == [0, 1, 2, 3]
    assert [step.step_type for step in steps] == ["request", "extract", "request", "assert"]
    assert all(step.status == "pending" for step in steps)

    assertions = list(
        (
            await read_session.execute(
                select(RunAssertion).where(RunAssertion.run_scenario_id == scenario.id)
            )
        ).scalars()
    )
    assert len(assertions) == 1
    assertion = assertions[0]
    assert assertion.assertion_key == ASSERTION_KEY
    assert assertion.assertion_type == "status"
    assert assertion.target == "status"
    assert assertion.expected_value == "201", "expected_value is stored as the string it is"
    assert assertion.status == "skipped", "an assertion that has not run is skipped"

    # The assertion hangs off the step that decides it: the first assert-kind step,
    # or the last step when there is none.  The assert marker is explicit here, so
    # the reads of the two requests are unambiguous.
    assert assertion.run_step_id == steps[-1].id
    assert steps[-1].step_key == ASSERT_STEP


async def test_snapshot_keeps_the_plan_side_source_links(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The snapshot copies the plan tree, and remembers where it was copied from."""
    run_id = await _create_run(fixtures, stack, monkeypatch)

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()

    # A run create materialises the plan it was handed, so the plan-side tables
    # hold the submitted tree and the run points at it.
    stored_plan = (
        await read_session.execute(select(_TestPlan).where(_TestPlan.id == run.plan_id))
    ).scalar_one()
    assert stored_plan.public_id == PLAN_ID
    assert stored_plan.status == "approved"

    stored_scenarios = list(
        (
            await read_session.execute(
                select(_TestScenario).where(_TestScenario.plan_id == stored_plan.id)
            )
        ).scalars()
    )
    assert [s.scenario_key for s in stored_scenarios] == [SCENARIO_KEY]

    stored_steps = {
        step.step_key: step
        for step in (
            await read_session.execute(
                select(_TestStep).where(_TestStep.scenario_id == stored_scenarios[0].id)
            )
        ).scalars()
    }
    assert set(stored_steps) == {READ_STEP, EXTRACT_STEP, CREATE_STEP, ASSERT_STEP}

    # The run rows point back at the rows they were copied from.
    scenario = (await _scenario_rows(read_session, run_id))[0]
    assert scenario.source_scenario_id == stored_scenarios[0].id

    steps = await _step_rows(read_session, scenario.id)
    by_key = {step.step_key: step for step in steps}
    for key in (READ_STEP, EXTRACT_STEP, CREATE_STEP, ASSERT_STEP):
        assert by_key[key].source_step_id == stored_steps[key].id


# --------------------------------------------------------------------------- #
# 2. method/path: plan step -> stored config -> run snapshot -> the request sent
# --------------------------------------------------------------------------- #


async def test_method_and_path_survive_from_plan_to_snapshot_to_request(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The four places a target lives, asserted in one walk.

    test_steps.config is the plan side (the step table has no method or path
    column), run_steps.method/path is the snapshot, and httpx.Request is what was
    actually sent.  A mismatch anywhere in that chain is a run calling the wrong
    endpoint, so all four are checked rather than the two ends.
    """
    client = _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    # (a) what the plan stored: only request steps carry a target
    scenario = (await _scenario_rows(read_session, run_id))[0]
    stored_scenario = (
        await read_session.execute(
            select(_TestScenario).where(_TestScenario.id == scenario.source_scenario_id)
        )
    ).scalar_one()
    configs = {
        step.step_key: step.config
        for step in (
            await read_session.execute(
                select(_TestStep).where(_TestStep.scenario_id == stored_scenario.id)
            )
        ).scalars()
    }
    assert configs[READ_STEP] == {"method": "GET", "path": READ_PATH}
    assert configs[CREATE_STEP] == {"method": "POST", "path": CREATE_PATH}
    assert configs[EXTRACT_STEP] == {}, "a non-request step has no target to store"
    assert configs[ASSERT_STEP] == {}, "the assert marker carries no target either"

    # (b) what the run snapshot carries
    steps = {step.step_key: step for step in await _step_rows(read_session, scenario.id)}
    assert (steps[READ_STEP].method, steps[READ_STEP].path) == ("GET", READ_PATH)
    assert (steps[CREATE_STEP].method, steps[CREATE_STEP].path) == ("POST", CREATE_PATH)
    assert (steps[EXTRACT_STEP].method, steps[EXTRACT_STEP].path) == (None, None)

    # (c) what the executor actually sent -- the whole point of the walk
    await run_executor.execute_run(run_id)

    sent = [(r.method, r.url.path, r.url.query.decode()) for r in client.sent]
    assert sent == [
        ("GET", "/orders/order_1", ""),
        ("POST", "/orders", "for=order_1"),
    ], f"the executor called something else: {sent}"


# --------------------------------------------------------------------------- #
# 3. The real executor runs the snapshot and the run finishes passed
# --------------------------------------------------------------------------- #


async def test_executor_runs_the_snapshot_to_a_passed_run(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """One complete successful run, and the final state it leaves behind."""
    client = _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    await run_executor.execute_run(run_id)

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "passed", f"expected a passed run, got {run.status!r} ({run.error_code!r})"
    assert run.started_at is not None and run.finished_at is not None
    assert run.finished_at >= run.started_at
    assert run.error_code is None
    assert run.error_message is None

    scenario = (await _scenario_rows(read_session, run_id))[0]
    assert scenario.status == "passed"

    steps = await _step_rows(read_session, scenario.id)
    assert [step.status for step in steps] == ["passed", "passed", "passed", "passed"]
    assert all(step.started_at is not None for step in steps)
    assert all(step.finished_at is not None for step in steps)

    assertions = list(
        (
            await read_session.execute(
                select(RunAssertion).where(RunAssertion.run_scenario_id == scenario.id)
            )
        ).scalars()
    )
    assert len(assertions) == 1
    assert assertions[0].status == "passed"
    assert assertions[0].actual_value == "201"

    # Two requests, in the order the plan listed them.
    assert [r.method for r in client.sent] == ["GET", "POST"]

    # The run is no longer registered as executing.
    assert run_id not in run_executor._RUNNING_TASKS


async def test_extract_step_feeds_the_step_that_consumes_it(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The extracted value is what the next request used, not a stub."""
    client = _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    await run_executor.execute_run(run_id)

    sent = list(client.sent)
    assert len(sent) == 2
    # orderId is nowhere in the submitted plan: it comes out of the first response.
    assert sent[1].url.query.decode() == "for=order_1"


async def test_an_extract_is_visible_to_a_later_scenario(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The runtime context is run-scoped, not scenario-scoped.

    The first scenario creates the variable; the second scenario is a separate
    story that starts after it.  This is the contract the console must explain:
    Extract values live for the whole run, and no environment value is needed.
    """
    client = _install_client(monkeypatch)
    plan = copy.deepcopy(_plan_payload())
    plan["scenarios"].append(
        {
            "id": "scenario_c17_second",
            "index": 1,
            "name": {"text": "read the order from a later scenario"},
            "description": {"text": "uses the run-scoped variable"},
            "expected": {"text": "the later read succeeds"},
            "riskLevel": "low",
            "steps": [
                {
                    "id": "step_c17_later_read",
                    "index": 0,
                    "kind": "request",
                    "description": {"text": "read with the run-scoped variable"},
                    "endpointId": None,
                    "method": "GET",
                    "path": "/orders/{{orderId}}",
                    "produces": None,
                    "consumes": ["orderId"],
                },
                {
                    "id": "step_c17_later_assert",
                    "index": 1,
                    "kind": "assert",
                    "description": {"text": "check the later read"},
                    "endpointId": None,
                    "method": None,
                    "path": None,
                    "produces": None,
                    "consumes": [],
                },
            ],
            "assertions": [
                {
                    "id": "assertion_c17_later_status",
                    "kind": "status",
                    "target": "status",
                    "expected": "200",
                    "description": {"text": "the later read answers 200"},
                }
            ],
        }
    )

    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    await run_executor.execute_run(run_id)

    sent = list(client.sent)
    assert [request.method for request in sent] == ["GET", "POST", "GET"]
    assert sent[-1].url.path == "/orders/order_1"
    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "passed"


async def test_a_missing_variable_fails_before_an_uninterpolated_request(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """A missing value is a failure, not a literal template sent to the API."""
    client = _install_client(monkeypatch)
    plan = copy.deepcopy(_plan_payload())
    plan["scenarios"] = [
        {
            "id": "scenario_c17_missing",
            "index": 0,
            "name": {"text": "needs an id the run does not have"},
            "description": {"text": "the variable is absent"},
            "expected": {"text": "the run refuses before calling"},
            "riskLevel": "low",
            "steps": [
                {
                    "id": "step_c17_missing_read",
                    "index": 0,
                    "kind": "request",
                    "description": {"text": "read with an absent variable"},
                    "endpointId": None,
                    "method": "GET",
                    "path": "/orders/{{orderId}}",
                    "produces": None,
                    "consumes": ["orderId"],
                },
                {
                    "id": "step_c17_missing_assert",
                    "index": 1,
                    "kind": "assert",
                    "description": {"text": "check the missing read"},
                    "endpointId": None,
                    "method": None,
                    "path": None,
                    "produces": None,
                    "consumes": [],
                },
            ],
            "assertions": [
                {
                    "id": "assertion_c17_missing_status",
                    "kind": "status",
                    "target": "status",
                    "expected": "200",
                    "description": {"text": "the read would answer 200"},
                }
            ],
        }
    ]

    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)
    await run_executor.execute_run(run_id)

    assert list(client.sent) == []
    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "failed"
    assert run.error_code == "missing-runtime-variable"


# --------------------------------------------------------------------------- #
# 4. Events: the real writer, dense seq, contract order, readable back
# --------------------------------------------------------------------------- #


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


async def test_the_successful_run_emits_a_dense_contract_event_stream(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The events of one successful run, read back from the database."""
    _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    await run_executor.execute_run(run_id)

    events = await _event_rows(read_session, run_id)
    kinds = [event.event_type for event in events]

    assert all(event.run_id == run_id for event in events)
    assert all(kind in FROZEN_EVENT_TYPES for kind in kinds), (
        f"an event outside the frozen set was written: {sorted(set(kinds) - FROZEN_EVENT_TYPES)}"
    )

    assert [event.seq for event in events] == list(range(1, len(events) + 1)), (
        f"seq must be dense from 1, got {[e.seq for e in events]}"
    )

    # The order the executor walks: start, then each step settled in turn, then end.
    assert kinds[0] == "run.started"
    assert kinds[-1] == "run.completed"
    assert kinds.count("run.started") == 1
    assert kinds.count("run.completed") == 1
    assert "run.failed" not in kinds

    assert kinds.count("step.started") == 4, "four steps were walked"
    assert kinds.count("step.completed") == 4
    assert "step.failed" not in kinds

    # One assertion was evaluated, so one assertion event.
    assert kinds.count("assertion.completed") == 1

    # Every step.started is followed by that step being settled before the next
    # step starts -- the executor finishes a step before beginning another.
    step_starts = [i for i, k in enumerate(kinds) if k == "step.started"]
    for position in step_starts:
        assert kinds[position + 1] in ("step.completed", "assertion.completed"), (
            f"step at {position} was not settled before the next event: {kinds}"
        )

    # The payloads are the contract payloads, not invented here.
    payloads = [dict(event.payload) for event in events]
    assert "startedAt" in payloads[0]
    assert "finishedAt" in payloads[-1] and "durationMs" in payloads[-1]


async def test_events_are_readable_through_the_events_service(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The same history, through the reader the events route calls.

    The route itself needs a guest session header; the body shape it returns is
    produced by runs.get_run_events, so that is what is read here.  This file does
    not claim the HTTP route or the SSE stream was exercised.
    """
    _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    await run_executor.execute_run(run_id)

    stored = await _event_rows(read_session, run_id)
    read = await runs.get_run_events(read_session, run_id=str(run_id), from_seq=1)

    assert len(read) == len(stored), "the reader returned a different history"
    assert [item.seq for item in read] == [event.seq for event in stored]
    assert [item.event_type for item in read] == [event.event_type for event in stored]
    assert [dict(item.payload) for item in read] == [dict(event.payload) for event in stored]

    # fromSeq is a resume point, inclusive.
    tail = await runs.get_run_events(
        read_session, run_id=str(run_id), from_seq=stored[-1].seq
    )
    assert [item.seq for item in tail] == [stored[-1].seq]


# --------------------------------------------------------------------------- #
# 5. A failing assertion reaches the run
# --------------------------------------------------------------------------- #


async def test_a_failed_assertion_fails_the_step_and_the_run(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """The other end of the same machinery: a wrong expectation is reported."""
    _install_client(monkeypatch)

    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()
    public_id = await _project_public_id(fixtures, stack["project"])

    # The same plan, expecting 200 from an endpoint that answers 201.
    body = _run_body(public_id)
    body["plan"]["scenarios"][0]["assertions"][0]["expected"] = "200"

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    response = await runs.create_run(
        fixtures.session, project_id=public_id, payload=RunCreateRequest.model_validate(body)
    )
    run_id = uuid.UUID(str(response.id))

    await run_executor.execute_run(run_id)

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "failed", f"expected a failed run, got {run.status!r}"
    assert run.error_code is not None

    scenario = (await _scenario_rows(read_session, run_id))[0]
    assert scenario.status == "failed"

    assertion = (
        await read_session.execute(
            select(RunAssertion).where(RunAssertion.run_scenario_id == scenario.id)
        )
    ).scalar_one()
    assert assertion.status == "failed"
    assert assertion.actual_value == "201", "the recorded actual is what the API answered"

    events = await _event_rows(read_session, run_id)
    kinds = [event.event_type for event in events]
    assert kinds[-1] == "run.failed"
    assert "run.completed" not in kinds
    assert "assertion.completed" in kinds
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert all(kind in FROZEN_EVENT_TYPES for kind in kinds)

# --------------------------------------------------------------------------- #
# 6. An explicit Extract source path survives the snapshot and feeds the next URL
# --------------------------------------------------------------------------- #


async def test_extract_source_path_maps_id_to_post_id_across_the_run_snapshot(
    fixtures, stack, read_session, monkeypatch
) -> None:
    """GET /posts -> $[0].id into postId -> GET /posts/101.

    The response deliberately does not contain a postId field; only the source
    path and the target variable name connect the two concepts.
    """
    client = _install_client(monkeypatch)

    plan = copy.deepcopy(_plan_payload())
    steps = plan["scenarios"][0]["steps"]
    steps[0]["path"] = "/posts"
    steps[1]["sourcePath"] = "$[0].id"
    steps[1]["sourceStepId"] = READ_STEP
    steps[1]["produces"] = "postId"
    steps[2]["path"] = "/posts/{{postId}}"
    steps[2]["method"] = "GET"
    steps[2]["consumes"] = ["postId"]
    plan["scenarios"][0]["assertions"][0]["expected"] = "200"

    run_id = await _create_run(fixtures, stack, monkeypatch, plan=plan)

    scenario = (await _scenario_rows(read_session, run_id))[0]
    by_key = {step.step_key: step for step in await _step_rows(read_session, scenario.id)}
    extract = by_key[EXTRACT_STEP]
    assert extract.source_path == "$[0].id"
    assert extract.source_step_key == READ_STEP

    stored_extract = (
        await read_session.execute(
            select(_TestStep)
            .join(_TestScenario, _TestScenario.id == _TestStep.scenario_id)
            .where(
                _TestScenario.scenario_key == SCENARIO_KEY,
                _TestStep.step_key == EXTRACT_STEP,
            )
        )
    ).scalar_one()
    assert stored_extract.config == {
        "sourcePath": "$[0].id",
        "sourceStepId": READ_STEP,
    }

    project_public_id = await _project_public_id(fixtures, stack["project"])
    plans = await agent_service.list_plans(read_session, project_id=project_public_id)
    read_back = next(
        step
        for plan in plans
        for scenario in plan.scenarios
        for step in scenario.steps
        if step.id == EXTRACT_STEP
    )
    assert read_back.source_path == "$[0].id"
    assert read_back.source_step_id == READ_STEP

    await run_executor.execute_run(run_id)

    sent = list(client.sent)
    assert [request.url.path for request in sent] == ["/posts", "/posts/101"]

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "passed"
