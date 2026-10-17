"""Assertions are grouped by the request whose response they read.

The defect these tests cover was a plan-shape one: every assertion in a
scenario hung off one assert step at the end, so the executor judged the create
order's 201 against the read order's 200.  Two planner paths produce plans, and
both now build the same layout -- POST, its assertions, the extract, GET, its
assertions -- from the real endpoint association.  The last test runs that plan
through the product's own run service and executor, not just the assertion
helper.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from backend.db.models.project import Environment
from backend.db.models.result import RunAssertion, RunStep
from backend.db.models.result import TestRun as _TestRun
from backend.schemas.run import RunCreateRequest
from backend.services import agent_analyzer, agent_plan, run_executor, runs
from backend.services.agent import derive_spec_identity, probe_document

pytestmark = pytest.mark.anyio

ORDERS_DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "post": {
                "summary": "Create an order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["productId", "quantity"],
                                "properties": {
                                    "productId": {"type": "string", "minLength": 1},
                                    "quantity": {"type": "integer", "minimum": 1},
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "created"}},
            }
        },
        "/orders/{orderId}": {
            "get": {
                "summary": "Read one order",
                "responses": {"200": {"description": "the order"}},
            }
        },
    },
}

ORDERS_TEXT = json.dumps(ORDERS_DOCUMENT)
ORDERS_IDENTITY = derive_spec_identity(
    spec_document=ORDERS_TEXT, spec_id="spec_probe", facts=probe_document(ORDERS_TEXT)
)
ORDERS_SLUG = ORDERS_IDENTITY.slug
ORDERS_SPEC_ID = "spec_" + ORDERS_SLUG
BASE_URL = "http://127.0.0.1:9"
ENVIRONMENT_ID = "env_c30m_orders"


def _parsed() -> agent_plan.ParsedSpec:
    endpoints, resources = agent_plan._extract_endpoints(ORDERS_DOCUMENT, "openapi-3")
    spec = agent_plan.SpecFacts(
        id=ORDERS_SPEC_ID,
        project_id="PLACEHOLDER",
        slug=ORDERS_SLUG,
        title="Orders API",
        version="1.0.0",
        format="openapi-3",
        source="upload",
        filename="orders.json",
        server_url=None,
        endpoint_count=len(endpoints),
        loaded_at="2026-10-17T00:00:00Z",
    )
    authentication = agent_plan.AuthenticationFacts(
        scheme="none",
        scheme_name=None,
        header_name=None,
        token_source_endpoint_id=None,
        token_field=None,
        protected_endpoint_count=0,
    )
    return agent_plan.ParsedSpec(
        spec=spec, endpoints=endpoints, resources=resources, authentication=authentication
    )


def _groups(scenario: agent_plan.PlanScenario) -> list[list[agent_plan.PlanAssertion]]:
    return [
        [assertion for assertion in scenario.assertions if assertion.step_id == step.id]
        for step in scenario.steps
        if step.kind == "assert"
    ]


# --------------------------------------------------------------------------- #
# 1. The deterministic rule engine
# --------------------------------------------------------------------------- #


def test_the_deterministic_planner_splits_the_order_lifecycle_assertions() -> None:
    parsed = _parsed()
    plan = agent_plan.generate_plan(agent_plan.analyze(parsed), parsed.spec)
    agent_plan.validate_plan(
        plan,
        project_id=parsed.spec.project_id,
        spec_id=parsed.spec.id,
        expected_plan_id=plan.id,
    )

    scenario = next(
        item for item in plan.scenarios if item.id.startswith("scenario_lifecycle_")
    )

    assert [step.kind for step in scenario.steps] == [
        "request",
        "assert",
        "extract",
        "request",
        "assert",
    ]
    assert [step.index for step in scenario.steps] == [0, 1, 2, 3, 4]

    create, create_assert, extract, read, read_assert = scenario.steps
    assert (create.method, create.path) == ("POST", "/orders")
    assert create.body_present is True
    assert isinstance(create.body, dict)
    assert set(create.body) == {"productId", "quantity"}

    assert (extract.kind, extract.produces) == ("extract", "orderId")
    assert (read.method, read.path) == ("GET", "/orders/{{orderId}}")
    assert read.body_present is False
    assert read.body is None

    assert create_assert.id != read_assert.id
    assert create_assert.id == "assert__1"
    assert read_assert.id == "assert__4"

    groups = _groups(scenario)
    assert len(groups) == 2

    create_assertions, read_assertions = groups
    assert {assertion.id for assertion in create_assertions} == {
        "ep_post_orders__status",
        "ep_post_orders__id",
    }
    assert {assertion.id for assertion in read_assertions} == {
        "ep_get_orders_orderid__status"
    }

    assert any(
        assertion.kind == "status" and assertion.expected == "201"
        for assertion in create_assertions
    )
    assert any(
        assertion.kind == "field"
        and assertion.target == "body.id"
        and assertion.expected == "present"
        for assertion in create_assertions
    )
    assert any(
        assertion.kind == "status" and assertion.expected == "200"
        for assertion in read_assertions
    )
    assert not any(assertion.expected == "201" for assertion in read_assertions)


# --------------------------------------------------------------------------- #
# 2. The model planner
# --------------------------------------------------------------------------- #


def _design() -> agent_analyzer.PlanDesign:
    parsed = _parsed()
    post = next(endpoint for endpoint in parsed.endpoints if endpoint.method == "POST")
    get = next(endpoint for endpoint in parsed.endpoints if endpoint.method == "GET")

    def step(kind: str, endpoint_id: str | None) -> dict[str, Any]:
        return {
            "kind": kind,
            "description": {"key": "console.aiTest.step.callEndpoint"},
            "endpoint_id": endpoint_id,
            "method": None,
            "path": None,
            "produces": None,
            "consumes": [],
        }

    design = agent_analyzer.PlanDesign.model_validate(
        {
            "name": {"key": "console.aiTest.plan.lifecycleName"},
            "goal": {"key": "console.aiTest.plan.lifecycleGoal"},
            "risk_level": "high",
            "scenarios": [
                {
                    "name": {"text": "Order lifecycle"},
                    "description": {"text": "create then read"},
                    "expected": {"text": "both requests succeed"},
                    "risk_level": "high",
                    "steps": [
                        step("request", post.id),
                        step("extract", post.id),
                        step("request", get.id),
                        {
                            "kind": "assert",
                            "description": {"key": "console.aiTest.step.assertResponse"},
                            "endpoint_id": None,
                            "method": None,
                            "path": None,
                            "produces": None,
                            "consumes": [],
                        },
                    ],
                    # Deliberately not in request order: grouping must follow the
                    # real endpoint association, not the order they were written.
                    "assertions": [
                        {
                            "kind": "status",
                            "target": "status",
                            "expected": "200",
                            "description": {"key": "console.aiTest.assertion.statusIs"},
                            "endpoint_id": get.id,
                        },
                        {
                            "kind": "status",
                            "target": "status",
                            "expected": "201",
                            "description": {"key": "console.aiTest.assertion.statusIs"},
                            "endpoint_id": post.id,
                        },
                        {
                            "kind": "field",
                            "target": "body.id",
                            "expected": "present",
                            "description": {
                                "key": "console.aiTest.assertion.fieldPresent",
                                "params": {"field": "id"},
                            },
                            "endpoint_id": get.id,
                        },
                        {
                            "kind": "field",
                            "target": "body.id",
                            "expected": "present",
                            "description": {
                                "key": "console.aiTest.assertion.fieldPresent",
                                "params": {"field": "id"},
                            },
                            "endpoint_id": post.id,
                        },
                        {
                            "kind": "field",
                            "target": "body.status",
                            "expected": "present",
                            "description": {
                                "key": "console.aiTest.assertion.fieldPresent",
                                "params": {"field": "status"},
                            },
                            "endpoint_id": get.id,
                        },
                    ],
                }
            ],
        }
    )
    design.scenarios[0].steps[1].produces = "orderId"
    design.scenarios[0].steps[2].consumes = ["orderId"]
    return design


def _model_plan() -> agent_plan.PlanPayload:
    plan = agent_analyzer.design_to_plan(_design(), _parsed())
    agent_plan.validate_plan(
        plan,
        project_id="PLACEHOLDER",
        spec_id=ORDERS_SPEC_ID,
        expected_plan_id=plan.id,
    )
    return plan


def test_the_model_planner_splits_the_order_lifecycle_assertions() -> None:
    scenario = _model_plan().scenarios[0]

    assert [step.kind for step in scenario.steps] == [
        "request",
        "assert",
        "extract",
        "request",
        "assert",
    ]
    create, create_assert, extract, read, read_assert = scenario.steps
    assert (create.method, create.path) == ("POST", "/orders")
    assert create.body_present is True
    assert (extract.kind, extract.produces) == ("extract", "orderId")
    assert (read.method, read.path) == ("GET", "/orders/{{orderId}}")
    assert read.body_present is False and read.body is None
    assert create_assert.id != read_assert.id

    groups = _groups(scenario)
    assert len(groups) == 2
    create_assertions, read_assertions = groups

    assert {assertion.expected for assertion in create_assertions} == {"201", "present"}
    assert {assertion.target for assertion in create_assertions} == {"status", "body.id"}
    assert {assertion.expected for assertion in read_assertions} == {"200", "present"}
    assert {assertion.target for assertion in read_assertions} == {
        "status",
        "body.id",
        "body.status",
    }
    assert not any(assertion.expected == "201" for assertion in read_assertions)
    assert all(
        assertion.step_id in {step.id for step in scenario.steps}
        for assertion in scenario.assertions
    )
    # Both paths build the same shape, which is what keeps them from drifting.
    deterministic = next(
        item
        for item in agent_plan.generate_plan(
            agent_plan.analyze(_parsed()), _parsed().spec
        ).scenarios
        if item.id.startswith("scenario_lifecycle_")
    )
    assert [step.kind for step in deterministic.steps] == [
        step.kind for step in scenario.steps
    ]


# --------------------------------------------------------------------------- #
# 3. The executor, through the real run service
# --------------------------------------------------------------------------- #


class _LifecycleClient(httpx.AsyncClient):
    """Answers the two calls with deliberately different bodies."""

    sent: list[httpx.Request] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.pop("transport", None)
        super().__init__(*args, transport=httpx.MockTransport(self._answer), **kwargs)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        type(self).sent.append(request)
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(
                201,
                json={
                    "id": "order_post_123",
                    "orderId": "order_post_123",
                    "status": "created",
                },
            )
        if request.method == "GET" and request.url.path == "/orders/order_post_123":
            return httpx.Response(200, json={"id": "order_read_456", "status": "open"})
        return httpx.Response(404, json={"error": "unexpected target"})


def _install_client(monkeypatch: pytest.MonkeyPatch) -> type[_LifecycleClient]:
    _LifecycleClient.sent = []
    monkeypatch.setattr(httpx, "AsyncClient", _LifecycleClient)
    return _LifecycleClient


async def _seed_environment(fixtures, project_id: uuid.UUID) -> uuid.UUID:
    row = Environment(
        project_id=project_id,
        public_id=ENVIRONMENT_ID,
        name="C30-M environment",
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


async def _create_run(fixtures, stack, monkeypatch) -> uuid.UUID:
    await _seed_environment(fixtures, stack["project"])
    await fixtures.commit()

    public_id = await _project_public_id(fixtures, stack["project"])
    plan = _model_plan()
    plan.project_id = public_id
    plan.status = "approved"
    plan.approved_at = datetime.now(timezone.utc)

    payload = RunCreateRequest.model_validate(
        {
            "projectId": public_id,
            "planId": plan.id,
            "plan": plan.model_dump(by_alias=True, mode="json"),
            "specId": ORDERS_SPEC_ID,
            "specDocument": ORDERS_TEXT,
            "environmentId": ENVIRONMENT_ID,
            "variables": {},
            "baseUrl": BASE_URL,
        }
    )

    async def _do_not_schedule(run_id):
        return None

    monkeypatch.setattr(run_executor, "schedule_run", _do_not_schedule)
    response = await runs.create_run(
        fixtures.session, project_id=public_id, payload=payload
    )
    return uuid.UUID(str(response.id))


async def test_the_executor_binds_each_assertion_to_its_own_response(
    fixtures, stack, read_session, monkeypatch
) -> None:
    client = _install_client(monkeypatch)
    run_id = await _create_run(fixtures, stack, monkeypatch)

    await run_executor.execute_run(run_id)

    sent = list(client.sent)
    assert [(request.method, request.url.path) for request in sent] == [
        ("POST", "/orders"),
        ("GET", "/orders/order_post_123"),
    ]
    assert json.loads(sent[0].content)["productId"]
    assert sent[1].content == b"", "the read must not inherit the create's body"

    run = (
        await read_session.execute(select(_TestRun).where(_TestRun.id == run_id))
    ).scalar_one()
    assert run.status == "passed", f"expected passed, got {run.status!r} ({run.error_code!r})"
    assert run.error_code is None

    from backend.db.models.result import RunScenario

    scenario = (
        await read_session.execute(
            select(RunScenario).where(RunScenario.run_id == run_id)
        )
    ).scalar_one()
    steps = list(
        (
            await read_session.execute(
                select(RunStep)
                .where(RunStep.run_scenario_id == scenario.id)
                .order_by(RunStep.sort_order, RunStep.step_key)
            )
        ).scalars()
    )
    assert [step.step_key for step in steps] == [
        "ep_post_orders__0",
        "assert__1",
        "ep_post_orders__extract_orderId",
        "ep_get_orders_orderid__2",
        "assert__4",
    ]
    assert [step.status for step in steps] == ["passed"] * 5

    assertions = list(
        (
            await read_session.execute(
                select(RunAssertion)
                .where(RunAssertion.run_scenario_id == scenario.id)
                .order_by(RunAssertion.assertion_key)
            )
        ).scalars()
    )
    assert len(assertions) == 5
    assert all(assertion.status == "passed" for assertion in assertions)

    step_by_id = {step.id: step.step_key for step in steps}
    by_key = {assertion.assertion_key: assertion for assertion in assertions}

    post_status = by_key["ep_post_orders__status"]
    post_id = by_key["ep_post_orders__id"]
    get_status = by_key["ep_get_orders_orderid__status"]
    get_id = by_key["ep_get_orders_orderid__id"]
    get_body_status = by_key["ep_get_orders_orderid__status_5"]

    # The binding itself: the create's assertions point at the create's assert
    # step, the read's at the read's assert step.
    assert step_by_id[post_status.run_step_id] == "assert__1"
    assert step_by_id[post_id.run_step_id] == "assert__1"
    assert step_by_id[get_status.run_step_id] == "assert__4"
    assert step_by_id[get_id.run_step_id] == "assert__4"
    assert step_by_id[get_body_status.run_step_id] == "assert__4"

    # The decisive values: the create's status really read 201, the read's 200,
    # and the two body.id assertions saw different payloads.
    assert post_status.actual_value == "201"
    assert post_id.actual_value == "order_post_123"
    assert get_status.actual_value == "200"
    assert get_id.actual_value == "order_read_456"
    assert get_body_status.actual_value == "open"
