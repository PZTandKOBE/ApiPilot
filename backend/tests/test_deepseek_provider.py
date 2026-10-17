"""The live DeepSeek provider path: what only a real model call can prove.

Two kinds of test live here, and the split matters.

**Failure paths run by default.**  They drive the real client through httpx
``MockTransport``, so a missing key, a provider error, a timeout, an unparseable
body and a half-finished answer are all covered without a network, a key or a
bill.  A regression that turned one of those into a "successful" analysis would
fail here.

**The live tests are off unless asked for.**  They are skipped unless
``RUN_DEEPSEEK_INTEGRATION=1`` *and* ``DEEPSEEK_API_KEY`` is present, because
they spend the account balance and depend on the provider being reachable --
neither of which belongs in a routine regression run.  They assert structure
(shape, contract validity, provenance), never wording: the model is not required
to say the same thing twice.

This module never touches a database.  It needs none: both stages under test are
pure functions over a parsed document plus one model call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx
import pytest

from backend.services import agent_analyzer, agent_plan
from backend.services.agent_plan import PlanPipelineError
from backend.services.llm import (
    DeepSeekConfig,
    DeepSeekLLMClient,
    LLMError,
    deepseek_config,
)

# The key is read from the process environment only, exactly as the product does.
# Loading .env here matches how the app is run locally; it never overrides a real
# environment variable, and nothing from it is ever printed.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.is_file():
    from dotenv import load_dotenv

    load_dotenv(_ENV_FILE)

INTEGRATION_ENV = "RUN_DEEPSEEK_INTEGRATION"


def integration_enabled() -> bool:
    """True only when the run explicitly asks for live calls."""
    return (os.getenv(INTEGRATION_ENV) or "").strip().lower() in ("1", "true", "yes")


def live_reason() -> str:
    if not integration_enabled():
        return f"live provider tests are opt-in: set {INTEGRATION_ENV}=1 to spend a real call"
    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return "DEEPSEEK_API_KEY is not set"
    return ""


requires_live_provider = pytest.mark.skipif(
    bool(live_reason()),
    reason=live_reason() or "live provider disabled",
)

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------- #
# A synthetic document: an orders API, small enough to stay cheap to send.
# --------------------------------------------------------------------------- #

DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0", "description": "A tiny orders service."},
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearerAuth": []}],
    "paths": {
        "/auth/token": {
            "post": {
                "tags": ["auth"],
                "summary": "Exchange credentials for a bearer token",
                "security": [],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["username", "password"],
                                "properties": {
                                    "username": {"type": "string"},
                                    "password": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "a token",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["token"],
                                    "properties": {"token": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/orders/{orderId}": {
            "get": {
                "tags": ["orders"],
                "summary": "Read one order",
                "parameters": [
                    {
                        "name": "orderId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "the order",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "status", "total"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "status": {"type": "string"},
                                        "total": {"type": "number"},
                                    },
                                }
                            }
                        },
                    },
                    "404": {"description": "no such order"},
                },
            }
        },
        "/orders": {
            "post": {
                "tags": ["orders"],
                "summary": "Create an order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["sku", "quantity"],
                                "properties": {
                                    "sku": {"type": "string"},
                                    "quantity": {"type": "integer"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "created",
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
    },
}

TASK = (
    "Analyse the orders API: its parameters, request bodies and success responses. "
    "Then design a test plan that covers reading one order and creating an order, "
    "with assertions on the HTTP status or on a response field."
)


def _parsed_spec():
    return agent_plan.parse_document(
        agent_plan.decode_document(json.dumps(DOCUMENT)),
        project_id="prj_phase91",
        spec_id="spec_phase91",
        slug="orders-phase91",
        filename="orders.json",
        source="upload",
    )


# --------------------------------------------------------------------------- #
# Failure paths -- always on, no network
# --------------------------------------------------------------------------- #


def _client(handler) -> DeepSeekLLMClient:
    """The real client, with a transport that answers instead of the network."""
    return DeepSeekLLMClient(_fake_config(), transport=httpx.MockTransport(handler))


def _fake_config() -> DeepSeekConfig:
    """A config that never needs the real key, for the transport-driven tests."""
    return DeepSeekConfig(api_key="not-a-real-key", base_url="https://api.deepseek.com")


async def _analyze_with(client) -> Any:
    return await agent_analyzer.analyze_with_model(
        _parsed_spec(), task=TASK, document=DOCUMENT, client=client
    )


async def test_failure_provider_error_is_a_pipeline_failure_not_a_result() -> None:
    """A 500 from the provider must not become an understanding."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream is unwell"}})

    with pytest.raises(PlanPipelineError) as caught:
        await _analyze_with(_client(handler))

    assert caught.value.code == "analyze-failed"
    assert "500" in str(caught.value.detail)


