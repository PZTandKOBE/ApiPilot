"""The DeepSeek client: one model call, JSON Schema structured output.

Phase 8.3 Step 1.  The first model in this product, and deliberately the
smallest thing that can carry one: an HTTP call over the `httpx` that is
already a dependency, no SDK, no provider hierarchy, no framework.  The pipeline
this serves has exactly one model-shaped hole -- understanding a specification --
and this module fills it and nothing else.

**The wire shape is the Responses API.**  `POST {base}/responses` with the
instructions, the conversation turns, and `text.format` carrying a JSON Schema
the answer must match.  The route is real on `api.deepseek.com` (a request
without a key answers `401` with `Allow: POST`), which is as much as this
environment could verify: the doc site does not resolve from here and there is no
API key in this checkout, so the request and response bodies below follow the
documented shape and are covered by tests against a stubbed transport rather than
by a live call.  A live call is what `scripts/verify_deepseek_analyze.py` is
for; run it where a key exists.

**Nothing here is domain logic.**  The client takes instructions, turns and a
schema, and gives back a JSON object plus its usage.  What the object means --
and whether it is an acceptable understanding -- belongs to
`services/agent_analyzer.py`, which is the layer that must not trust this one.

**The key never travels further than the header.**  It is read from the
environment, sent as `Authorization`, and appears in no log line, no exception
message and no response: every path that could quote a body runs it through
:func:_redact: first, and the tests assert that a key echoed by the server does
not survive into an error.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "MODEL_ENV",
    "DeepSeekConfig",
    "DeepSeekLLMClient",
    "LLMError",
    "LLMOutputInvalid",
    "LLMProtocolError",
    "LLMResult",
    "LLMUnavailable",
    "deepseek_config",
    "normalized_usage",
    "strict_schema",
]

logger = logging.getLogger(__name__)

API_KEY_ENV = "DEEPSEEK_API_KEY"
BASE_URL_ENV = "DEEPSEEK_BASE_URL"
MODEL_ENV = "DEEPSEEK_MODEL"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

# One call, one deadline.  There are no retries in this step on purpose: the
# first question is whether a single request is correct, and a retry hides a
# wrong answer behind a second one.  Queues and backoff are a later phase.
DEFAULT_TIMEOUT_SECONDS = 90.0
_CONNECT_TIMEOUT_SECONDS = 10.0

_RESPONSES_PATH = "/responses"

_REDACTED = "redacted"
_MAX_DETAIL_CHARS = 240

# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


class LLMError(Exception):
    """A model call that did not produce usable JSON.

    `detail` is safe to log and safe to put in a server-side reason: it is
    built from the HTTP status and a redacted excerpt, never from the raw body
    and never from the request headers.
    """

    def __init__(self, detail: str, *, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


class LLMUnavailable(LLMError):
    """The client could not be built: no key, or a base URL that would expose it."""


class LLMProtocolError(LLMError):
    """The call did not answer the way the protocol says it must."""


class LLMOutputInvalid(LLMError):
    """A response arrived, but it was not the JSON object that was asked for."""


def _redact(text: str, secret: str | None) -> str:
    """A bounded, secret-free excerpt for a log line or an error detail.

    Belt and braces rather than decoration: a provider that echoes the credential
    it rejected would otherwise put the key in this process's log.
    """
    if secret:
        text = text.replace(secret, _REDACTED)

    collapsed = " ".join(text.split())

    return collapsed[:_MAX_DETAIL_CHARS]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DeepSeekConfig:
    """Where the model is and what to call it.  The key is part of the value."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def responses_url(self) -> str:
        return self.base_url.rstrip("/") + _RESPONSES_PATH

    def __repr__(self) -> str:  # pragma: no cover - never print the key
        return (
            f"DeepSeekConfig(base_url={self.base_url!r}, model={self.model!r}, "
            f"api_key={_REDACTED!r}, timeout_seconds={self.timeout_seconds!r})"
        )


def _is_loopback(base_url: str) -> bool:
    return httpx.URL(base_url).host in {"127.0.0.1", "::1", "localhost"}


def deepseek_config() -> DeepSeekConfig:
    """Read the configuration from the environment.

    The key has no default and no fallback: without it the analyze stage cannot
    run, and saying so once is better than failing every request with a 401.
    """
    api_key = (os.getenv(API_KEY_ENV) or "").strip()

    if api_key == "":
        raise LLMUnavailable(f"{API_KEY_ENV} is not set")

    base_url = (os.getenv(BASE_URL_ENV) or DEFAULT_BASE_URL).strip().rstrip("/")
    model = (os.getenv(MODEL_ENV) or DEFAULT_MODEL).strip()

    # A key sent over plain HTTP leaves the machine in the clear.  Loopback is
    # the exception: that is a local gateway, and a test double.
    if not base_url.startswith("https://") and not _is_loopback(base_url):
        raise LLMUnavailable(f"{BASE_URL_ENV} must be https (or loopback): {base_url!r}")

    return DeepSeekConfig(api_key=api_key, base_url=base_url, model=model)

