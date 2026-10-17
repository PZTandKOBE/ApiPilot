"""Planner paths compare ApiPilot runtime braces with OpenAPI document braces.

The model may echo /orders/{{orderId}} while the OpenAPI operation spells
/orders/{orderId}.  Validation must treat those as the same path without
loosening static segments, parameter names or counts.  The converted plan must
keep the runtime {{...}} form the executor interpolates.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.services import agent_analyzer, agent_plan

ORDERS = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "post": {
                "summary": "Create an order",
                "responses": {"201": {"description": "created"}},
            }
        },
        "/orders/{orderId}": {
            "get": {
                "summary": "Read one order",
                "parameters": [
                    {
                        "name": "orderId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "the order"}},
            }
        },
        "/orders/{orderId}/items/{itemId}": {
            "get": {
                "summary": "Read an item",
                "responses": {"200": {"description": "the item"}},
            }
        },
    },
}


def _parsed() -> agent_plan.ParsedSpec:
    endpoints, resources = agent_plan._extract_endpoints(ORDERS, "openapi-3")
    spec = agent_plan.SpecFacts(
        id="spec_c31r1_orders",
        project_id="prj_c31r1",
        slug="c31r1_orders",
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


def _endpoint(parsed: agent_plan.ParsedSpec, method: str, path: str):
    return next(
        endpoint
        for endpoint in parsed.endpoints
        if endpoint.method == method and endpoint.path == path
    )


def _request_design(
    endpoint_id: str,
    *,
    path: str,
    method: str = "GET",
    produces: str | None = None,
    consumes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": {"text": "C31-R1 path"},
        "goal": {"text": "path validation"},
        "risk_level": "low",
        "scenarios": [
            {
                "name": {"text": "path"},
                "description": {"text": "path"},
                "expected": {"text": "path"},
                "risk_level": "low",
                "steps": [
                    {
                        "kind": "request",
                        "description": {"key": "console.aiTest.step.callEndpoint"},
                        "endpoint_id": endpoint_id,
                        "method": method,
                        "path": path,
                        "produces": produces,
                        "consumes": consumes or [],
                    }
                ],
                "assertions": [],
            }
        ],
    }


def _issues(payload: dict[str, Any]) -> list[str]:
    parsed = _parsed()
    design = agent_analyzer.PlanDesign.model_validate(payload)
    return agent_analyzer.plan_design_issues(design, parsed)


def test_canonical_path_treats_runtime_and_document_parameters_alike() -> None:
    assert agent_plan.canonical_plan_path("/orders/{{orderId}}") == "/orders/{orderId}"
    assert (
        agent_plan.canonical_plan_path("/orders/{{orderId}}/items/{{itemId}}")
        == "/orders/{orderId}/items/{itemId}"
    )
    assert agent_plan.canonical_plan_path("/orders/{orderId}") == "/orders/{orderId}"
    assert agent_plan.canonical_plan_path("/orders") == "/orders"


@pytest.mark.parametrize(
    "path",
    [
        "/orders/{{orderId}",
        "/orders/{{{orderId}}}",
        "/orders/{orderId",
        "/orders/{}",
        "/orders/}orderId{",
    ],
)
def test_canonical_path_rejects_malformed_placeholders(path: str) -> None:
    assert agent_plan.canonical_plan_path(path) is None


def test_double_brace_path_matches_the_single_brace_document() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")

    assert _issues(_request_design(endpoint.id, path="/orders/{{orderId}}")) == []
    assert _issues(_request_design(endpoint.id, path="/orders/{orderId}")) == []


def test_multiple_double_brace_parameters_match_the_document() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}/items/{itemId}")

    assert (
        _issues(
            _request_design(
                endpoint.id, path="/orders/{{orderId}}/items/{{itemId}}"
            )
        )
        == []
    )


def test_parameter_name_mismatch_is_still_refused() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    issues = _issues(_request_design(endpoint.id, path="/orders/{{customerId}}"))

    assert any("customerId" in issue and "orderId" in issue for issue in issues)


def test_static_segment_mismatch_is_still_refused() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    issues = _issues(_request_design(endpoint.id, path="/customers/{{orderId}}"))

    assert any("/customers/" in issue for issue in issues)


def test_parameter_count_mismatch_is_still_refused() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    issues = _issues(
        _request_design(endpoint.id, path="/orders/{{orderId}}/items/{{itemId}}")
    )

    assert issues


def test_method_mismatch_is_still_refused() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    issues = _issues(
        _request_design(endpoint.id, path="/orders/{{orderId}}", method="POST")
    )

    assert any("POST" in issue and "GET" in issue for issue in issues)


def test_malformed_plan_path_is_still_refused() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    issues = _issues(_request_design(endpoint.id, path="/orders/{{{orderId}}}"))

    assert issues


def test_converted_plan_keeps_the_runtime_variable_path() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")
    design = agent_analyzer.design_from_payload(
        _request_design(endpoint.id, path="/orders/{{orderId}}"), parsed=parsed
    )
    plan = agent_analyzer.design_to_plan(design, parsed)
    step = next(
        item
        for scenario in plan.scenarios
        for item in scenario.steps
        if item.kind == "request"
    )

    assert step.path == "/orders/{{orderId}}"


def test_the_model_lifecycle_design_passes_both_paths() -> None:
    parsed = _parsed()
    post = _endpoint(parsed, "POST", "/orders")
    get = _endpoint(parsed, "GET", "/orders/{orderId}")

    payload = {
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
                    {
                        "kind": "request",
                        "description": {"key": "console.aiTest.step.callEndpoint"},
                        "endpoint_id": post.id,
                        "method": "POST",
                        "path": "/orders",
                    },
                    {
                        "kind": "extract",
                        "description": {
                            "key": "console.aiTest.step.extractVariable"
                        },
                        "endpoint_id": post.id,
                        "produces": "orderId",
                    },
                    {
                        "kind": "request",
                        "description": {"key": "console.aiTest.step.callEndpoint"},
                        "endpoint_id": get.id,
                        "method": "GET",
                        "path": "/orders/{{orderId}}",
                        "consumes": ["orderId"],
                    },
                    {
                        "kind": "assert",
                        "description": {"key": "console.aiTest.step.assertResponse"},
                    },
                ],
                "assertions": [],
            }
        ],
    }

    design = agent_analyzer.design_from_payload(payload, parsed=parsed)
    plan = agent_analyzer.design_to_plan(design, parsed)
    request_paths = [step.path for step in plan.scenarios[0].steps if step.kind == "request"]

    assert request_paths == ["/orders", "/orders/{{orderId}}"]


def test_the_deterministic_path_helper_is_unchanged() -> None:
    parsed = _parsed()
    endpoint = _endpoint(parsed, "GET", "/orders/{orderId}")

    assert agent_plan.request_step_path(endpoint) == "/orders/{{orderId}}"
