"""Both planner paths carry the OpenAPI request body.

The model path (design_to_plan) is the one the real Agent Lab uses by default,
and it used to build request steps with no body at all -- which is why a real UI
run sent POST /orders empty.  These tests cover that path and keep the
deterministic one honest at the same time.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.schemas.agent import AgentStepResponse
from backend.schemas.run import PlanStep
from backend.services import agent_analyzer, agent_plan
from backend.services.runs import _config_target

ORDERS = {
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


def _parsed():
    endpoints, resources = agent_plan._extract_endpoints(ORDERS, "openapi-3")
    spec = agent_plan.SpecFacts(
        id="spec_orders",
        project_id="prj_x",
        slug="orders",
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


def _step_design(kind: str, endpoint_id: str | None, description: str = "step") -> dict[str, Any]:
    return {
        "kind": kind,
        "description": {"key": "console.aiTest.step.callEndpoint"},
        "endpoint_id": endpoint_id,
        "method": None,
        "path": None,
        "produces": None,
        "consumes": [],
    }


def _design(post_id: str, get_id: str) -> agent_analyzer.PlanDesign:
    return agent_analyzer.PlanDesign.model_validate(
        {
            "name": {"key": "console.aiTest.plan.name"},
            "goal": {"key": "console.aiTest.plan.goal"},
            "risk_level": "low",
            "scenarios": [
                {
                    "name": {"key": "console.aiTest.scenario.post"},
                    "description": {"key": "console.aiTest.scenario.post"},
                    "expected": {"key": "console.aiTest.scenario.post"},
                    "risk_level": "low",
                    "steps": [
                        _step_design("request", post_id),
                        _step_design("assert", None),
                    ],
                },
                {
                    "name": {"key": "console.aiTest.scenario.get"},
                    "description": {"key": "console.aiTest.scenario.get"},
                    "expected": {"key": "console.aiTest.scenario.get"},
                    "risk_level": "low",
                    "steps": [
                        _step_design("request", get_id),
                        _step_design("assert", None),
                    ],
                },
            ],
        }
    )


def test_the_model_path_generates_the_body_from_the_schema() -> None:
    parsed = _parsed()
    post = next(e for e in parsed.endpoints if e.method == "POST")
    get = next(e for e in parsed.endpoints if e.method == "GET")

    plan = agent_analyzer.design_to_plan(_design(post.id, get.id), parsed)

    steps = {step.endpoint_id: step for scenario in plan.scenarios for step in scenario.steps if step.kind == "request"}
    post_step = steps[post.id]

    assert post_step.body_present is True
    assert isinstance(post_step.body, dict)
    assert isinstance(post_step.body["productId"], str) and post_step.body["productId"] != ""
    assert isinstance(post_step.body["quantity"], int) and not isinstance(post_step.body["quantity"], bool)


def test_the_model_path_leaves_a_read_without_a_body() -> None:
    parsed = _parsed()
    post = next(e for e in parsed.endpoints if e.method == "POST")
    get = next(e for e in parsed.endpoints if e.method == "GET")

    plan = agent_analyzer.design_to_plan(_design(post.id, get.id), parsed)

    steps = {step.endpoint_id: step for scenario in plan.scenarios for step in scenario.steps if step.kind == "request"}
    assert steps[get.id].body_present is False
    assert steps[get.id].body is None


def test_the_model_body_survives_persistence_and_the_response() -> None:
    parsed = _parsed()
    post = next(e for e in parsed.endpoints if e.method == "POST")
    get = next(e for e in parsed.endpoints if e.method == "GET")

    plan = agent_analyzer.design_to_plan(_design(post.id, get.id), parsed)
    step = next(
        s for scenario in plan.scenarios for s in scenario.steps if s.kind == "request" and s.method == "POST"
    )

    config = _config_target(step)
    assert config["bodyPresent"] is True
    assert isinstance(config["body"], dict)

    response = AgentStepResponse(
        id=step.id,
        index=step.index,
        kind=step.kind,
        description=step.description.model_dump(),
        endpoint_id=step.endpoint_id,
        method=step.method,
        path=step.path,
        produces=None,
        consumes=list(step.consumes),
        body=config["body"],
        body_present=config["bodyPresent"],
    )
    dumped = response.model_dump()
    assert dumped["body"] == config["body"]
    assert dumped["body_present"] is True
    assert PlanStep.model_validate(dumped).body_present is True