# --------------------------------------------------------------------------- #
# One call
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LLMResult:
    """What came back: the JSON object, and the metadata worth keeping."""

    content: dict[str, Any]
    model: str
    usage: Mapping[str, Any] | None = None
    request_id: str | None = None
    status: str | None = None


class DeepSeekLLMClient:
    """One model, one method.

    `transport` exists for tests: httpx's own `MockTransport` drives this
    class through every failure the provider can produce, without a network, a
    key or a bill.
    """

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def model(self) -> str:
        return self._config.model

    def _body(
        self,
        *,
        instructions: str,
        turns: Sequence[str],
        schema: Mapping[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        """The request: instructions once, then one turn per input part.

        The parts stay separate on purpose.  The specification is a turn of its
        own so that it reads as data next to the task, rather than as more
        instructions appended to the system message.
        """
        return {
            "model": self._config.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": instructions}],
                },
                *[
                    {"role": "user", "content": [{"type": "input_text", "text": turn}]}
                    for turn in turns
                ],
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    # Normalised here as well as by the caller: no caller can send
                    # a schema the provider will reject, and normalising an
                    # already-normalised schema is a no-op.
                    "schema": strict_schema(schema),
                    "strict": True,
                }
            },
        }

    async def complete_json(
        self,
        *,
        instructions: str,
        turns: Sequence[str],
        schema: Mapping[str, Any],
        schema_name: str,
    ) -> LLMResult:
        """Ask for one JSON object and return it, or raise.

        Every failure is one of the `LLMError` kinds; none of them carries the
        key, the request headers or the whole body.
        """
        body = self._body(
            instructions=instructions, turns=turns, schema=schema, schema_name=schema_name
        )
        timeout = httpx.Timeout(self._config.timeout_seconds, connect=_CONNECT_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=self._transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    self._config.responses_url,
                    json=body,
                    headers={
                        "Authorization": "Bearer " + self._config.api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise LLMProtocolError(
                f"the model did not answer within {self._config.timeout_seconds:g}s "
                f"({type(exc).__name__})"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProtocolError(f"the model could not be reached ({type(exc).__name__})") from exc

        if response.status_code >= 400:
            raise LLMProtocolError(
                f"the model answered {response.status_code}: "
                + _redact(response.text, self._config.api_key),
                status=response.status_code,
            )

        payload = self._decode(response)

        return LLMResult(
            content=self._object(self._text_of(payload)),
            model=str(payload.get("model") or self._config.model),
            usage=self._usage(payload),
            request_id=self._request_id(payload, response),
            status=self._status(payload),
        )

    # -- response reading -------------------------------------------------- #

    def _decode(self, response: httpx.Response) -> Mapping[str, Any]:
        """The body as a mapping, or a failure that quotes it only after redaction."""
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMOutputInvalid(
                "the model answered with something that is not JSON: "
                + _redact(response.text, self._config.api_key)
            ) from exc

        if not isinstance(payload, Mapping):
            raise LLMOutputInvalid("the model's response was not a JSON object")

        return payload

    @staticmethod
    def _status(payload: Mapping[str, Any]) -> str | None:
        value = payload.get("status")

        return value if isinstance(value, str) else None

    @staticmethod
    def _usage(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """What the call cost, when the provider says.  Never required."""
        usage = payload.get("usage")

        return usage if isinstance(usage, Mapping) else None

    @staticmethod
    def _request_id(payload: Mapping[str, Any], response: httpx.Response) -> str | None:
        for candidate in (payload.get("id"), response.headers.get("x-request-id")):
            if isinstance(candidate, str) and candidate != "":
                return candidate

        return None

    def _text_of(self, payload: Mapping[str, Any]) -> str:
        """The answer's text, from the one place the protocol puts it.

        The response carries a list of output items; the assistant's message
        holds content parts, and the part with the answer is an output text.  A
        status that is neither absent nor completed means the answer is not
        whole -- and half an answer must not be parsed as if it were one.
        """
        status = self._status(payload)

        if status == "incomplete":
            raise LLMOutputInvalid("the model's answer was incomplete")

        if status not in (None, "completed"):
            raise LLMProtocolError(f"the model reported status {status!r}")

        collected: list[str] = []
        output = payload.get("output")

        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                if item.get("type") not in (None, "message"):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if part.get("type") not in (None, "output_text", "text"):
                        continue
                    text = part.get("text")
                    if isinstance(text, str):
                        collected.append(text)

        # The convenience field some deployments add alongside the list.
        if not collected:
            convenience = payload.get("output_text")
            if isinstance(convenience, str):
                collected.append(convenience)

        joined = "".join(collected).strip()

        if joined == "":
            raise LLMOutputInvalid("the model returned no text")

        return joined

    @staticmethod
    def _object(text: str) -> dict[str, Any]:
        """The answer as an object.

        A non-object is not a schema mismatch -- that is the next layer's
        judgement, and it is the layer that owns the schema -- but it is never a
        usable answer, so it stops here.
        """
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise LLMOutputInvalid(
                f"the model's answer was not JSON ({type(exc).__name__})"
            ) from exc

        if not isinstance(parsed, dict):
            raise LLMOutputInvalid("the model's answer was not a JSON object")

        return parsed


# --------------------------------------------------------------------------- #
# The provider's strict dialect
# --------------------------------------------------------------------------- #

_LOCAL_REF_PREFIXES = ("#/$defs/", "#/definitions/")
_DEFINITION_KEYS = ("$defs", "definitions")
_BRANCH_KEYS = ("anyOf", "oneOf", "allOf")
_CHILD_KEYS = ("items", "not", "contains", "propertyNames", "if", "then", "else")
_MAX_DEPTH = 24


def normalized_usage(usage: Mapping[str, Any] | None) -> dict[str, int] | None:
    """The counts the provider reported, in the shape the audit stores.

    Nothing is computed and nothing is defaulted.  A provider that reports three
    of the five counts stores three; a stage that called no model stores nothing
    at all, because zeroes would make "no model ran" and "the model charged
    nothing" the same answer.
    """
    if not isinstance(usage, Mapping):
        return None

    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")

    reported: dict[str, Any] = {
        "inputTokens": usage.get("input_tokens"),
        "cachedInputTokens": input_details.get("cached_tokens")
        if isinstance(input_details, Mapping)
        else None,
        "outputTokens": usage.get("output_tokens"),
        "reasoningTokens": output_details.get("reasoning_tokens")
        if isinstance(output_details, Mapping)
        else None,
        "totalTokens": usage.get("total_tokens"),
    }

    counts = {
        name: value
        for name, value in reported.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }

    return counts or None


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The caller's JSON Schema, raised to the provider's strict dialect.

    The domain model is the contract and stays as it is; this is the adapter that
    makes its schema acceptable to a provider that only accepts a *closed*,
    *fully required* subset of JSON Schema.  Two transformations, nothing else:

    1. every object closes -- `required` lists all of its properties and
       `additionalProperties` is `false`.  Optional fields keep their
       meaning: a nullable field still says `anyOf: [..., {"type": "null"}]`, so
       "absent" becomes "required, and may be null";
    2. a union branch that cannot be expressed strictly -- one containing a
       dictionary with typed values, `additionalProperties: {schema}`, which no
       closed object can describe -- is dropped, and the definitions only it
       reached are dropped with it.  That is how the localized-text union is
       reduced to its literal form for this provider.

    Nothing is invented, no property, type, enum or array item is removed, and
    the caller's schema is never mutated.  A schema that is still unrepresentable
    after step 2 is refused loudly rather than silently weakened: a plan built
    from a schema nobody can satisfy is worse than a failed task.
    """
    prepared = copy.deepcopy(dict(schema))
    definitions = _definitions(prepared)

    # Deepest first, following local references: a union nested inside a branch
    # has to be reduced before its parent can be judged.
    for node in _post_order(prepared, definitions):
        _prune_branches(node, definitions)

    _drop_unused_definitions(prepared, definitions)

    # The definitions that survived, and everything they reference.
    for node in _post_order(prepared, _definitions(prepared)):
        _close_objects(node)

    return prepared


def _ref_name(reference: Any) -> str:
    if not isinstance(reference, str):
        return ""

    for prefix in _LOCAL_REF_PREFIXES:
        if reference.startswith(prefix):
            return reference[len(prefix) :]

    return ""


def _definitions(root: Mapping[str, Any]) -> dict[str, Any]:
    """Every locally defined subschema, by name (both spellings in use)."""
    merged: dict[str, Any] = {}

    for key in _DEFINITION_KEYS:
        section = root.get(key)
        if isinstance(section, dict):
            merged.update(section)

    return merged


def _resolve(node: Any, definitions: Mapping[str, Any]) -> Any:
    """Follow a local `$ref` to the subschema it names."""
    seen: set[str] = set()

    while isinstance(node, Mapping):
        name = _ref_name(node.get("$ref"))
        if name == "" or name in seen or name not in definitions:
            break
        seen.add(name)
        node = definitions[name]

    return node


def _subschemas(node: Any) -> list[Any]:
    """Every schema nested directly inside `node` (not across a `$ref`)."""
    if not isinstance(node, Mapping):
        return []

    children: list[Any] = []

    properties = node.get("properties")
    if isinstance(properties, Mapping):
        children.extend(properties.values())

    for key in _CHILD_KEYS:
        child = node.get(key)
        if isinstance(child, (Mapping, list)):
            children.append(child)

    items = node.get("items")
    if isinstance(items, list):
        children.extend(items)

    pattern_properties = node.get("patternProperties")
    if isinstance(pattern_properties, Mapping):
        children.extend(pattern_properties.values())

    for key in _BRANCH_KEYS:
        branches = node.get(key)
        if isinstance(branches, list):
            children.extend(branches)

    prefix_items = node.get("prefixItems")
    if isinstance(prefix_items, list):
        children.extend(prefix_items)

    return children


def _contains_open_map(node: Any, definitions: Mapping[str, Any], *, depth: int = 0) -> bool:
    """True when this subtree needs a dictionary no closed object can express."""
    if depth > _MAX_DEPTH:
        return False

    resolved = _resolve(node, definitions)

    if not isinstance(resolved, Mapping):
        return False

    if isinstance(resolved.get("additionalProperties"), Mapping):
        return True

    return any(
        _contains_open_map(child, definitions, depth=depth + 1)
        for child in _subschemas(resolved)
    )


def _post_order(root: Any, definitions: Mapping[str, Any]) -> list[Any]:
    """Every subschema reachable from `root`, children before parents.

    References are followed into the definitions, once each: without that, a
    model's nested objects -- which live in `$defs` and are reached only through
    a reference -- would never be visited at all.
    """
    ordered: list[Any] = []
    seen: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return

        if isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
            return

        if not isinstance(node, Mapping):
            return

        name = _ref_name(node.get("$ref"))
        if name != "" and name in definitions and name not in seen:
            seen.add(name)
            visit(definitions[name], depth + 1)

        for child in _subschemas(node):
            visit(child, depth + 1)

        ordered.append(node)

    visit(root, 0)

    return ordered


def _prune_branches(node: Any, definitions: Mapping[str, Any]) -> None:
    """Drop this node's union branches that the provider cannot express."""
    if not isinstance(node, dict):
        return

    for key in ("anyOf", "oneOf"):
        branches = node.get(key)
        if not isinstance(branches, list) or len(branches) < 2:
            continue

        kept = [
            branch for branch in branches if not _contains_open_map(branch, definitions)
        ]

        if kept and len(kept) < len(branches):
            if len(kept) == 1 and isinstance(kept[0], Mapping) and "$ref" in kept[0]:
                node.pop(key, None)
                node["$ref"] = kept[0]["$ref"]
            else:
                node[key] = kept


def _drop_unused_definitions(root: Any, definitions: Mapping[str, Any]) -> None:
    """Remove definitions nothing refers to any more, so no dead, illegal
    definition travels to the provider."""
    reachable: set[str] = set()
    frontier = [root]

    while frontier:
        node = frontier.pop()

        if isinstance(node, list):
            frontier.extend(node)
            continue

        if not isinstance(node, Mapping):
            continue

        for key, value in node.items():
            if key in _DEFINITION_KEYS:
                continue
            if key == "$ref":
                name = _ref_name(value)
                if name != "" and name not in reachable:
                    reachable.add(name)
                    if name in definitions:
                        frontier.append(definitions[name])
                continue
            if isinstance(value, (Mapping, list)):
                frontier.append(value)

    for key in _DEFINITION_KEYS:
        section = root.get(key) if isinstance(root, Mapping) else None
        if not isinstance(section, dict):
            continue
        for name in list(section):
            if name not in reachable:
                del section[name]


def _close_objects(node: Any) -> None:
    """Every object: all properties required, no additional properties."""
    if not isinstance(node, dict):
        return

    if isinstance(node.get("additionalProperties"), Mapping):
        raise LLMError(
            "this schema needs a dictionary with typed values, which the provider's "
            "strict dialect cannot express"
        )

    properties = node.get("properties")

    if isinstance(properties, dict):
        node["required"] = list(properties)
        node["additionalProperties"] = False
    elif node.get("type") == "object":
        node.setdefault("properties", {})
        node["required"] = []
        node["additionalProperties"] = False


