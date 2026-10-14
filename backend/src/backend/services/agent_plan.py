"""The deterministic agent pipeline: a document in, a draft plan out.

Phase 8.2 Step 2.  Three of the four operations the frozen AgentService boundary
names live here -- parseSpec, analyze and generatePlan -- as **pure functions**:
no session, no I/O, no clock except the two timestamps the contract keeps as
metadata.  The fourth (approve / reject) is not here and is not server-side yet.

The rules are ports of the browser's deterministic engine
(frontend/src/services/mock/agent/{parse,analyze,plan}.ts), not a new design:
endpoint ids, resource grouping, scheme detection, token-source selection,
scenario keys, step numbering and the i18n keys the copy is authored with are
the same, so a plan generated here and a plan generated in the browser for the
same document are the same plan.  Determinism is the point of this step: the
same document and the same prompt must produce the same business keys, and no
UUID, random value or timestamp may enter one.

Two deliberate reductions, both recorded in docs/agent-pipeline-contract.md:

* **JSON only.**  decode_document reads JSON.  The service has no YAML parser by
  decision -- spec_identity.probe_document labels a YAML document and sniffs two
  keys, but does not read it -- so a YAML document is refused with parse-failed
  rather than half-read.  Server-side YAML parsing is deferred.
* **Two scenario kinds.**  scenario_authentication when the document names a
  token source and an identity endpoint, and one scenario_smoke_<endpoint> per
  endpoint.  The browser's lifecycle / dependent / negative builders need the
  analysis this step does not port; what this step exists to prove is the
  pipeline, not to be the final generator.

One intentional difference from the browser's smoke scenario: a path parameter
becomes a {{param}} placeholder and is declared in consumes, where the browser
leaves it literal and would send /orders/{orderId} as written.  The contract's
path field is documented as "the document's path, may contain {{var}}", and a
step that names the variable it needs is a step the executor can actually call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from backend.schemas.run import PlanAssertion, PlanPayload, PlanScenario, PlanStep
from backend.services.spec_identity import slugify

__all__ = [
    "AGENT_TEXT_KEYS",
    "HTTP_METHODS",
    "ApiEndpointFacts",
    "ApiResourceFacts",
    "AuthenticationFacts",
    "DependencyFacts",
    "FindingFacts",
    "ParsedSpec",
    "PlanInvalid",
    "PlanPipelineError",
    "RiskFacts",
    "SpecFacts",
    "Understanding",
    "analyze",
    "decode_document",
    "generate_plan",
    "parse_document",
    "path_params_of",
    "validate_plan",
    "variables_in",
]


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

HTTP_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE")
"""The executor's whole method vocabulary, and therefore the plan's."""

_DOCUMENT_METHODS = frozenset(method.lower() for method in HTTP_METHODS)

ASSERTION_KINDS = ("status", "field", "header")
"""What the executor evaluates.

`schema` is recognized by the wire contract but is *not* accepted here: the
executor reports it skipped, so a plan that leans on one would claim coverage it
does not have (contract section 10, D3).
"""

_SKIPPED_ASSERTION_KIND = "schema"

AGENT_TEXT_KEYS: frozenset[str] = frozenset(
    {
        "console.aiTest.plan.lifecycleName",
        "console.aiTest.plan.lifecycleGoal",
        "console.aiTest.scenario.smokeName",
        "console.aiTest.scenario.smokeDescription",
        "console.aiTest.scenario.smokeExpected",
        "console.aiTest.scenario.authenticationName",
        "console.aiTest.scenario.authenticationDescription",
        "console.aiTest.scenario.authenticationExpected",
        "console.aiTest.step.callEndpoint",
        "console.aiTest.step.login",
        "console.aiTest.step.fetchIdentity",
        "console.aiTest.step.assertResponse",
        "console.aiTest.step.extractVariable",
        "console.aiTest.assertion.statusIs",
        "console.aiTest.assertion.fieldPresent",
        "console.aiTest.dependencies.rationaleToken",
        "console.aiTest.dependencies.rationaleLifecycle",
    }
)
"""Every i18n key this generator may author copy with.

The frontend resolves these from its own dictionary, so a key it does not have
renders to the user as a dotted identifier.  The validator refuses a plan that
uses any other key, which is the whole of what a server without a dictionary can
check about authored copy (contract section 5.4, P1).
"""

_TOKEN_SOURCE = re.compile(r"(login|sign-?in|token|auth)", re.IGNORECASE)
_TOKEN_FIELD = re.compile(r"^(access_)?token$|^jwt$", re.IGNORECASE)
_IDENTITY_PATH = re.compile(r"/me$", re.IGNORECASE)
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_VARIABLE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")

_MIN_SECRET_LENGTH = 6
"""Shortest value worth scanning a plan for.

Below this a "secret" is a string like id or 200 that occurs in ordinary copy
for innocent reasons, and a check that cannot pass is a check nobody keeps.
"""

_SCHEME_MAP: dict[str, str] = {
    "basic": "basic",
    "bearer": "bearer",
    "oauth2": "oauth2",
    "apiKey": "apiKey",
}

_CONSTRAINT_KEYWORDS = frozenset(
    {
        "enum",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "multipleOf",
        "format",
    }
)

_RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


class PlanPipelineError(Exception):
    """A stage refused to produce its output.

    `code` is the wire code the route turns into the error envelope; the codes
    are the ones frontend/src/services/agentError.ts already names, so the
    browser keeps its existing mapping.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PlanInvalid(PlanPipelineError):
    """A generated plan that the contract's rules refuse.

    Carries every issue rather than the first: a plan that breaks four rules is
    one report, and the run that produces it should not have to be repeated four
    times to learn them.
    """

    def __init__(self, issues: Sequence[dict[str, str]]) -> None:
        super().__init__("plan-invalid", f"{len(issues)} issue(s)")
        self.issues: list[dict[str, str]] = list(issues)


