"""End-to-end verification of the DeepSeek client (Phase 8.3 Step 1).

No network, no key, no bill.  httpx's own `MockTransport` answers every request,
so each failure the provider can produce -- an expired key, a rate limit, a 500,
a timeout, an empty answer, JSON that is not an object -- is exercised against the
real client rather than described in a comment.

What is *not* here: any call to the real API.  That is
`scripts/verify_deepseek_analyze.py`, and it skips when there is no key.

Every check runs; a failure is reported and the run continues.  Exit code is the
number of failures.

    python scripts/verify_llm_client.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402
from backend.services import llm  # noqa: E402

__all__ = ["main"]

KEY = "sk-verify-secret-key-value"
BASE = "https://api.example.invalid"
MODEL = "deepseek-verify"

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


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
# A stubbed provider
# --------------------------------------------------------------------------- #


def config(**overrides: Any) -> llm.DeepSeekConfig:
    values: dict[str, Any] = {
        "api_key": KEY,
        "base_url": BASE,
        "model": MODEL,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)

    return llm.DeepSeekConfig(**values)


def completion(text: str, *, status: str = "completed", **extra: Any) -> dict[str, Any]:
    """A Responses API answer carrying `text` as the assistant's output."""
    body: dict[str, Any] = {
        "id": "resp_verify_1",
        "model": MODEL,
        "status": status,
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    }
    body.update(extra)

    return body