async def test_failure_unauthorized_is_reported_with_its_status() -> None:
    """A rejected key is a configuration failure, not an empty analysis."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(PlanPipelineError) as caught:
        await _analyze_with(_client(handler))

    assert "401" in str(caught.value.detail)


async def test_failure_unparseable_body_is_rejected() -> None:
    """A 200 whose body is not JSON is not an answer."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json at all</html>")

    with pytest.raises(PlanPipelineError):
        await _analyze_with(_client(handler))


async def test_failure_incomplete_answer_is_rejected() -> None:
    """A half-written answer must not be parsed as if it were whole."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "{\"endpoints\": ["}],
                    }
                ],
            },
        )

    with pytest.raises(PlanPipelineError):
        await _analyze_with(_client(handler))


async def test_failure_timeout_is_reported() -> None:
    """A provider that never answers becomes a timeout, not a hang or a success."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    with pytest.raises(PlanPipelineError):
        await _analyze_with(_client(handler))


def test_failure_wellformed_but_invalid_understanding_is_refused() -> None:
    """Well-formed JSON that breaks the contract is refused on the way in.

    This is the failure a provider error cannot cover: the call succeeded and the
    object parses, but its facts do not hold together.  The domain layer has to
    reject it, or a plan would be built on an invented endpoint.
    """
    parsed = _parsed_spec()
    # Schema-valid on purpose: every required field is present and typed, so the
    # response model accepts it and the refusal can only come from the domain
    # layer underneath.  The invented endpoint is the only thing wrong with it.
    payload = {
        "specId": parsed.spec.id,
        "analyzedAt": "2026-10-16T00:00:00Z",
        "authentication": {"scheme": "none", "protectedEndpointCount": 0},
        "endpoints": [
            {
                "id": "get__not_a_real_path",
                "method": "GET",
                "path": "/not/a/real/path",
                "resourceId": "res_invented",
                "summary": {"text": "invented"},
                "requiresAuth": False,
                "pathParams": [],
                "requiredBodyProps": [],
                "constrainedBodyProps": [],
                "responseStatuses": [200],
                "responseProps": [],
            }
        ],
        "resources": [],
        "dependencies": [],
        "risks": [],
        "findings": [],
    }

    # The response model must accept it, or this test would be proving the wrong
    # layer: the point is that a well-formed object can still be refused.
    agent_analyzer.AgentUnderstandingResponse.model_validate(payload)

    with pytest.raises(PlanPipelineError) as caught:
        agent_analyzer.understanding_from_payload(payload, parsed=parsed)

    assert caught.value.code == "analyze-failed"
    assert "refused" in str(caught.value.detail), (
        "the refusal should come from the domain layer, not the schema: "
        f"{caught.value.detail}"
    )
    assert "was not in the document" in str(caught.value.detail)


def test_missing_key_is_a_configuration_failure_not_an_empty_analysis() -> None:
    """With no key, the stage refuses before any request is made."""
    saved = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        with pytest.raises(LLMError) as caught:
            agent_analyzer.build_client()
        assert "DEEPSEEK_API_KEY" in str(caught.value)
    finally:
        if saved is not None:
            os.environ["DEEPSEEK_API_KEY"] = saved


