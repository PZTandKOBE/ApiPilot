"""Verification of the DeepSeek strict-schema adapter (Phase 8.3 Step 1-A).

The provider accepts only a *closed* dialect of JSON Schema: every object must
list all of its properties as required and forbid additional ones.  Our contract
is a Pydantic model with optional fields and a localized-text union, so the
schema it generates is rejected with

    HTTP 400  Required properties must match all properties in the object

The adapter in `services/llm.py` raises that schema to the provider's dialect
without touching the model.  This script proves the three things that matter:

* the **provider schema** obeys the dialect, everywhere -- including nested
  objects, arrays of objects, union branches and everything reached through a
  reference (the domain's nested models live in `$defs` and are otherwise
  never visited);
* the **domain schema** is untouched, and the domain model still accepts
  everything it accepted before (a `{key, params}` message included): the
  adapter restricts what the *provider* may emit, not what the contract means;
* the transformation loses nothing it is allowed to keep, and refuses loudly
  what it cannot express.

No network, no key, no cost.  Every check runs; exit code is the number of
failures.

    python scripts/verify_deepseek_schema.py
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend.schemas.agent import AgentUnderstandingResponse  # noqa: E402
from backend.services.llm import LLMError, strict_schema  # noqa: E402

__all__ = ["main"]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    def check(self, label: str, condition: bool, detail: Any = None) -> None:
        if condition:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail is not None else ""))

    def equal(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected {expected!r}, got {actual!r}")


# --------------------------------------------------------------------------- #
# Walking a schema the way a provider would
# --------------------------------------------------------------------------- #


def definitions_of(root: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for key in ("$defs", "definitions"):
        section = root.get(key)
        if isinstance(section, dict):
            merged.update(section)

    return merged


def objects(root: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Every object schema reachable from the root, references followed once."""
    found: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    definitions = definitions_of(root)

    def visit(node: Any, path: str, depth: int) -> None:
        if depth > 32:
            return

        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]", depth + 1)
            return

        if not isinstance(node, Mapping):
            return

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            name = reference.rsplit("/", 1)[-1]
            if name not in seen and name in definitions:
                seen.add(name)
                visit(definitions[name], f"$defs/{name}", depth + 1)

        if isinstance(node.get("properties"), Mapping) or node.get("type") == "object":
            found.append((path, node))

        for key, value in node.items():
            if key in ("$defs", "definitions"):
                continue
            if isinstance(value, (Mapping, list)):
                visit(value, f"{path}/{key}", depth + 1)

    visit(root, "schema", 0)

    return found


def open_dictionaries(root: Mapping[str, Any]) -> list[str]:
    """Paths whose `additionalProperties` is itself a schema."""
    found: list[str] = []

    def visit(node: Any, path: str, depth: int) -> None:
        if depth > 32:
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]", depth + 1)
            return
        if not isinstance(node, Mapping):
            return

        if isinstance(node.get("additionalProperties"), Mapping):
            found.append(path)

        for key, value in node.items():
            if isinstance(value, (Mapping, list)):
                visit(value, f"{path}/{key}", depth + 1)

    visit(root, "schema", 0)

    return found


def property_names(root: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()

    for _, node in objects(root):
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            names.update(properties)

    return names


def enums(root: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if depth > 32:
            return
        if isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
            return
        if not isinstance(node, Mapping):
            return

        values = node.get("enum")
        if isinstance(values, list):
            found.update(json.dumps(value) for value in values)

        for value in node.values():
            if isinstance(value, (Mapping, list)):
                visit(value, depth + 1)

    visit(root, 0)

    return found


# --------------------------------------------------------------------------- #
# Synthetic schemas: the cases the domain schema does not happen to contain
# --------------------------------------------------------------------------- #

SYNTHETIC: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plain": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "string"}, "deep": {"$ref": "#/$defs/Deep"}},
            },
        },
        "union": {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "null"},
            ]
        },
        "choice": {
            "anyOf": [
                {"$ref": "#/$defs/Closed"},
                {"$ref": "#/$defs/Open"},
                {"type": "null"},
            ]
        },
    },
    "$defs": {
        "Closed": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        "Open": {
            "type": "object",
            "properties": {"m": {"type": "object", "additionalProperties": {"type": "string"}}},
        },
        "Deep": {
            "type": "object",
            "properties": {
                "leaf": {"type": "object", "properties": {"k": {"type": "integer"}}}
            },
        },
    },
}

