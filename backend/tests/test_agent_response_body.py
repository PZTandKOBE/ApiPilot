"""The request body across the real product boundary, not just the generator.

C29-R proved the generator produces a body.  That was not enough: the body also
has to survive AgentStepResponse serialisation, the Pydantic plan model the Run
payload is validated into, and the config blob test_steps stores -- and it did
not, which is why a real UI run sent POST /orders with no body at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.schemas.agent import AgentStepResponse
from backend.schemas.run import PlanStep
from backend.services import agent
from backend.services.runs import _config_target


def _step(**overrides: Any) -> AgentStepResponse:
    fields: dict[str, Any] = {
        "id": "step_1",
        "index": 0,
        "kind": "request",
        "description": {"key": "console.aiTest.step.callEndpoint"},
        "endpoint_id": None,
        "method": "POST",
        "path": "/orders",
        "produces": None,
        "consumes": [],
    }
    fields.update(overrides)
    return AgentStepResponse(**fields)


def test_the_body_survives_the_response_and_the_plan_model() -> None:
    response = _step(body={"productId": "x", "quantity": 1}, body_present=True)

    dumped = response.model_dump()
    assert dumped["body"] == {"productId": "x", "quantity": 1}
    assert dumped["body_present"] is True

    plan_step = PlanStep.model_validate(dumped)
    assert plan_step.body == {"productId": "x", "quantity": 1}
    assert plan_step.body_present is True


def test_the_body_reaches_the_config_the_executor_reads_from() -> None:
    plan_step = PlanStep.model_validate(
        _step(body={"productId": "x", "quantity": 1}, body_present=True).model_dump()
    )

    config = _config_target(plan_step)

    assert config["body"] == {"productId": "x", "quantity": 1}
    assert config["bodyPresent"] is True
    assert agent._config_body(config) == {"productId": "x", "quantity": 1}
    assert agent._config_flag(config, "bodyPresent") is True


def test_a_plan_without_a_body_still_persists_as_it_did() -> None:
    plan_step = PlanStep.model_validate(_step(method="GET", path="/orders/1").model_dump())

    config = _config_target(plan_step)

    assert "body" not in config
    assert "bodyPresent" not in config
    assert agent._config_body(config) is None
    assert agent._config_flag(config, "bodyPresent") is False


def test_a_json_null_body_is_not_the_same_as_no_body() -> None:
    plan_step = PlanStep.model_validate(_step(body=None, body_present=True).model_dump())

    config = _config_target(plan_step)

    assert config["bodyPresent"] is True
    assert config["body"] is None
    assert agent._config_flag(config, "bodyPresent") is True


@pytest.mark.parametrize("value", [False, 0, "", [], {}])
def test_a_falsy_json_body_is_still_a_body(value: Any) -> None:
    """The bug shape to avoid: a fallback that turns a real body into none."""
    plan_step = PlanStep.model_validate(_step(body=value, body_present=True).model_dump())

    config = _config_target(plan_step)

    assert config["bodyPresent"] is True
    assert config["body"] == value
    assert agent._config_body(config) == value


def test_the_response_keeps_a_body_it_was_given_by_the_store() -> None:
    """What agent.py now does: read body and bodyPresent back out of the row."""
    config = {"method": "POST", "path": "/orders", "body": {"productId": "x"}, "bodyPresent": True}

    assert agent._config_body(config) == {"productId": "x"}
    assert agent._config_flag(config, "bodyPresent") is True
    assert agent._config_body({"method": "GET", "path": "/x"}) is None
    assert agent._config_flag({"method": "GET", "path": "/x"}, "bodyPresent") is False