def test_plan_never_arrives_approved() -> None:
    """The model designs; the runtime decides status.  A design cannot approve.

    PlanDesign has no status field at all, so this is structural: it holds for any
    answer the model can give.
    """
    assert "status" not in agent_analyzer.PlanDesign.model_fields
    assert "approved_at" not in agent_analyzer.PlanDesign.model_fields
    assert "id" not in agent_analyzer.PlanDesign.model_fields


def test_the_planner_is_configured_for_the_model_by_default() -> None:
    """The live plan test below must be exercising the model, not the rule engine."""
    saved = os.environ.pop("AGENT_PLANNER", None)
    try:
        assert agent_analyzer.selected_planner() == agent_analyzer.DEEPSEEK
    finally:
        if saved is not None:
            os.environ["AGENT_PLANNER"] = saved


# --------------------------------------------------------------------------- #
# Live provider -- opt-in, spends a real call
# --------------------------------------------------------------------------- #


@requires_live_provider
async def test_live_analysis_is_structured_and_matches_the_document() -> None:
    """One real analyze call: the answer is a contract-valid understanding.

    Assertions are about shape and provenance, not phrasing: the endpoints the
    model reports must be endpoints the document actually has, which is what the
    domain validator enforces and what this test re-checks from the outside.
    """
    parsed = _parsed_spec()
    from backend.services.llm import DeepSeekLLMClient as RealClient

    client = RealClient(deepseek_config())
    outcome = await agent_analyzer.analyze_with_model(
        parsed, task=TASK, document=DOCUMENT, client=client
    )

    assert outcome.provider == agent_analyzer.DEEPSEEK
    assert outcome.model
    assert outcome.prompt == agent_analyzer.PROMPT_NAME

    understanding = outcome.understanding
    assert understanding.endpoints, "a real analysis returned no endpoints"
    assert understanding.risks, "a real analysis returned no risks"

    real = {(e.method.upper(), e.path) for e in parsed.endpoints}
    for reported in understanding.endpoints:
        assert (reported.method.upper(), reported.path) in real, (
            f"the analysis invented an endpoint: {reported.method} {reported.path}"
        )
    assert understanding.risks[0].level in ("low", "medium", "high")


@requires_live_provider
async def test_live_plan_is_valid_and_never_approved() -> None:
    """One real plan call: the model designs, the runtime completes and validates.

    The understanding is computed locally by the rule engine so the single paid
    call is the one under test.
    """
    parsed = _parsed_spec()
    understanding = agent_plan.analyze(parsed)
    from backend.services.llm import DeepSeekLLMClient as RealClient

    client = RealClient(deepseek_config())
    outcome = await agent_analyzer.plan_with_model(
        parsed, understanding, task=TASK, client=client
    )

    assert outcome.provider == agent_analyzer.DEEPSEEK
    assert outcome.design is not None, "the design was not kept for the audit"

    plan = outcome.plan
    assert plan.status == "draft", "the model must never hand back an approved plan"
    assert plan.approved_at is None
    assert plan.scenarios, "a real plan had no scenarios"
    assert plan.scenarios[0].id, "the runtime did not give the scenario its contract key"

    steps = [step for scenario in plan.scenarios for step in scenario.steps]
    assertions = [a for scenario in plan.scenarios for a in scenario.assertions]
    assert steps, "a real plan had no steps"
    assert assertions, "a real plan had no assertions"
    assert any(a.kind in ("status", "field", "header") for a in assertions)

    # The plan has to survive the same validation the pipeline applies before
    # anything downstream is allowed to see it.
    issues = agent_analyzer.plan_design_issues(outcome.design, parsed)
    assert issues == [], f"the completed plan failed its own validator: {issues}"