UNION_REQUIRED_ELSEWHERE: dict[str, Any] = {
    "type": "object",
    "properties": {"m": {"type": "object", "additionalProperties": {"type": "string"}}},
}


def find(root: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = root

    for step in path:
        if isinstance(node, list):
            node = node[int(step)]
        elif isinstance(node, Mapping):
            node = node[step]
        else:
            return None

    return node


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def check_domain_untouched(report: Report, domain: Mapping[str, Any]) -> None:
    """Test 7: the contract is the model's, and only the provider sees a variant."""
    snapshot = copy.deepcopy(domain)
    before = json.dumps(domain, sort_keys=True)

    strict_schema(domain)

    report.equal(
        "7: the normaliser does not touch the schema it is given",
        json.dumps(domain, sort_keys=True),
        before,
    )
    report.equal(
        "7: the model still generates the schema it generated before",
        AgentUnderstandingResponse.model_json_schema(),
        snapshot,
    )

    # And the contract still accepts what it always accepted: a server-keyed
    # localized message with parameters.  The provider is restricted; the
    # contract is not.
    keyed = AgentUnderstandingResponse.model_validate(
        {
            "specId": "spec_x",
            "endpoints": [],
            "resources": [],
            "authentication": {
                "scheme": "none",
                "schemeName": None,
                "headerName": None,
                "tokenSourceEndpointId": None,
                "tokenField": None,
                "protectedEndpointCount": 0,
            },
            "dependencies": [],
            "risks": [],
            "findings": [
                {
                    "id": "finding_1",
                    "action": {"key": "console.aiTest.action.read", "params": {"n": 1}},
                    "decisionSummary": {"text": "text is fine too"},
                    "result": "succeeded",
                    "evidence": [{"label": {"text": "endpoints"}, "value": "0"}],
                    "at": "2026-01-01T00:00:00Z",
                }
            ],
            "analyzedAt": "2026-01-01T00:00:00Z",
        }
    )
    report.equal(
        "7: the domain still accepts a key/params localized message",
        keyed.findings[0].action.model_dump(),
        {"key": "console.aiTest.action.read", "params": {"n": 1}},
    )


def check_provider_schema(report: Report, strict: Mapping[str, Any]) -> None:
    found = objects(strict)

    # More objects than top-level properties can only mean the walk followed the
    # references the domain's nested models live behind.
    report.check(
        "1: the walk reaches the nested models (it follows references)",
        len(found) > len(strict.get("properties") or {}) and len(found) >= 9,
        [path for path, _ in found][:12],
    )

    incomplete = [
        (path, list(node.get("required") or []), sorted(node.get("properties") or {}))
        for path, node in found
        if sorted(node.get("required") or []) != sorted(node.get("properties") or {})
    ]
    report.check(
        "1: every object requires all of its properties",
        not incomplete,
        incomplete[:4],
    )

    open_objects = [
        path for path, node in found if node.get("additionalProperties") is not False
    ]
    report.check(
        "2: every object forbids additional properties",
        not open_objects,
        open_objects[:4],
    )

    open_maps = open_dictionaries(strict)
    report.check("3: no dictionary with typed values survives", not open_maps, open_maps[:4])

    names = property_names(strict)
    report.check(
        "3: the open params property is gone with the branch that held it",
        "params" not in names,
        sorted(names),
    )
    report.check(
        "3: LocalizedMessage itself is gone from the provider schema",
        "LocalizedMessage" not in (strict.get("$defs") or {}),
        sorted((strict.get("$defs") or {}).keys()),
    )


def check_no_information_lost(
    report: Report, domain: Mapping[str, Any], strict: Mapping[str, Any]
) -> None:
    domain_names = property_names(domain)
    strict_names = property_names(strict)

    # The dropped branch took both of its properties with it: the provider is
    # offered the literal form of a localized message, and only that.
    report.check(
        "the dropped union branch and its properties are the only loss",
        domain_names - strict_names == {"key", "params"},
        sorted(domain_names - strict_names),
    )
    report.check(
        "no property was invented",
        strict_names - domain_names == set(),
        sorted(strict_names - domain_names),
    )
    report.equal("enum values survive", enums(strict), enums(domain))
    report.equal(
        "an array of objects still describes its items",
        find(strict, ("$defs", "AgentEndpointResponse", "properties", "responseProps", "items")),
        {"type": "string"},
    )
    report.check(
        "an array field is still an array of its model",
        find(strict, ("properties", "endpoints", "type")) == "array"
        and find(strict, ("properties", "endpoints", "items", "$ref"))
        == "#/$defs/AgentEndpointResponse",
        find(strict, ("properties", "endpoints")),
    )
    report.equal(
        "a localized field is now only its literal form",
        find(strict, ("$defs", "AgentEndpointResponse", "properties", "summary", "$ref")),
        "#/$defs/LiteralMessage",
    )
    literal = find(strict, ("$defs", "LiteralMessage")) or {}
    report.check(
        "and that literal form is closed over its single property",
        list(literal.get("properties") or {}) == ["text"]
        and literal.get("required") == ["text"]
        and literal.get("additionalProperties") is False
        and literal.get("type") == "object",
        literal,
    )


def check_synthetic(report: Report) -> None:
    """Tests 4, 5 and 6 on shapes the domain schema does not happen to contain."""
    strict = strict_schema(SYNTHETIC)

    report.equal(
        "4: an object reached only through a reference is closed",
        find(strict, ("$defs", "Deep", "required")),
        ["leaf"],
    )
    report.equal(
        "4: and the object inside it too, however deep",
        find(strict, ("$defs", "Deep", "properties", "leaf", "required")),
        ["k"],
    )
    report.equal(
        "5: an object inside an array is closed",
        find(strict, ("properties", "rows", "items", "required")),
        ["n", "deep"],
    )
    report.equal(
        "6: an object inside a union branch is closed",
        find(strict, ("properties", "union", "anyOf", "0", "required")),
        ["a"],
    )
    report.equal(
        "6: a union branch that cannot be expressed is dropped",
        [branch.get("$ref") or branch.get("type") for branch in find(strict, ("properties", "choice", "anyOf"))],
        ["#/$defs/Closed", "null"],
    )
    report.check(
        "6: and its now-unused definition is dropped with it",
        "Open" not in (strict.get("$defs") or {}),
        sorted((strict.get("$defs") or {}).keys()),
    )
    report.equal(
        "6: the branch that stays keeps its own meaning",
        find(strict, ("properties", "choice", "anyOf", "0")),
        {"$ref": "#/$defs/Closed"},
    )

    report.equal("idempotent: normalising twice changes nothing", strict_schema(strict), strict)

    kept = find(strict, ("properties", "plain"))
    report.equal("a plain scalar is left alone", kept, {"type": "string"})

    try:
        strict_schema(UNION_REQUIRED_ELSEWHERE)
        report.check(
            "an unrepresentable object outside a union is refused loudly",
            False,
            "no error raised",
        )
    except LLMError as error:
        report.check(
            "an unrepresentable object outside a union is refused loudly",
            "strict dialect" in error.detail,
            error.detail,
        )


async def check_client_sends_it(report: Report) -> None:
    """The payload the client actually sends carries the normalised schema."""
    import httpx

    from backend.services import llm

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        body = {
            "id": "resp_schema",
            "model": "deepseek-verify",
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}
            ],
        }

        return httpx.Response(200, json=body)

    client = llm.DeepSeekLLMClient(
        llm.DeepSeekConfig(api_key="sk-verify", base_url="https://api.example.invalid"),
        transport=httpx.MockTransport(handler),
    )

    await client.complete_json(
        instructions="i",
        turns=["t"],
        schema=AgentUnderstandingResponse.model_json_schema(),
        schema_name="api_understanding",
    )

    sent = seen["text"]["format"]["schema"]
    found = objects(sent)

    report.check(
        "the request carries a schema with objects in it",
        len(found) >= 9,
        len(found),
    )
    report.check(
        "every object in the request is fully required, with no extras",
        all(
            sorted(node.get("required") or []) == sorted(node.get("properties") or {})
            and node.get("additionalProperties") is False
            for _, node in found
        ),
    )
    report.check(
        "and the request carries no typed dictionary",
        not open_dictionaries(sent),
        open_dictionaries(sent)[:4],
    )
    report.check(
        "the request kept the contract's fields",
        property_names(sent) >= {"specId", "endpoints", "resources", "authentication"},
    )



