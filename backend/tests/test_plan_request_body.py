"""The request body, from the OpenAPI document to the wire.

The chain this file pins down is the one that was missing: a parsed
requestBody schema becomes a plan step body, the body travels in the plan
step config, and the executor puts it in the HTTP request as JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.services import agent_plan
from backend.services.agent_plan import (
    _extract_endpoints,
    _request_step,
    json_body_for,
)
from backend.services.run_executor import _Step

ORDERS = json.loads(
    """{
  "openapi": "3.0.3",
  "info": {"title": "Orders API", "version": "1.0.0"},
  "paths": {
    "/orders": {
      "post": {
        "summary": "Create an order",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["productId", "quantity"],
                "properties": {
                  "productId": {"type": "string", "minLength": 1},
                  "quantity": {"type": "integer", "minimum": 1},
                  "note": {"type": "string"}
                }
              }
            }
          }
        },
        "responses": {"201": {"description": "created"}}
      }
    },
    "/orders/{orderId}": {
      "get": {
        "summary": "Read one order",
        "responses": {"200": {"description": "the order"}}
      }
    }
  }
}"""
)


def _endpoint(document: dict[str, Any], method: str, path: str):
    endpoints, _ = _extract_endpoints(document, "openapi-3")
    for endpoint in endpoints:
        if endpoint.method == method and endpoint.path == path:
            return endpoint
    raise AssertionError("no endpoint " + method + " " + path)


def test_post_gets_a_body_that_satisfies_the_document() -> None:
    endpoint = _endpoint(ORDERS, "POST", "/orders")
    step = _request_step(0, endpoint, "console.aiTest.step.callEndpoint", {}, [])

    assert step.body_present is True
    assert isinstance(step.body, dict)
    # Required fields only; the optional "note" is not invented.
    assert set(step.body) == {"productId", "quantity"}
    assert isinstance(step.body["productId"], str) and step.body["productId"] != ""
    assert isinstance(step.body["quantity"], int) and not isinstance(step.body["quantity"], bool)
    assert step.body["quantity"] >= 1


def test_a_read_without_a_request_body_still_has_none() -> None:
    endpoint = _endpoint(ORDERS, "GET", "/orders/{orderId}")
    step = _request_step(0, endpoint, "console.aiTest.step.callEndpoint", {}, [])

    assert step.body_present is False
    assert step.body is None


def test_an_explicit_example_wins_over_synthesis() -> None:
    value, generated = json_body_for(
        {"type": "object", "properties": {"a": {"type": "string"}}, "example": {"a": "given"}}
    )
    assert (value, generated) == ({"a": "given"}, True)

    value, generated = json_body_for({"type": "string", "enum": ["eur", "usd"]})
    assert (value, generated) == ("eur", True)


def test_a_schema_it_cannot_state_honestly_is_not_an_empty_object() -> None:
    # An object with no properties cannot be turned into a legal sample.
    assert json_body_for({"type": "object"}) == (None, False)
    # A required field the generator cannot build fails the whole body rather
    # than producing one that is certain to be rejected.
    assert json_body_for(
        {"type": "object", "required": ["weird"], "properties": {"weird": {"type": "mystery"}}}
    ) == (None, False)


def test_json_null_is_a_body_and_none_is_not() -> None:
    # The distinction the plan has to preserve.
    step_none = _Step(id=None, key="k", kind="request", method="POST", path="/x", produces=None)
    assert step_none.body_present is False

    step_null = _Step(
        id=None, key="k", kind="request", method="POST", path="/x", produces=None, body=None, body_present=True
    )
    assert step_null.body_present is True
    assert step_null.body is None


@pytest.mark.anyio
async def test_the_executor_puts_the_body_in_the_request() -> None:
    """The wire, not the call: what the executor hands the HTTP client."""
    from backend.services import run_executor

    captured = {}

    class _Client:
        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs

            class _Response:
                status_code = 201
                headers = {"content-type": "application/json"}
                text = "{\"id\": \"order_1\"}"

            return _Response()

    context = run_executor.RunExecutionContext(
        run_id=None,
        project_id=None,
        environment_id=None,
        base_url="http://127.0.0.1:18002",
        variables={},
        runtime={},
    )

    step = _Step(
        id=None,
        key="k",
        kind="request",
        method="POST",
        path="/orders",
        produces=None,
        body={"productId": "prod_1", "quantity": 2},
        body_present=True,
    )

    outcome, response, _ = await run_executor._execute_step(
        step=step, context=context, auth=None, client=_Client(), response=None
    )

    assert outcome is None
    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert captured["kwargs"]["json"] == {"productId": "prod_1", "quantity": 2}


@pytest.mark.anyio
async def test_a_step_without_a_body_sends_no_body() -> None:
    from backend.services import run_executor

    captured = {}

    class _Client:
        async def request(self, method, url, **kwargs):
            captured["kwargs"] = kwargs

            class _Response:
                status_code = 200
                headers = {}
                text = ""

            return _Response()

    context = run_executor.RunExecutionContext(
        run_id=None,
        project_id=None,
        environment_id=None,
        base_url="http://127.0.0.1:18002",
        variables={},
        runtime={},
    )
    step = _Step(id=None, key="k", kind="request", method="GET", path="/orders/1", produces=None)

    outcome, _, _ = await run_executor._execute_step(
        step=step, context=context, auth=None, client=_Client(), response=None
    )

    assert outcome is None
    assert "json" not in captured["kwargs"]
