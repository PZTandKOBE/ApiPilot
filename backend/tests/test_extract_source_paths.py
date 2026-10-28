"""Regression coverage for explicit Extract source paths and response facts."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.services import agent_analyzer, agent_plan, run_executor
from backend.services.json_path import parse_path, resolve_path


def _document() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Posts", "version": "1"},
        "paths": {
            "/posts": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Post"},
                                    }
                                }
                            },
                        }
                    }
                }
            },
            "/posts/{postId}": {
                "get": {
                    "parameters": [
                        {
                            "name": "postId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Post"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Post": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "userId": {"type": "integer"},
                        "title": {"type": "string"},
                        "owner": {"$ref": "#/components/schemas/User"},
                    },
                },
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            }
        },
    }


def test_json_path_subset_parses_and_resolves() -> None:
    assert parse_path("$[0].id")
    assert resolve_path([{"id": 101}], "$[0].id").found
    assert resolve_path({"data": [{"id": 5}]}, "$.data[0].id").value == 5
    assert not resolve_path({"data": {}}, "$.data.id").found
    assert "out of range" in resolve_path([], "$[0].id").reason
    assert not resolve_path({"id": 1}, "id").found


def test_parser_keeps_array_items_and_nested_refs() -> None:
    document = _document()
    endpoints, _ = agent_plan._extract_endpoints(document, "openapi-3")
    posts = next(endpoint for endpoint in endpoints if endpoint.path == "/posts")

    assert posts.response_props == ()
    assert "$[0].id" in posts.response_paths
    assert "$[0].userId" in posts.response_paths
    assert "$[0].owner.name" in posts.response_paths

    get_post = next(endpoint for endpoint in endpoints if endpoint.path == "/posts/{postId}")
    assert get_post.response_props == ("id", "userId", "title", "owner")
    assert "$.id" in get_post.response_paths
    assert "$.owner.name" in get_post.response_paths


def test_parser_is_safe_for_bad_and_cyclic_refs() -> None:
    document: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Broken", "version": "1"},
        "paths": {
            "/loop": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                }
                            },
                        }
                    }
                }
            },
            "/missing": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Missing"}
                                }
                            },
                        }
                    }
                }
            },
        },
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "child": {"$ref": "#/components/schemas/Node"},
                    },
                }
            }
        },
    }

    endpoints, _ = agent_plan._extract_endpoints(document, "openapi-3")
    loop = next(endpoint for endpoint in endpoints if endpoint.path == "/loop")
    missing = next(endpoint for endpoint in endpoints if endpoint.path == "/missing")

    assert "$.id" in loop.response_paths
    assert len([path for path in loop.response_paths if path.count("child") > 4]) == 0
    assert missing.response_paths == ()


def _context() -> run_executor.RunExecutionContext:
    return run_executor.RunExecutionContext(
        run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=None,
        base_url="https://example.test",
        variables={},
        runtime={},
    )


def _extract(source_path: str, produces: str, body: Any):
    context = _context()
    step = run_executor._Step(
        id=uuid.uuid4(),
        key="extract_source",
        kind="extract",
        method=None,
        path=None,
        produces=produces,
        source_path=source_path,
    )
    response = run_executor._Response(
        status_code=200,
        headers={},
        text="{}",
        json=body,
    )
    failure, _, _ = run_executor._extract(
        step=step,
        context=context,
        response=response,
    )
    return failure, context.runtime


def test_extract_maps_id_to_a_differently_named_variable() -> None:
    failure, runtime = _extract("$[0].id", "postId", [{"id": 101, "userId": 8}])
    assert failure is None
    assert runtime == {"postId": "101"}

    failure, runtime = _extract("$[0].userId", "authorId", [{"id": 101, "userId": 8}])
    assert failure is None
    assert runtime == {"authorId": "8"}

    failure, runtime = _extract("$.id", "postId", {"id": 101})
    assert failure is None
    assert runtime == {"postId": "101"}


def test_extract_nested_and_boolean_values() -> None:
    failure, runtime = _extract("$.active", "isActive", {"active": False})
    assert failure is None
    assert runtime == {"isActive": "false"}

    failure, runtime = _extract("$.data.id", "postId", {"data": {"id": 0}})
    assert failure is None
    assert runtime == {"postId": "0"}

    failure, runtime = _extract("$.id", "postId", {"id": None})
    assert failure is None
    assert runtime == {"postId": ""}

    failure, runtime = _extract("$.id", "postId", None)
    assert failure is not None
    assert "not JSON" in failure.detail
    assert runtime == {}


@pytest.mark.anyio
async def test_a_missing_source_response_is_reported() -> None:
    context = _context()
    step = run_executor._Step(
        id=uuid.uuid4(),
        key="extract_missing_source",
        kind="extract",
        method=None,
        path=None,
        produces="postId",
        source_path="$[0].id",
        source_step_key="read_posts",
    )
    response = run_executor._Response(
        status_code=200,
        headers={},
        text="[]",
        json=[],
    )

    outcome, _, _ = await run_executor._execute_step(
        step=step,
        context=context,
        auth=None,
        client=None,
        response=response,
        source_response=None,
    )

    assert outcome is not None
    assert outcome.code == run_executor.EXTRACT_FAILED
    assert "source response step read_posts" in outcome.detail



def test_extract_reports_invalid_and_missing_paths() -> None:
    failure, runtime = _extract("data[0].id", "postId", {"data": []})
    assert failure is not None
    assert failure.code == run_executor.EXTRACT_FAILED
    assert "did not resolve" in failure.detail
    assert runtime == {}

    failure, runtime = _extract("$[0].id", "postId", [])
    assert failure is not None
    assert failure.code == run_executor.EXTRACT_FAILED
    assert "out of range" in failure.detail
    assert runtime == {}


def test_legacy_name_lookup_remains_available() -> None:
    context = _context()
    step = run_executor._Step(
        id=uuid.uuid4(),
        key="legacy_extract",
        kind="extract",
        method=None,
        path=None,
        produces="orderId",
        source_path=None,
    )
    response = run_executor._Response(
        status_code=200,
        headers={},
        text="{}",
        json={"orderId": "order_1"},
    )
    failure, _, _ = run_executor._extract(step=step, context=context, response=response)
    assert failure is None
    assert context.runtime == {"orderId": "order_1"}


def test_agent_design_requires_a_source_path_for_extract() -> None:
    document = _document()
    parsed = agent_plan.parse_document(
        document,
        project_id="prj_test",
        spec_id="spec_test",
        slug="test",
        filename="posts.json",
        source="upload",
    )
    post = next(endpoint for endpoint in parsed.endpoints if endpoint.path == "/posts")

    payload = {
        "name": {"text": "Posts"},
        "goal": {"text": "read posts"},
        "risk_level": "low",
        "scenarios": [
            {
                "name": {"text": "Posts"},
                "description": {"text": "read posts"},
                "expected": {"text": "the response succeeds"},
                "risk_level": "low",
                "steps": [
                    {
                        "kind": "request",
                        "description": {"text": "list posts"},
                        "endpoint_id": post.id,
                        "method": "GET",
                        "path": "/posts",
                    },
                    {
                        "kind": "extract",
                        "description": {"text": "take the id"},
                        "endpoint_id": post.id,
                        "produces": "postId",
                    },
                ],
                "assertions": [],
            }
        ],
    }

    with pytest.raises(agent_plan.PlanPipelineError) as caught:
        agent_analyzer.design_from_payload(payload, parsed=parsed)

    assert caught.value.code == "plan-invalid"
    assert "source path" in caught.value.detail

    payload["scenarios"][0]["steps"][1]["source_path"] = "data[0].id"
    with pytest.raises(agent_plan.PlanPipelineError) as caught:
        agent_analyzer.design_from_payload(payload, parsed=parsed)

    assert caught.value.code == "plan-invalid"
    assert "invalid source path" in caught.value.detail