# --------------------------------------------------------------------------- #
# What the parser and the analysis produce
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ApiEndpointFacts:
    """One operation, in the shape frontend/src/types/agent.ts declares."""

    id: str
    method: str
    path: str
    resource_id: str
    summary: dict[str, Any]
    requires_auth: bool
    path_params: tuple[str, ...]
    required_body_props: tuple[str, ...]
    constrained_body_props: tuple[str, ...]
    response_statuses: tuple[int, ...]
    response_props: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


@dataclass(frozen=True)
class ApiResourceFacts:
    id: str
    name: str
    endpoint_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuthenticationFacts:
    scheme: str
    scheme_name: str | None
    header_name: str | None
    token_source_endpoint_id: str | None
    token_field: str | None
    protected_endpoint_count: int


@dataclass(frozen=True)
class SpecFacts:
    """The ApiSpec half of a parse: metadata, never structure."""

    id: str
    project_id: str
    slug: str
    title: str
    version: str
    format: str
    source: str
    filename: str
    server_url: str | None
    endpoint_count: int
    loaded_at: str


@dataclass(frozen=True)
class ParsedSpec:
    spec: SpecFacts
    endpoints: tuple[ApiEndpointFacts, ...]
    resources: tuple[ApiResourceFacts, ...]
    authentication: AuthenticationFacts


@dataclass(frozen=True)
class DependencyFacts:
    id: str
    from_endpoint_id: str
    to_endpoint_id: str
    kind: str
    binding: str
    rationale: dict[str, Any]


@dataclass(frozen=True)
class RiskFacts:
    id: str
    level: str
    category: str
    title: dict[str, Any]
    detail: dict[str, Any]
    related_endpoint_ids: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class FindingFacts:
    id: str
    action: dict[str, Any]
    decision_summary: dict[str, Any]
    result: str
    evidence: tuple[dict[str, Any], ...]
    at: str


@dataclass(frozen=True)
class Understanding:
    """Everything the agent understood about one document.

    A pure function of the parsed document, which is why it is never stored:
    recomputing it cannot disagree with the file it came from, and the database
    keeps no second copy to go stale (contract section 4.2).
    """

    spec_id: str
    endpoints: tuple[ApiEndpointFacts, ...]
    resources: tuple[ApiResourceFacts, ...]
    authentication: AuthenticationFacts
    dependencies: tuple[DependencyFacts, ...]
    risks: tuple[RiskFacts, ...]
    findings: tuple[FindingFacts, ...]
    analyzed_at: str = field(default="")


# --------------------------------------------------------------------------- #
# Small readers -- ports of the as* helpers in parse.ts
# --------------------------------------------------------------------------- #


def _as_record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) else None


def _as_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: str) -> dict[str, str]:
    """A literal LocalizedText.  Used for diagnostics, never for UI copy."""
    return {"text": value}