def stub(
    handler: Any,
) -> tuple[llm.DeepSeekLLMClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        return handler(request)

    return llm.DeepSeekLLMClient(config(), transport=httpx.MockTransport(wrapped)), seen


async def call(client: llm.DeepSeekLLMClient) -> llm.LLMResult:
    return await client.complete_json(
        instructions="the instructions",
        turns=["the task", "the data"],
        schema=SCHEMA,
        schema_name="verify",
    )


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


async def check_request(report: Report) -> None:
    """The call is the protocol: path, model, roles, and a strict JSON schema."""
    client, seen = stub(lambda request: httpx.Response(200, json=completion('{"ok": true}')))

    await call(client)

    report.equal("one request was made", len(seen), 1)
    request = seen[0]
    report.equal("it went to the responses path", request.url.path, "/responses")
    report.equal("with the configured model", json.loads(request.content)["model"], MODEL)
    report.equal(
        "the key travelled as a bearer header",
        request.headers.get("authorization"),
        "Bearer " + KEY,
    )

    body = json.loads(request.content)
    roles = [item["role"] for item in body["input"]]
    report.equal("instructions first, then the turns", roles, ["system", "user", "user"])
    report.equal(
        "the task is its own turn",
        body["input"][1]["content"][0]["text"],
        "the task",
    )
    report.equal(
        "the data is its own turn",
        body["input"][2]["content"][0]["text"],
        "the data",
    )

    shape = body["text"]["format"]
    report.equal("the answer must be a named JSON schema", shape["type"], "json_schema")
    report.equal("schema name", shape["name"], "verify")
    report.check("the schema is sent strict", shape["strict"] is True)
    report.equal("the schema is the one asked for", shape["schema"], SCHEMA)


def _objects(schema: Any) -> list[Any]:
    """Every object schema reachable from the root, references followed."""
    found: list[Any] = []
    definitions = {}
    for key in ("$defs", "definitions"):
        if isinstance(schema.get(key), dict):
            definitions.update(schema[key])
    seen: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if depth > 32:
            return
        if isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
            return
        if not isinstance(node, Mapping):
            return

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            name = reference.rsplit("/", 1)[-1]
            if name not in seen and name in definitions:
                seen.add(name)
                visit(definitions[name], depth + 1)

        if isinstance(node.get("properties"), Mapping) or node.get("type") == "object":
            found.append(node)

        for value in node.values():
            if isinstance(value, (Mapping, list)):
                visit(value, depth + 1)

    visit(schema, 0)

    return found


def _open_dictionaries(schema: Any) -> list[str]:
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

    visit(schema, "schema", 0)

    return found


async def check_request_schema(report: Report) -> None:
    """What is sent is the provider's dialect, whatever the caller handed over.

    The caller passes the *contract's* schema -- optional fields, a localized-text
    union, a typed dictionary inside it -- and the client is the last thing
    between that and a provider which rejects all three.  Checking the payload
    rather than the function is the point: this is the byte string DeepSeek saw
    when it answered 400.
    """
    from backend.schemas.agent import AgentUnderstandingResponse

    contract = AgentUnderstandingResponse.model_json_schema()
    snapshot = copy.deepcopy(contract)
    client, seen = stub(lambda request: httpx.Response(200, json=completion('{"ok": true}')))

    await client.complete_json(
        instructions="the instructions",
        turns=["the task", "the data"],
        schema=contract,
        schema_name="api_understanding",
    )

    sent = json.loads(seen[0].content)["text"]["format"]["schema"]
    found = _objects(sent)

    report.check(
        "the sent schema describes the whole contract",
        len(found) >= 9,
        len(found),
    )
    report.check(
        "every object it sends is fully required",
        all(
            sorted(node.get("required") or []) == sorted(node.get("properties") or {})
            for node in found
        ),
    )
    report.check(
        "every object it sends is closed",
        all(node.get("additionalProperties") is False for node in found),
    )
    report.check(
        "it sends no dictionary with typed values",
        not _open_dictionaries(sent),
        _open_dictionaries(sent)[:4],
    )
    report.check(
        "and it does not mutate the caller's schema",
        contract == snapshot,
    )


async def check_success(report: Report) -> None:
    """The happy path: content, model, usage and the provider's request id."""
    client, _ = stub(lambda request: httpx.Response(200, json=completion('{"ok": true}')))

    result = await call(client)

    report.equal("the content is the parsed object", result.content, {"ok": True})
    report.equal("the model is reported", result.model, MODEL)
    report.equal("the status is reported", result.status, "completed")
    report.equal("the request id is reported", result.request_id, "resp_verify_1")
    report.equal(
        "usage is reported",
        dict(result.usage or {}),
        {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )


async def check_convenience_field(report: Report) -> None:
    """A deployment that also exposes a flat answer text is still readable."""
    client, _ = stub(
        lambda request: httpx.Response(
            200,
            json={"status": "completed", "output": [], "output_text": '{"ok": false}'},
        )
    )

    result = await call(client)

    report.equal("the flat answer is used when the list is empty", result.content, {"ok": False})


async def check_http_failures(report: Report) -> None:
    """401, 429 and 500 are three statuses and one safe sentence."""
    for status in (401, 429, 500):
        client, _ = stub(
            lambda request, status=status: httpx.Response(
                status, text="{" + KEY + "} refused"
            )
        )

        try:
            await call(client)
            report.check(f"HTTP {status} is refused", False, "no error raised")
            continue
        except llm.LLMProtocolError as error:
            report.equal(f"HTTP {status} raises a protocol error", error.status, status)
            report.check(
                f"HTTP {status} does not leak the key",
                KEY not in str(error) and KEY not in error.detail,
                error.detail,
            )
            report.check(
                f"HTTP {status} keeps a bounded, readable reason",
                str(status) in error.detail and len(error.detail) <= 260,
                error.detail,
            )


async def check_timeout(report: Report) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("the model is slow", request=request)

    client, _ = stub(handler)

    try:
        await call(client)
        report.check("a timeout is refused", False, "no error raised")
    except llm.LLMProtocolError as error:
        report.check("a timeout raises a protocol error", "did not answer" in error.detail, error.detail)
        report.check("a timeout carries no status", error.status is None)


async def check_bad_answers(report: Report) -> None:
    """Empty, truncated, non-JSON and non-object answers are four failures."""
    cases: list[tuple[str, dict[str, Any], type[llm.LLMError]]] = [
        (
            "an answer with no text",
            {"status": "completed", "output": [{"type": "message", "content": []}]},
            llm.LLMOutputInvalid,
        ),
        ("an incomplete answer", completion('{"ok": true}', status="incomplete"), llm.LLMOutputInvalid),
        ("an answer in a failed state", completion('{"ok": true}', status="failed"), llm.LLMProtocolError),
        (
            "an answer that is not JSON",
            completion("I think the API has three endpoints."),
            llm.LLMOutputInvalid,
        ),
        ("an answer that is a JSON array", completion("[1, 2, 3]"), llm.LLMOutputInvalid),
    ]

    for label, body, expected in cases:
        client, _ = stub(lambda request, body=body: httpx.Response(200, json=body))

        try:
            await call(client)
            report.check(f"{label} is refused", False, "no error raised")
        except llm.LLMError as error:
            report.check(f"{label} is refused", isinstance(error, expected), type(error).__name__)

    client, _ = stub(lambda request: httpx.Response(200, text="<html>not json</html>"))

    try:
        await call(client)
        report.check("a non-JSON body is refused", False, "no error raised")
    except llm.LLMOutputInvalid as error:
        report.check("a non-JSON body is refused", True)
        report.check("a non-JSON body is quoted only after redaction", KEY not in error.detail)


def check_configuration(report: Report) -> None:
    """The key, the base URL and the model come from the environment, safely."""
    saved = dict(os.environ)

    try:
        os.environ.pop(llm.API_KEY_ENV, None)
        try:
            llm.deepseek_config()
            report.check("a missing key is refused", False, "no error raised")
        except llm.LLMUnavailable as error:
            report.check("a missing key is refused", llm.API_KEY_ENV in error.detail)

        os.environ[llm.API_KEY_ENV] = KEY
        os.environ.pop(llm.BASE_URL_ENV, None)
        os.environ.pop(llm.MODEL_ENV, None)
        defaults = llm.deepseek_config()
        report.equal("the documented base URL is the default", defaults.base_url, llm.DEFAULT_BASE_URL)
        report.equal("the documented model is the default", defaults.model, llm.DEFAULT_MODEL)

        os.environ[llm.BASE_URL_ENV] = "https://gateway.example/v1/"
        os.environ[llm.MODEL_ENV] = "some-other-model"
        overridden = llm.deepseek_config()
        report.equal("the base URL can be overridden", overridden.base_url, "https://gateway.example/v1")
        report.equal(
            "and it keeps its version prefix",
            overridden.responses_url,
            "https://gateway.example/v1/responses",
        )
        report.equal("the model can be overridden", overridden.model, "some-other-model")

        os.environ[llm.BASE_URL_ENV] = "http://gateway.example"
        try:
            llm.deepseek_config()
            report.check("a plain-http base is refused", False, "no error raised")
        except llm.LLMUnavailable:
            report.check("a plain-http base is refused", True)

        os.environ[llm.BASE_URL_ENV] = "http://127.0.0.1:8080"
        loopback = llm.deepseek_config()
        report.equal("loopback is allowed, for a local double", loopback.base_url, "http://127.0.0.1:8080")
    finally:
        os.environ.clear()
        os.environ.update(saved)

    report.check(
        "the config never prints the key",
        KEY not in repr(config()) and "redacted" in repr(config()),
        repr(config()),
    )


async def main() -> int:
    report = Report()

    print("verifying the DeepSeek client\n")

    await check_request(report)
    await check_request_schema(report)
    await check_success(report)
    await check_convenience_field(report)
    await check_http_failures(report)
    await check_timeout(report)
    await check_bad_answers(report)
    check_configuration(report)

    print(f"\n{report.passed} passed, {len(report.failures)} failed")
    for failure in report.failures:
        print(f"  - {failure}")

    return len(report.failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
