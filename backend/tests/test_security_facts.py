"""OpenAPI security declarations become facts, and the planner respects them.

The parser used to keep only a boolean: an operation that inherited global auth
and one that explicitly made itself public both looked like "no auth" once the
boolean was false.  These tests pin the declaration through to the model-facing
facts and to the scenarios the deterministic planner actually emits.
"""

from __future__ import annotations

import json
from typing import Any

from backend.services import agent_analyzer, agent_plan


def _document(
    security: list[dict[str, Any]] | None,
    *,
    me_security: list[dict[str, Any]] | None = None,
    login_security: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Orders API", "version": "1.0.0"},
        "components": {
            "securitySchemes": {
                "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
                "Basic": {"type": "http", "scheme": "basic"},
            }
        },
        "paths": {
            "/login": {
                "post": {
                    "summary": "Log in",
                    "responses": {
                        "200": {
                            "description": "token",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"token": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/me": {
                "get": {
                    "summary": "Current identity",
                    "responses": {"200": {"description": "identity"}},
                }
            },
        },
    }

    if security is not None:
        document["security"] = security
    if login_security is not None:
        document["paths"]["/login"]["post"]["security"] = login_security
    if me_security is not None:
        document["paths"]["/me"]["get"]["security"] = me_security

    return document


def _parse(document: dict[str, Any]) -> agent_plan.ParsedSpec:
    return agent_plan.parse_document(
        document,
        project_id="prj_security",
        spec_id="spec_security",
        slug="security",
        filename="security.json",
        source="upload",
    )


def _understanding(parsed: agent_plan.ParsedSpec) -> agent_plan.Understanding:
    return agent_plan.Understanding(
        spec_id=parsed.spec.id,
        endpoints=parsed.endpoints,
        resources=parsed.resources,
        authentication=parsed.authentication,
        dependencies=(),
        risks=(),
        findings=(),
        analyzed_at="2026-10-17T00:00:00Z",
    )


def _endpoint(parsed: agent_plan.ParsedSpec, method: str, path: str):
    return next(
        item for item in parsed.endpoints if item.method == method and item.path == path
    )


def test_global_security_is_inherited_by_an_operation() -> None:
    parsed = _parse(_document([{"ApiKey": []}], login_security=[]))
    me = _endpoint(parsed, "GET", "/me")

    assert me.requires_auth is True
    assert me.security_declared is True
    assert me.security_schemes == ("ApiKey",)
    assert me.security_optional is False


def test_operation_security_overrides_global_security() -> None:
    parsed = _parse(
        _document([{"ApiKey": []}], login_security=[], me_security=[{"Basic": []}])
    )
    me = _endpoint(parsed, "GET", "/me")

    assert me.requires_auth is True
    assert me.security_schemes == ("Basic",)
    assert "ApiKey" not in me.security_schemes


def test_empty_operation_security_is_explicitly_public() -> None:
    parsed = _parse(_document([{"ApiKey": []}], login_security=[], me_security=[]))
    me = _endpoint(parsed, "GET", "/me")

    assert me.requires_auth is False
    assert me.security_declared is True
    assert me.security_schemes == ()
    assert me.security_optional is False


def test_no_security_declaration_is_not_the_same_as_public_override() -> None:
    parsed = _parse(_document(None))
    me = _endpoint(parsed, "GET", "/me")

    assert me.requires_auth is False
    assert me.security_declared is False
    assert me.security_schemes == ()


def test_an_empty_requirement_makes_authentication_optional() -> None:
    parsed = _parse(_document([{}, {"ApiKey": []}], login_security=[]))
    me = _endpoint(parsed, "GET", "/me")

    assert me.requires_auth is False
    assert me.security_declared is True
    assert me.security_schemes == ("ApiKey",)
    assert me.security_optional is True


def test_specification_facts_carry_the_security_declaration() -> None:
    parsed = _parse(_document([{"ApiKey": []}], login_security=[]))
    facts = json.loads(agent_analyzer.specification_facts(parsed))

    me = next(item for item in facts["endpoints"] if item["path"] == "/me")
    assert me["requiresAuth"] is True
    assert me["securityDeclared"] is True
    assert me["securitySchemes"] == ["ApiKey"]
    assert me["securityOptional"] is False


def test_a_protected_identity_endpoint_gets_the_authentication_scenario() -> None:
    parsed = _parse(_document([{"ApiKey": []}], login_security=[]))
    plan = agent_plan.generate_plan(_understanding(parsed), parsed.spec)

    scenarios = {scenario.id: scenario for scenario in plan.scenarios}
    assert "scenario_authentication" in scenarios

    authentication = scenarios["scenario_authentication"]
    requests = [step for step in authentication.steps if step.kind == "request"]
    assert [step.path for step in requests] == ["/login", "/me"]
    assert requests[1].consumes == ["token"]


def test_a_public_identity_endpoint_does_not_get_the_authentication_scenario() -> None:
    parsed = _parse(
        _document([{"ApiKey": []}], login_security=[], me_security=[])
    )
    plan = agent_plan.generate_plan(_understanding(parsed), parsed.spec)

    assert "scenario_authentication" not in {scenario.id for scenario in plan.scenarios}


def test_a_public_api_does_not_invent_an_unauthenticated_scenario() -> None:
    document = _document(None)
    document["paths"] = {
        "/orders": {
            "get": {
                "summary": "List orders",
                "responses": {"200": {"description": "orders"}},
            }
        }
    }
    parsed = _parse(document)
    plan = agent_plan.generate_plan(_understanding(parsed), parsed.spec)

    names = {scenario.id for scenario in plan.scenarios}
    assert names == {"scenario_smoke_ep_get_orders"}
    assert "scenario_authentication" not in names