def _message(key: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
    """An authored LocalizedText: an i18n key plus its interpolation values."""
    return {"key": key, "params": dict(params or {})}


def path_params_of(path: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _PATH_PARAM.finditer(path))


def variables_in(value: str) -> tuple[str, ...]:
    """The {{var}} names a string references, in order of appearance."""
    return tuple(match.group(1) for match in _VARIABLE.finditer(value))

def _endpoint_id(method: str, path: str) -> str:
    return f"ep_{method.lower()}_{slugify(path) or 'root'}"


def _resource_label(operation: dict[str, Any], path: str) -> str:
    """The first tag, else the first meaningful path segment.

    `api` and version segments are skipped, so `/api/v1/orders/{id}` groups
    under `orders` rather than under `api` -- the rule parse.ts applies.
    """
    tags = _as_str_list(operation.get("tags"))
    if tags:
        return tags[0]

    segments = [segment for segment in path.split("/") if segment]
    meaningful = [
        segment
        for segment in segments
        if not re.fullmatch(r"(api|v\d+)", segment, re.IGNORECASE)
        and not segment.startswith("{")
    ]

    return (meaningful or segments or ["default"])[0]


# --------------------------------------------------------------------------- #
# parseSpec
# --------------------------------------------------------------------------- #


def decode_document(content: str) -> dict[str, Any]:
    """Read a document's text into a mapping.

    JSON only, by the reduction in the module docstring.  The error carries the
    decoder's own message as `detail`, which is what the frontend interpolates
    into its parseFailed sentence -- the technical cause stays visible and the
    sentence stays translatable.
    """
    try:
        parsed = json.loads(content)
    except (ValueError, RecursionError) as exc:
        raise PlanPipelineError(
            "parse-failed",
            f"the document is not JSON ({exc}); this service does not parse YAML",
        ) from exc

    document = _as_record(parsed)
    if document is None:
        raise PlanPipelineError("parse-failed", "the document's root is not an object")

    return document


def _detect_format(document: dict[str, Any]) -> str:
    openapi = document.get("openapi")
    if isinstance(openapi, str) and openapi.startswith("3."):
        return "openapi-3"

    swagger = document.get("swagger")
    if isinstance(swagger, str) and swagger.startswith("2."):
        return "swagger-2"

    raise PlanPipelineError(
        "unsupported-format",
        "expected an 'openapi' 3.x or 'swagger' 2.x field at the top level",
    )


def _server_url_of(document: dict[str, Any], format_: str) -> str | None:
    if format_ == "openapi-3":
        servers = document.get("servers")
        if isinstance(servers, list) and servers:
            first = _as_record(servers[0])
            if first is not None:
                return _as_str(first.get("url"))
        return None

    host = _as_str(document.get("host"))
    if host is None:
        return None

    schemes = _as_str_list(document.get("schemes"))
    base_path = _as_str(document.get("basePath")) or ""
    return f"{schemes[0] if schemes else 'https'}://{host}{base_path}"


def _body_schema(
    document: dict[str, Any], operation: dict[str, Any], format_: str
) -> dict[str, Any] | None:
    """The request body's schema, without resolving `$ref`.

    Reference resolution is the browser's resolveRef and is not ported: a
    document that factors its schemas out loses the body-property facts (which
    only feed the risk list), not the endpoint, and porting it is a parser's job.
    """
    if format_ == "openapi-3":
        request_body = _as_record(operation.get("requestBody"))
        if request_body is None:
            return None
        content = _as_record(request_body.get("content"))
        if content is None:
            return None
        media = _as_record(content.get("application/json"))
        return _as_record(media.get("schema")) if media is not None else None

    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        return None
    for parameter in parameters:
        record = _as_record(parameter)
        if record is not None and record.get("in") == "body":
            return _as_record(record.get("schema"))

    return None


def _body_facts(schema: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if schema is None:
        return (), ()

    required = _as_str_list(schema.get("required"))
    properties = _as_record(schema.get("properties")) or {}

    constrained: list[str] = []
    for name in required:
        definition = _as_record(properties.get(name))
        if definition is None:
            continue
        if _CONSTRAINT_KEYWORDS & set(definition):
            constrained.append(name)

    return required, tuple(constrained)


def _response_facts(operation: dict[str, Any]) -> tuple[tuple[int, ...], tuple[str, ...]]:
    responses = _as_record(operation.get("responses")) or {}

    statuses = sorted(
        int(code) for code in responses if isinstance(code, str) and code.isdigit()
    )

    props: tuple[str, ...] = ()
    for code in statuses:
        if not 200 <= code < 300:
            continue
        response = _as_record(responses.get(str(code)))
        if response is None:
            continue
        content = _as_record(response.get("content"))
        media = _as_record(content.get("application/json")) if content is not None else None
        schema = _as_record(media.get("schema")) if media is not None else None
        if schema is None:
            continue
        props = tuple((_as_record(schema.get("properties")) or {}).keys())
        if props:
            break

    return tuple(statuses), props


def _is_protected(document: dict[str, Any], operation: dict[str, Any]) -> bool:
    own = operation.get("security")
    if isinstance(own, list):
        return len(own) > 0

    global_ = document.get("security")
    return isinstance(global_, list) and len(global_) > 0


def _summary_of(operation: dict[str, Any], method: str, path: str) -> dict[str, str]:
    summary = _as_str(operation.get("summary"))
    if summary:
        return _text(summary)

    description = _as_str(operation.get("description"))
    if description:
        return _text(description.split("\n")[0])

    return _text(f"{method} {path}")


def _extract_endpoints(
    document: dict[str, Any], format_: str
) -> tuple[tuple[ApiEndpointFacts, ...], tuple[ApiResourceFacts, ...]]:
    """Every operation under `paths`, in document order.

    Collision-free ids without disturbing the ones that do not collide: the
    suffix is assigned only when two operations slug to the same string, which
    is what keeps a pre-existing plan's ids resolving (parse.ts's P1a fix).
    """
    paths = _as_record(document.get("paths"))
    if paths is None:
        raise PlanPipelineError("no-endpoints", "the document has no 'paths' object")

    endpoints: list[ApiEndpointFacts] = []
    labels: dict[str, str] = {}
    order: list[str] = []
    taken: set[str] = set()

    for path, item in paths.items():
        path_item = _as_record(item)
        if path_item is None:
            continue

        for method, operation in path_item.items():
            if not isinstance(method, str) or method.lower() not in _DOCUMENT_METHODS:
                continue
            operation_record = _as_record(operation)
            if operation_record is None:
                continue

            upper = method.upper()
            base = _endpoint_id(upper, path)
            endpoint_key = base
            suffix = 2
            while endpoint_key in taken:
                endpoint_key = f"{base}_{suffix}"
                suffix += 1
            taken.add(endpoint_key)

            label = _resource_label(operation_record, path)
            resource_id = f"res_{slugify(label)}"
            if resource_id not in labels:
                labels[resource_id] = label
                order.append(resource_id)

            required, constrained = _body_facts(
                _body_schema(document, operation_record, format_)
            )
            statuses, props = _response_facts(operation_record)

            endpoints.append(
                ApiEndpointFacts(
                    id=endpoint_key,
                    method=upper,
                    path=path,
                    resource_id=resource_id,
                    summary=_summary_of(operation_record, upper, path),
                    requires_auth=_is_protected(document, operation_record),
                    path_params=path_params_of(path),
                    required_body_props=required,
                    constrained_body_props=constrained,
                    response_statuses=statuses,
                    response_props=props,
                )
            )

    if not endpoints:
        raise PlanPipelineError("no-endpoints", "the document declares no operations")

    resources = tuple(
        ApiResourceFacts(
            id=resource_id,
            name=labels[resource_id],
            endpoint_ids=tuple(
                endpoint.id for endpoint in endpoints if endpoint.resource_id == resource_id
            ),
        )
        for resource_id in order
    )

    return tuple(endpoints), resources


def _detect_scheme(
    document: dict[str, Any], format_: str
) -> tuple[str, str | None, str | None]:
    if format_ == "openapi-3":
        components = _as_record(document.get("components")) or {}
        container = components.get("securitySchemes")
    else:
        container = document.get("securityDefinitions")

    schemes = _as_record(container)
    if schemes is None:
        return "none", None, None

    for name, definition in schemes.items():
        record = _as_record(definition)
        if record is None:
            continue
        type_ = _as_str(record.get("type"))
        if type_ is None:
            continue

        if type_ == "http":
            mapped = _SCHEME_MAP.get(_as_str(record.get("scheme")) or "")
            if mapped is not None:
                return mapped, name, None
            continue

        if type_ == "apiKey":
            header = _as_str(record.get("name")) if record.get("in") == "header" else None
            return "apiKey", name, header

        mapped = _SCHEME_MAP.get(type_)
        if mapped is not None:
            return mapped, name, None

    return "none", None, None


def _find_token_source(endpoints: Sequence[ApiEndpointFacts]) -> ApiEndpointFacts | None:
    """An unauthenticated POST that mints a credential; shortest path wins."""
    candidates = [
        endpoint
        for endpoint in endpoints
        if endpoint.method == "POST"
        and not endpoint.requires_auth
        and _TOKEN_SOURCE.search(endpoint.path)
    ]
    if not candidates:
        return None

    return sorted(candidates, key=lambda endpoint: len(endpoint.path))[0]


def _find_token_field(endpoint: ApiEndpointFacts | None) -> str | None:
    if endpoint is None:
        return None
    return next((prop for prop in endpoint.response_props if _TOKEN_FIELD.match(prop)), None)


def parse_document(
    document: dict[str, Any],
    *,
    project_id: str,
    spec_id: str,
    slug: str,
    filename: str,
    source: str,
) -> ParsedSpec:
    """Read a document into the understanding's inputs.

    `spec_id` and `slug` arrive from the caller because they are derived from
    the document's *text* (a hash) and the client's id, which is spec_identity's
    job and stays the single rule for it.
    """
    format_ = _detect_format(document)
    endpoints, resources = _extract_endpoints(document, format_)

    scheme, scheme_name, header_name = _detect_scheme(document, format_)
    token_source = _find_token_source(endpoints)
    info = _as_record(document.get("info")) or {}
    title = _as_str(info.get("title")) or filename

    return ParsedSpec(
        spec=SpecFacts(
            id=spec_id,
            project_id=project_id,
            slug=slug,
            title=title,
            version=_as_str(info.get("version")) or "",
            format=format_,
            source=source,
            filename=filename,
            server_url=_server_url_of(document, format_),
            endpoint_count=len(endpoints),
            loaded_at=_now(),
        ),
        endpoints=endpoints,
        resources=resources,
        authentication=AuthenticationFacts(
            scheme=scheme,
            scheme_name=scheme_name,
            header_name=header_name,
            token_source_endpoint_id=token_source.id if token_source is not None else None,
            token_field=_find_token_field(token_source),
            protected_endpoint_count=sum(1 for endpoint in endpoints if endpoint.requires_auth),
        ),
    )

# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #


def _token_dependencies(parsed: ParsedSpec) -> list[DependencyFacts]:
    source_id = parsed.authentication.token_source_endpoint_id
    if source_id is None:
        return []

    binding = parsed.authentication.token_field or "token"
    source = next(
        (endpoint for endpoint in parsed.endpoints if endpoint.id == source_id), None
    )
    if source is None:
        return []

    return [
        DependencyFacts(
            # The raw binding, not its slug: orderId and OrderId slug alike and
            # would otherwise be two edges wearing one id (parse.ts's P1b fix,
            # which frontend/docs/phase-6-architecture.md records as the minimal
            # correction).
            id=f"dep_{source.id}__{endpoint.id}__{binding}",
            from_endpoint_id=source.id,
            to_endpoint_id=endpoint.id,
            kind="token",
            binding=binding,
            rationale=_message(
                "console.aiTest.dependencies.rationaleToken",
                {"from": source.label, "to": endpoint.label},
            ),
        )
        for endpoint in parsed.endpoints
        if endpoint.requires_auth and endpoint.id != source_id
    ]


def _lifecycle_dependencies(parsed: ParsedSpec) -> list[DependencyFacts]:
    """A create and the item endpoint under it: POST /orders -> /orders/{id}.

    Only the nesting the paths spell out is derived.  The browser's identity and
    reference edges need response-schema analysis this step does not port, and a
    dependency nothing consumes is a fact no scenario can act on yet.
    """
    created = [
        endpoint
        for endpoint in parsed.endpoints
        if endpoint.method == "POST" and not endpoint.path_params
    ]

    edges: list[DependencyFacts] = []
    for endpoint in parsed.endpoints:
        if not endpoint.path_params:
            continue
        prefix = endpoint.path.split("{")[0].rstrip("/")
        for source in created:
            if source.path.rstrip("/") != prefix:
                continue
            binding = endpoint.path_params[0]
            edges.append(
                DependencyFacts(
                    id=f"dep_{source.id}__{endpoint.id}__{binding}",
                    from_endpoint_id=source.id,
                    to_endpoint_id=endpoint.id,
                    kind="lifecycle",
                    binding=binding,
                    rationale=_message(
                        "console.aiTest.dependencies.rationaleLifecycle",
                        {"from": source.label, "to": endpoint.label, "binding": binding},
                    ),
                )
            )
            break

    return edges


def _risks(parsed: ParsedSpec, dependencies: Sequence[DependencyFacts]) -> list[RiskFacts]:
    """Findings, each one a fact the document states about itself.

    Three rules, not the browser's six: authentication, dependency and
    negative-coverage are the ones whose inputs this parse produces.  The copy is
    literal because the understanding is a diagnostic intermediate here -- the
    frontend's own risk copy is its own business, and this module does not invent
    keys it cannot check.
    """
    risks: list[RiskFacts] = []

    protected = [endpoint for endpoint in parsed.endpoints if endpoint.requires_auth]
    if protected and parsed.authentication.token_source_endpoint_id is None:
        risks.append(
            RiskFacts(
                id="risk_authentication_no_token_source",
                level="high",
                category="authentication",
                title=_text("Protected endpoints declare no way to obtain a credential"),
                detail=_text(
                    "No unauthenticated POST that mints a token was found, so no "
                    "scenario can authenticate before calling these endpoints."
                ),
                related_endpoint_ids=tuple(endpoint.id for endpoint in protected),
                fields=(),
            )
        )

    produced = {(dependency.to_endpoint_id, dependency.binding) for dependency in dependencies}

    for endpoint in parsed.endpoints:
        unproduced = [
            param for param in endpoint.path_params if (endpoint.id, param) not in produced
        ]
        if unproduced:
            risks.append(
                RiskFacts(
                    id=f"risk_dependency_{endpoint.id}",
                    level="medium",
                    category="dependency",
                    title=_text("A path parameter has no producer in this document"),
                    detail=_text(
                        f"{endpoint.label} needs {', '.join(unproduced)} and no earlier "
                        "call in this document returns it, so the value has to come "
                        "from the environment."
                    ),
                    related_endpoint_ids=(endpoint.id,),
                    fields=tuple(unproduced),
                )
            )

    for endpoint in parsed.endpoints:
        if not endpoint.constrained_body_props:
            continue
        risks.append(
            RiskFacts(
                id=f"risk_negative_{endpoint.id}",
                level="medium",
                category="negative-coverage",
                title=_text("A constrained field is a candidate for a rejection case"),
                detail=_text(
                    f"{endpoint.label} requires {', '.join(endpoint.constrained_body_props)} "
                    "with a declared constraint, which a negative case should exercise. "
                    "Request bodies are not executed in this version, so no such "
                    "scenario is generated yet."
                ),
                related_endpoint_ids=(endpoint.id,),
                fields=endpoint.constrained_body_props,
            )
        )

    return risks


def _findings(
    parsed: ParsedSpec,
    dependencies: Sequence[DependencyFacts],
    risks: Sequence[RiskFacts],
    at: str,
) -> tuple[FindingFacts, ...]:
    """One line per stage: what the agent decided, with the count behind it.

    The copy is literal rather than keyed because these are diagnostics for the
    task record, not sentences the console renders.
    """
    authentication = parsed.authentication
    worst = max(
        (risk.level for risk in risks), key=lambda level: _RISK_ORDER[level], default="none"
    )

    return (
        FindingFacts(
            id="finding_parse",
            action=_text("Read the document"),
            decision_summary=_text(
                f"{len(parsed.endpoints)} endpoints across {len(parsed.resources)} resources"
            ),
            result="succeeded",
            evidence=(
                {"label": _text("Endpoints"), "value": str(len(parsed.endpoints))},
                {"label": _text("Resources"), "value": str(len(parsed.resources))},
            ),
            at=at,
        ),
        FindingFacts(
            id="finding_authentication",
            action=_text("Detect authentication"),
            decision_summary=_text(
                "no scheme declared"
                if authentication.scheme == "none"
                else f"{authentication.scheme} declared, credential minted by "
                + (authentication.token_source_endpoint_id or "no endpoint this document names")
            ),
            result="succeeded" if authentication.scheme != "none" else "skipped",
            evidence=(
                {"label": _text("Scheme"), "value": authentication.scheme},
                {
                    "label": _text("Protected endpoints"),
                    "value": str(authentication.protected_endpoint_count),
                },
            ),
            at=at,
        ),
        FindingFacts(
            id="finding_dependencies",
            action=_text("Trace the dependency path"),
            decision_summary=_text(f"{len(dependencies)} edges the plan can follow"),
            result="succeeded" if dependencies else "skipped",
            evidence=({"label": _text("Dependencies"), "value": str(len(dependencies))},),
            at=at,
        ),
        FindingFacts(
            id="finding_risks",
            action=_text("Identify coverage risks"),
            decision_summary=_text(f"{len(risks)} findings, worst level {worst}"),
            result="succeeded" if risks else "skipped",
            evidence=({"label": _text("Risks"), "value": str(len(risks))},),
            at=at,
        ),
    )


def analyze(parsed: ParsedSpec) -> Understanding:
    """Derive the understanding from a parsed document.

    Deterministic by construction: everything here is a function of the
    document, and the one timestamp is metadata no business key reads.
    """
    at = _now()
    dependencies = (*_token_dependencies(parsed), *_lifecycle_dependencies(parsed))
    risks = _risks(parsed, dependencies)

    return Understanding(
        spec_id=parsed.spec.id,
        endpoints=parsed.endpoints,
        resources=parsed.resources,
        authentication=parsed.authentication,
        dependencies=tuple(dependencies),
        risks=tuple(risks),
        findings=_findings(parsed, dependencies, risks, at),
        analyzed_at=at,
    )

# --------------------------------------------------------------------------- #
# generatePlan
# --------------------------------------------------------------------------- #


def _success_status(endpoint: ApiEndpointFacts) -> int:
    """First documented success status, or 200 when the document is silent."""
    return next((status for status in endpoint.response_statuses if 200 <= status < 300), 200)


# --------------------------------------------------------------------------- #
# The key formulas
#
# These are the contract's stable keys (section 5.3), written once so that the
# rule engine and the model-driven planner cannot drift apart: two generators
# producing different keys for the same design would break the browser's id
# matching, which has no positional fallback.
# --------------------------------------------------------------------------- #


KEY_LIMIT = 80
"""Longest key this pipeline derives.

Every key lands in a VARCHAR(100) column -- test_scenarios.scenario_key,
test_steps.step_key, test_assertions.assertion_key and the run snapshot's copies
-- so a key has to fit with room for a uniqueness suffix.  An endpoint id is made
from the document's path and has no bound of its own, and a designed scenario is
named in a sentence, so these formulas trim rather than trust their inputs.
"""


def bounded_key(key: str, *, limit: int = KEY_LIMIT) -> str:
    """The key, trimmed at a separator when it would not fit the contract's columns.

    Deterministic: the same input always trims to the same key.  The cut prefers a
    word boundary, so a trimmed key still reads as what it names.
    """
    if len(key) <= limit:
        return key

    head = key[:limit]
    cut = max(head.rfind("_"), head.rfind("-"))

    return (head[:cut] if cut > limit // 2 else head).rstrip("_-")


def request_step_key(endpoint_id: str, index: int) -> str:
    """A request step: the endpoint it calls, and its position in the scenario."""
    return bounded_key(f"{endpoint_id}__{index}")


def extract_step_key(endpoint_id: str, variable: str) -> str:
    return bounded_key(f"{endpoint_id}__extract_{variable}")


def assert_step_key(index: int) -> str:
    return bounded_key(f"assert__{index}")


def status_assertion_key(endpoint_id: str) -> str:
    return bounded_key(f"{endpoint_id}__status")


def field_assertion_key(endpoint_id: str, target: str) -> str:
    """A payload or header assertion: the endpoint, and the field it reads."""
    leaf = target.split(".")[-1] if "." in target else target
    cleaned = "".join(char if char.isalnum() or char in "_-" else "_" for char in leaf)

    return bounded_key(f"{endpoint_id}__{cleaned}")


def header_assertion_key(endpoint_id: str, target: str) -> str:
    """A header assertion: the endpoint, and the header it reads."""
    leaf = target.split(".", 1)[-1] if "." in target else target
    cleaned = "".join(char if char.isalnum() or char in "_-" else "_" for char in leaf)

    return bounded_key(f"{endpoint_id}__header_{cleaned}")


def request_step_path(endpoint: ApiEndpointFacts) -> str:
    """The document's path, with every path parameter named as a variable."""
    path = endpoint.path
    for param in endpoint.path_params:
        path = path.replace("{" + param + "}", "{{" + param + "}}")

    return path


def request_step_consumes(
    endpoint: ApiEndpointFacts, declared: Sequence[str]
) -> list[str]:
    """What the caller declared, plus the path parameters the path actually uses."""
    names = list(declared)
    for param in endpoint.path_params:
        if param not in names:
            names.append(param)

    return names


def _request_step(
    index: int,
    endpoint: ApiEndpointFacts,
    description_key: str,
    params: dict[str, str | int],
    consumes: Sequence[str],
) -> PlanStep:
    """One call, with every path parameter named rather than left literal."""
    return PlanStep(
        id=request_step_key(endpoint.id, index),
        index=index,
        kind="request",
        description=_message(description_key, params),
        endpoint_id=endpoint.id,
        method=endpoint.method,
        path=request_step_path(endpoint),
        produces=None,
        consumes=request_step_consumes(endpoint, consumes),
    )


def _extract_step(index: int, endpoint: ApiEndpointFacts, variable: str) -> PlanStep:
    return PlanStep(
        id=extract_step_key(endpoint.id, variable),
        index=index,
        kind="extract",
        description=_message("console.aiTest.step.extractVariable", {"variable": variable}),
        endpoint_id=endpoint.id,
        method=None,
        path=None,
        produces=variable,
        consumes=[],
    )


def _assert_step(index: int) -> PlanStep:
    return PlanStep(
        id=assert_step_key(index),
        index=index,
        kind="assert",
        description=_message("console.aiTest.step.assertResponse"),
        endpoint_id=None,
        method=None,
        path=None,
        produces=None,
        consumes=[],
    )


def _status_assertion(endpoint: ApiEndpointFacts) -> PlanAssertion:
    status = _success_status(endpoint)
    return PlanAssertion(
        id=status_assertion_key(endpoint.id),
        kind="status",
        target="status",
        expected=str(status),
        description=_message("console.aiTest.assertion.statusIs", {"status": status}),
    )


def _authentication_scenario(understanding: Understanding) -> PlanScenario | None:
    """Login, lift the credential, call the identity endpoint -- the browser's.

    Ported whole, including its three assertions and its trigger condition: a
    token source *and* a GET .../me style endpoint.  Without both there is no
    identity to prove the credential against, and the scenario would be a login
    with nothing to show for it.
    """
    authentication = understanding.authentication
    source_id = authentication.token_source_endpoint_id
    if source_id is None:
        return None

    source = next(
        (endpoint for endpoint in understanding.endpoints if endpoint.id == source_id), None
    )
    identity = next(
        (
            endpoint
            for endpoint in understanding.endpoints
            if endpoint.method == "GET" and _IDENTITY_PATH.search(endpoint.path)
        ),
        None,
    )
    if source is None or identity is None:
        return None

    token_field = authentication.token_field or "token"

    return PlanScenario(
        id="scenario_authentication",
        index=1,
        name=_message("console.aiTest.scenario.authenticationName"),
        description=_message("console.aiTest.scenario.authenticationDescription"),
        risk_level="high",
        steps=[
            _request_step(0, source, "console.aiTest.step.login", {}, []),
            _extract_step(1, source, token_field),
            _request_step(2, identity, "console.aiTest.step.fetchIdentity", {}, [token_field]),
            _assert_step(3),
        ],
        expected=_message("console.aiTest.scenario.authenticationExpected"),
        assertions=[
            _status_assertion(source),
            PlanAssertion(
                id=field_assertion_key(source.id, f"body.{token_field}"),
                kind="field",
                target=f"body.{token_field}",
                expected="present",
                description=_message(
                    "console.aiTest.assertion.fieldPresent", {"field": token_field}
                ),
            ),
            _status_assertion(identity),
        ],
    )


def _smoke_scenario(endpoint: ApiEndpointFacts, index: int) -> PlanScenario:
    """Call the endpoint and assert the status the document documents.

    The browser emits this one only as a fallback; the server emits it per
    endpoint, because a plan that covers one of six endpoints tells the user
    almost nothing.  The builder, the key scheme and the assertion are the
    browser's, and the scenario index is one-based because the browser's
    pushScenario numbers them that way.
    """
    label = endpoint.label

    return PlanScenario(
        id=f"scenario_smoke_{endpoint.id}",
        index=index,
        name=_message("console.aiTest.scenario.smokeName"),
        description=_message("console.aiTest.scenario.smokeDescription", {"endpoint": label}),
        risk_level="low",
        steps=[
            _request_step(0, endpoint, "console.aiTest.step.callEndpoint", {"endpoint": label}, []),
            _assert_step(1),
        ],
        expected=_message("console.aiTest.scenario.smokeExpected", {"endpoint": label}),
        assertions=[_status_assertion(endpoint)],
    )


def generate_plan(
    understanding: Understanding, spec: SpecFacts, *, source: str = "generated"
) -> PlanPayload:
    """Turn an understanding into a reviewable plan.  Always a draft.

    Nothing here reads a clock, a database or the environment: the plan is a
    function of the understanding and the spec, so running it twice produces the
    same ids and the same structure.
    """
    scenarios: list[PlanScenario] = []

    authentication = _authentication_scenario(understanding)
    if authentication is not None:
        scenarios.append(authentication)

    for endpoint in understanding.endpoints:
        scenarios.append(_smoke_scenario(endpoint, len(scenarios) + 1))

    risk_level = "low"
    for scenario in scenarios:
        if _RISK_ORDER[scenario.risk_level] > _RISK_ORDER[risk_level]:
            risk_level = scenario.risk_level

    return PlanPayload(
        id=f"plan_{spec.slug}",
        project_id=spec.project_id,
        spec_id=spec.id,
        name=_message("console.aiTest.plan.lifecycleName", {"resource": spec.title}),
        goal=_message("console.aiTest.plan.lifecycleGoal", {"resource": spec.title}),
        risk_level=risk_level,
        # Always draft.  Only a human action can move this forward, and the agent
        # has no path to the approved state (contract section 8.2, F3).
        status="draft",
        scenarios=scenarios,
        source=source,
        generated_at=datetime.now(timezone.utc),
        approved_at=None,
        rejected_at=None,
        rejection_reason=None,
    )

# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #


def _contiguous(indices: Sequence[int]) -> bool:
    """A dense run: sorted, unique, no gaps.  The base is the generator's choice."""
    return list(indices) == list(range(min(indices), min(indices) + len(indices)))


def validate_plan(
    plan: PlanPayload,
    *,
    project_id: str,
    spec_id: str,
    expected_plan_id: str,
    forbidden_values: Iterable[str] = (),
) -> None:
    """Refuse a plan the contract does not allow, before anything is written.

    Every rule here is a rule the contract states (sections 5 and 9.2) -- the
    list is the contract's, not a second opinion about it.  Issues accumulate so
    one call reports all of them; this function writes nothing and knows nothing
    about a session, which is what lets the service run it strictly between
    generate and persist.
    """
    issues: list[dict[str, str]] = []

    def issue(rule: str, detail: str) -> None:
        issues.append({"rule": rule, "detail": detail})

    if plan.project_id != project_id:
        issue("project-identity", f"plan says {plan.project_id!r}, request says {project_id!r}")

    if plan.spec_id != spec_id:
        issue("spec-identity", f"plan says {plan.spec_id!r}, expected {spec_id!r}")

    if plan.status != "draft":
        issue("plan-status", f"the agent may only produce 'draft', got {plan.status!r}")

    if plan.id != expected_plan_id:
        issue("plan-id", f"expected the stable id {expected_plan_id!r}, got {plan.id!r}")

    if not plan.scenarios:
        issue("no-scenarios", "a plan with no scenarios tests nothing")

    scenario_keys = [scenario.id for scenario in plan.scenarios]
    if len(set(scenario_keys)) != len(scenario_keys):
        issue("scenario-keys", "scenario ids are not unique within the plan")

    if scenario_keys and not _contiguous([scenario.index for scenario in plan.scenarios]):
        issue("scenario-order", "scenario indices are not a dense ascending run")

    for scenario in plan.scenarios:
        if not scenario.id.strip():
            issue("scenario-keys", "a scenario has an empty id")

        if not scenario.steps:
            issue("no-steps", f"scenario {scenario.id!r} has no steps")

        step_keys = [step.id for step in scenario.steps]
        if len(set(step_keys)) != len(step_keys):
            issue("step-keys", f"scenario {scenario.id!r} has duplicate step ids")

        if step_keys and not _contiguous([step.index for step in scenario.steps]):
            issue("step-order", f"scenario {scenario.id!r} has non-dense step indices")

        assertion_keys = [assertion.id for assertion in scenario.assertions]
        if len(set(assertion_keys)) != len(assertion_keys):
            issue("assertion-keys", f"scenario {scenario.id!r} has duplicate assertion ids")

        produced: set[str] = set()
        for step in scenario.steps:
            _validate_step(step, scenario.id, produced, issue)
            if step.kind == "extract" and step.produces:
                produced.add(step.produces)

        for assertion in scenario.assertions:
            _validate_assertion(assertion, scenario.id, issue)

    _validate_copy(plan, issue)
    _validate_secrets(plan, forbidden_values, issue)

    if issues:
        raise PlanInvalid(issues)


def _validate_step(
    step: PlanStep, scenario_id: str, produced: set[str], issue: Any
) -> None:
    where = f"scenario {scenario_id!r} step {step.id!r}"

    if not step.id.strip():
        issue("step-keys", f"{where} has an empty id")

    if step.kind == "request":
        if step.method is None or step.path is None:
            issue("request-target", f"{where} names no method or path")
        elif step.method not in HTTP_METHODS:
            issue("request-method", f"{where} uses {step.method!r}")
        else:
            declared = set(step.consumes)
            for name in variables_in(step.path):
                if name not in produced and name not in declared:
                    issue(
                        "request-variable",
                        f"{where} uses the variable {name!r} without producing or consuming it",
                    )
        return

    if step.kind == "extract":
        if not (step.produces or "").strip():
            issue("extract-variable", f"{where} extracts into no variable")
        return

    if step.kind == "assert":
        if step.method is not None or step.path is not None:
            issue("assert-target", f"{where} is an assert step that names a request")
        return

    issue("step-kind", f"{where} has unknown kind {step.kind!r}")


def _validate_assertion(assertion: PlanAssertion, scenario_id: str, issue: Any) -> None:
    where = f"scenario {scenario_id!r} assertion {assertion.id!r}"

    if not assertion.id.strip():
        issue("assertion-keys", f"{where} has an empty id")

    if assertion.kind == _SKIPPED_ASSERTION_KIND:
        issue(
            "unsupported-assertion",
            f"{where} is a schema assertion, which this executor reports as skipped",
        )
        return

    if assertion.kind not in ASSERTION_KINDS:
        issue("assertion-kind", f"{where} has unknown kind {assertion.kind!r}")
        return

    if assertion.kind == "status" and assertion.target != "status":
        issue("assertion-target", f"{where} is a status assertion targeting {assertion.target!r}")

    if assertion.kind == "field" and not assertion.target.startswith("body."):
        issue("assertion-target", f"{where} is a field assertion targeting {assertion.target!r}")

    if assertion.kind == "header" and not assertion.target.startswith("header."):
        issue("assertion-target", f"{where} is a header assertion targeting {assertion.target!r}")

    if not isinstance(assertion.expected, str) or not assertion.expected:
        issue("assertion-expected", f"{where} expects {assertion.expected!r}, not a string")


def _localized_values(plan: PlanPayload) -> Iterable[dict[str, Any]]:
    """Every LocalizedText the plan carries, as the dict it serialises to."""
    yield plan.name.model_dump()

    # The payload's prose field is `goal`; `description` is the column it lands in.
    if plan.goal is not None:
        yield plan.goal.model_dump()

    for scenario in plan.scenarios:
        yield scenario.name.model_dump()

        if scenario.description is not None:
            yield scenario.description.model_dump()

        if scenario.expected is not None:
            yield scenario.expected.model_dump()

        for step in scenario.steps:
            if step.description is not None:
                yield step.description.model_dump()

        for assertion in scenario.assertions:
            if assertion.description is not None:
                yield assertion.description.model_dump()


def _validate_copy(plan: PlanPayload, issue: Any) -> None:
    """Authored copy may only use keys the frontend's dictionary actually has."""
    for value in _localized_values(plan):
        key = value.get("key")
        if key is not None and key not in AGENT_TEXT_KEYS:
            issue("message-key", f"{key!r} is not a key the frontend can resolve")


def _validate_secrets(plan: PlanPayload, forbidden_values: Iterable[str], issue: Any) -> None:
    """No value of a variable may reach a plan.

    Scanned over the serialised plan rather than its fields: a value that leaked
    into a description is the same leak as one that leaked into a path, and the
    serialised form is the thing that would be written down.
    """
    haystack = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)

    for value in forbidden_values:
        if isinstance(value, str) and len(value) >= _MIN_SECRET_LENGTH and value in haystack:
            issue("secret-value", "a variable's value appears in the plan")