# --------------------------------------------------------------------------- #
# The plan stage's provider schema
# --------------------------------------------------------------------------- #


def check_plan_schema(report: Report) -> None:
    """The design schema obeys the dialect, and offers nothing the runtime owns.

    The plan stage has a second job here: the model must not be *offered* an id,
    an index, a status or an identity it could fill in wrongly.  A provider
    schema that omits them is the strongest statement that keys are derived
    rather than invented.
    """
    from backend.services import agent_analyzer

    strict = strict_schema(agent_analyzer.PlanDesign.model_json_schema())
    found = objects(strict)

    incomplete = [
        path
        for path, node in found
        if sorted(node.get("required") or []) != sorted(node.get("properties") or {})
    ]
    report.check("plan: every object requires all of its properties", not incomplete, incomplete)
    report.check(
        "plan: every object forbids additional properties",
        all(node.get("additionalProperties") is False for _, node in found),
    )
    report.check(
        "plan: no dictionary with typed values survives",
        not open_dictionaries(strict),
        open_dictionaries(strict)[:4],
    )

    names = property_names(strict)
    report.check(
        "plan: the model is offered no key, index, status or identity to invent",
        not (names & {"id", "index", "status", "source", "generatedAt", "projectId", "specId"}),
        sorted(names),
    )
    report.check(
        "plan: the text fields it is offered are the literal form",
        find(strict, ("$defs", "LiteralMessage")) is not None
        and "LocalizedMessage" not in (strict.get("$defs") or {}),
        sorted((strict.get("$defs") or {}).keys()),
    )

    step = find(strict, ("$defs", "PlanStepDesign", "properties")) or {}
    report.check(
        "plan: a step offers the executor's vocabulary and nothing else",
        sorted(step)
        == ["consumes", "description", "endpointId", "kind", "method", "path", "produces"],
        sorted(step),
    )
    report.check(
        "plan: the step kind is closed to the three the executor runs",
        sorted(find(strict, ("$defs", "PlanStepDesign", "properties", "kind", "enum")) or [])
        == ["assert", "extract", "request"],
        find(strict, ("$defs", "PlanStepDesign", "properties", "kind")),
    )
    report.check(
        "plan: the assertion kind is closed to the three the executor runs",
        sorted(find(strict, ("$defs", "PlanAssertionDesign", "properties", "kind", "enum")) or [])
        == ["field", "header", "status"],
        find(strict, ("$defs", "PlanAssertionDesign", "properties", "kind")),
    )
    report.check(
        "plan: an assertion may name the request it reads",
        "endpointId" in (find(strict, ("$defs", "PlanAssertionDesign", "properties")) or {}),
    )
    report.check(
        "plan: the design has no body, query or schema field to fill in",
        not (names & {"body", "requestBody", "query", "queryParams", "schema", "stepId"}),
        sorted(names),
    )

    renderable = agent_analyzer.PlanDesign.model_validate(
        {
            "name": {"text": "n"},
            "goal": {"text": "g"},
            "riskLevel": "low",
            "scenarios": [
                {
                    "name": {"text": "n"},
                    "description": {"text": "d"},
                    "expected": {"text": "e"},
                    "riskLevel": "low",
                    "steps": [
                        {
                            "kind": "request",
                            "description": {"text": "call"},
                            "endpointId": "ep_x",
                            "method": "GET",
                            "path": "/x",
                        }
                    ],
                    "assertions": [
                        {
                            "kind": "status",
                            "target": "status",
                            "expected": "200",
                            "description": {"text": "ok"},
                            "endpointId": "ep_x",
                        }
                    ],
                }
            ],
        }
    )
    report.check(
        "plan: a design in the schema's own shape validates",
        renderable.scenarios[0].steps[0].kind == "request"
        and renderable.scenarios[0].assertions[0].endpoint_id == "ep_x",
    )


async def main() -> int:
    report = Report()
    domain = AgentUnderstandingResponse.model_json_schema()
    strict = strict_schema(domain)

    print("verifying the DeepSeek strict-schema adapter\n")

    check_domain_untouched(report, domain)
    check_provider_schema(report, strict)
    check_no_information_lost(report, domain, strict)
    check_synthetic(report)
    check_plan_schema(report)
    await check_client_sends_it(report)

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
