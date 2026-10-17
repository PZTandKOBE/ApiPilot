"""Assertion and extract descriptions follow the actual response they read.

The multi-request layout is POST -> POST assertion -> Extract -> GET -> GET
assertion.  A single scenario-level sentence cannot describe both responses, so
the conversion generates the description from the step and assertion binding.
"""

from __future__ import annotations

from typing import Any

from backend.services import agent_analyzer, agent_plan

DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
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


def _parsed() -> agent_plan.ParsedSpec:
    return agent_plan.parse_document(
        DOCUMENT,
        project_id="prj_descriptions",
        spec_id="spec_descriptions",
        slug="descriptions",
        filename="orders.json",
        source="upload",
    )


def _endpoint(parsed: agent_plan.ParsedSpec, method: str, path: str):
    return next(
        item for item in parsed.endpoints if item.method == method and item.path == path
    )


def _lifecycle_plan() -> agent_plan.PlanPayload:
    parsed = _parsed()
    create = _endpoint(parsed, "POST", "/orders")
    read = _endpoint(parsed, "GET", "/orders/{orderId}")
    understanding = agent_plan.Understanding(
        spec_id=parsed.spec.id,
        endpoints=parsed.endpoints,
        resources=parsed.resources,
        authentication=parsed.authentication,
        dependencies=(
            agent_plan.DependencyFacts(
                id=f"dep_{create.id}__{read.id}__orderId",
                from_endpoint_id=create.id,
                to_endpoint_id=read.id,
                kind="lifecycle",
                binding="orderId",
                rationale={},
            ),
        ),
        risks=(),
        findings=(),
        analyzed_at="2026-10-17T00:00:00Z",
    )
    return agent_plan.generate_plan(understanding, parsed.spec)


def test_lifecycle_assert_steps_name_their_own_request() -> None:
    plan = _lifecycle_plan()
    lifecycle = next(
        scenario for scenario in plan.scenarios if scenario.id.startswith("scenario_lifecycle_")
    )

    assert [step.kind for step in lifecycle.steps] == [
        "request",
        "assert",
        "extract",
        "request",
        "assert",
    ]

    create_assert = lifecycle.steps[1]
    read_assert = lifecycle.steps[4]
    assert create_assert.description.model_dump() == {
        "key": "console.aiTest.step.assertRequestResponse",
        "params": {"method": "POST", "path": "/orders"},
    }
    assert read_assert.description.model_dump() == {
        "key": "console.aiTest.step.assertRequestResponse",
        "params": {"method": "GET", "path": "/orders/{{orderId}}"},
    }

    extract = lifecycle.steps[2]
    assert extract.description.model_dump() == {
        "key": "console.aiTest.step.extractVariableFrom",
        "params": {
            "variable": "orderId",
            "method": "POST",
            "path": "/orders",
        },
    }


def test_lifecycle_assertion_descriptions_name_the_response_value() -> None:
    plan = _lifecycle_plan()
    lifecycle = next(
        scenario for scenario in plan.scenarios if scenario.id.startswith("scenario_lifecycle_")
    )
    by_key = {assertion.id: assertion for assertion in lifecycle.assertions}

    descriptions = [
        assertion.description.model_dump() for assertion in by_key.values()
    ]
    assert {
        "key": "console.aiTest.assertion.statusIs",
        "params": {"status": "201"},
    } in descriptions
    assert {
        "key": "console.aiTest.assertion.statusIs",
        "params": {"status": "200"},
    } in descriptions
    assert {
        "key": "console.aiTest.assertion.fieldPresent",
        "params": {"field": "id"},
    } in descriptions


def test_a_design_scenario_level_description_does_not_leak_into_each_assert() -> None:
    parsed = _parsed()
    post = _endpoint(parsed, "POST", "/orders")
    get = _endpoint(parsed, "GET", "/orders/{orderId}")
    misleading = {
        "text": "Check both status codes and fields after create and read finish."
    }

    payload = {
        "name": {"text": "Order lifecycle"},
        "goal": {"text": "create then read"},
        "risk_level": "high",
        "scenarios": [
            {
                "name": {"text": "Order lifecycle"},
                "description": {"text": "create then read"},
                "expected": {"text": "both responses are correct"},
                "risk_level": "high",
                "steps": [
                    {
                        "kind": "request",
                        "description": {"text": "create an order"},
                        "endpoint_id": post.id,
                        "method": "POST",
                        "path": "/orders",
                    },
                    {
                        "kind": "assert",
                        "description": misleading,
                    },
                    {
                        "kind": "extract",
                        "description": {"text": "take the id"},
                        "endpoint_id": post.id,
                        "produces": "orderId",
                    },
                    {
                        "kind": "request",
                        "description": {"text": "read the order"},
                        "endpoint_id": get.id,
                        "method": "GET",
                        "path": "/orders/{{orderId}}",
                        "consumes": ["orderId"],
                    },
                    {
                        "kind": "assert",
                        "description": misleading,
                    },
                ],
                "assertions": [
                    {
                        "kind": "status",
                        "target": "status",
                        "expected": "201",
                        "description": misleading,
                        "endpoint_id": post.id,
                    },
                    {
                        "kind": "field",
                        "target": "body.id",
                        "expected": "present",
                        "description": misleading,
                        "endpoint_id": post.id,
                    },
                    {
                        "kind": "status",
                        "target": "status",
                        "expected": "200",
                        "description": misleading,
                        "endpoint_id": get.id,
                    },
                ],
            }
        ],
    }

    design = agent_analyzer.design_from_payload(payload, parsed=parsed)
    plan = agent_analyzer.design_to_plan(design, parsed)
    scenario = plan.scenarios[0]

    assert [step.kind for step in scenario.steps] == [
        "request",
        "assert",
        "extract",
        "request",
        "assert",
    ]
    for step in (scenario.steps[1], scenario.steps[4], scenario.steps[2]):
        assert misleading["text"] not in str(step.description)

    assert scenario.steps[1].description.model_dump() == {
        "key": "console.aiTest.step.assertRequestResponse",
        "params": {"method": "POST", "path": "/orders"},
    }
    assert scenario.steps[4].description.model_dump() == {
        "key": "console.aiTest.step.assertRequestResponse",
        "params": {"method": "GET", "path": "/orders/{{orderId}}"},
    }
    assert scenario.steps[2].description.model_dump() == {
        "key": "console.aiTest.step.extractVariableFrom",
        "params": {
            "variable": "orderId",
            "method": "POST",
            "path": "/orders",
        },
    }

    descriptions = [
        assertion.description.model_dump() for assertion in scenario.assertions
    ]
    assert {
        "key": "console.aiTest.assertion.statusIs",
        "params": {"status": "201"},
    } in descriptions
    assert {
        "key": "console.aiTest.assertion.statusIs",
        "params": {"status": "200"},
    } in descriptions
    assert {
        "key": "console.aiTest.assertion.fieldPresent",
        "params": {"field": "id"},
    } in descriptions
    assert all(description != misleading for description in descriptions)
