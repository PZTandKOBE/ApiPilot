"""The Run Executor: what turns a queued run into an executed one.

A run is created queued and stays queued until something executes it.  This
module is that something: it walks a run's own snapshot -- scenarios, steps and
assertions, in sort order -- sends the HTTP requests the plan describes, judges
the assertions, writes the results and the evidence, and appends the events that
the live stream carries.  It is deterministic on purpose: no model, no planner,
no retry, no parallel steps.  The plan says what to test; this says what
happened.

**It executes the snapshot, not the plan.**  Everything it needs was frozen onto
``run_scenarios`` / ``run_steps`` / ``run_assertions`` when the run was created,
which is what makes a plan edited mid-run irrelevant to the run in flight.  There
is exactly one exception, and it is a gap rather than a decision: an ``extract``
step learns *which* variable it produces from ``test_steps.produces``, because
``run_steps`` has no such column and adding one is a migration this phase does
not make.  It reads that one field through ``source_step_id``; nothing else here
touches the plan side.

**Every boundary commits.**  The result rows and the event that announces them go
in one transaction, and that transaction ends immediately -- before the next
request is sent and long before the run is over.  A run is not one big
transaction: an HTTP call can take seconds, and holding a transaction across it
would both pin a connection and hide every event from the stream until the end.

**Cancellation is cooperative, and the run row is the only authority.**  The
executor asks "is this run still running" before each scenario, before each step,
again before the request, and once more after the step returns; the answer is
read from ``test_runs.status``, never cached.  Its own terminal writes are
conditional on the run still being ``running``, so a cancel that lands mid-flight
wins: the executor stops, writes nothing else, and emits no ``run.completed`` or
``run.failed``.  ``run.cancelled`` belongs to the cancel route and is never
produced here.

**Nothing secret is written down.**  Variable values live in this process for the
length of the run: they are read from the environment, substituted into a URL or
a header, and forgotten.  An event payload names variables, never their values,
and evidence records the *template* (``GET /orders/{{order_id}}``) rather than the
resolved URL -- so a history that is read back by anyone cannot leak a token
that was only ever meant for one request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import AsyncSessionLocal
from backend.db.models.agent import TestStep
from backend.db.models.project import EnvironmentAuth, EnvironmentVariable
from backend.db.models.result import (
    RunAssertion,
    RunEvidence,
    RunEvent,
    RunScenario,
    RunStep,
    TestRun,
)
from backend.services.runs import _as_text, _sse_timestamp, append_run_event, run_failure_dict

logger = logging.getLogger(__name__)

__all__ = [
    "EXECUTOR_DISABLED_ENV",
    "HTTP_TIMEOUT_SECONDS",
    "RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS",
    "RUN_RECOVERY_MAX_AGE_ENV",
    "RunExecutionContext",
    "build_url",
    "execute_run",
    "recover_queued_runs",
    "recovery_max_age_seconds",
    "resolve_variables",
    "schedule_run",
]

HTTP_TIMEOUT_SECONDS = 10.0
"""How long one request may take before it is a transport failure.

One number, in one place: a run that hangs is a run whose cancel has to wait,
and a timeout that differs per call site is a timeout nobody can reason about.
"""

VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
"""The ``{{name}}`` form, and the only substitution syntax this executor has.

Deliberately the whole of the language: no ``{{random.uuid}}``, no ``{{faker.email}}``,
no expressions.  Those are a contract the frontend has not defined yet, and a
backend that invents them is a backend the plan generator has to catch up with.
"""

QUEUED = "queued"
RUNNING = "running"
PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
CANCELLED = "cancelled"

_ACTIVE_STATUSES = (QUEUED, RUNNING)

MISSING_VARIABLE = "missing-runtime-variable"
TRANSPORT_ERROR = "transport-error"
EXTRACT_FAILED = "extract-failed"
NOT_EXECUTABLE = "not-executable"
EXECUTOR_FAILED = "executor-failed"
ASSERTION_FAILED = "assertion-failed"
"""Stable, safe codes: they are what a client reads when a code has no sentence.

They are internal identifiers, never messages -- nothing derived from a URL, a
body or an exception travels in them, which is why they can be written to a row
the browser reads back.
"""

EVIDENCE_ENDPOINT = "console.runs.evidence.endpoint"
EVIDENCE_EXTRACTED = "console.runs.evidence.extracted"
EVIDENCE_CHECKED = "console.runs.evidence.checked"
"""The three labels the console already renders -- see ``mock/run/script.ts``."""

_REQUEST_EVIDENCE_TYPE = "endpoint"
_EXTRACT_EVIDENCE_TYPE = "extracted"
_CHECK_EVIDENCE_TYPE = "checked"

EXECUTOR_DISABLED_ENV = "RUN_EXECUTOR_DISABLED"
"""Set it to keep a created run from being executed.

The verification scripts written before this phase create runs in order to test
the REST surface -- list, detail, cancel, replay, stream -- and every one of them
asserts what a run looks like *before* anything has executed it.  Now that
creating a run starts an executor, those fixtures would be executed out from
under their own assertions, so those scripts set this variable and get the world
they were written for.

It defaults to off, and off is the only behaviour the application ever gets: a
run created through the API is executed.  This is a test seam, not a feature.
"""

_RUNNING_TASKS: dict[uuid.UUID, asyncio.Task[None]] = {}
"""Live executor tasks, keyed by run.

A bare ``create_task`` whose reference is dropped is a task the garbage collector
may cancel -- the run would simply stop with nothing to say for itself.  The
registry is also what makes "one executor per run" checkable rather than
hopeful.
"""

_MISSING = object()
"""Distinguishes "the field is not there" from "the field is null"."""


# --------------------------------------------------------------------------- #
# What one run needs to know about itself
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunExecutionContext:
    """The state a run carries while it executes.

    ``variables`` is the environment, read once when the run starts; ``runtime`` is
    what the run itself produces.  They are separate fields rather than one
    merged mapping on purpose: the precedence rule ("runtime wins") is a decision
    this module makes at substitution time, and a merged dict would make it
    invisible -- and would make it impossible to tell a value that came from the
    user's environment from one an earlier step extracted.

    ``runtime`` never leaves this process.  It is not written to
    ``environment_variables``, not added to ``test_runs``, not echoed in a
    response, and not carried in an event payload.
    """

    run_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None
    base_url: str
    variables: Mapping[str, str]
    runtime: dict[str, str]
    current_scenario: str | None = None
    current_step: str | None = None


@dataclass(frozen=True)
class _Step:
    """One ``run_steps`` row, as the executor needs it."""

    id: uuid.UUID
    key: str
    kind: str
    method: str | None
    path: str | None
    produces: str | None


@dataclass(frozen=True)
class _Assertion:
    """One ``run_assertions`` row, as the executor needs it."""

    id: uuid.UUID
    key: str
    kind: str
    target: str
    expected: Any
    step_id: uuid.UUID | None


@dataclass(frozen=True)
class _Scenario:
    id: uuid.UUID
    key: str
    steps: tuple[_Step, ...]
    assertions: tuple[_Assertion, ...]


@dataclass(frozen=True)
class _Response:
    """What a request came back with, for the assertions and the extractions."""

    status_code: int
    headers: Mapping[str, str]
    text: str
    json: Any

    def header(self, name: str) -> str | None:
        """A header, case-insensitively -- HTTP does not promise a spelling."""
        wanted = name.strip().lower()

        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value

        return None

    def field(self, path: str) -> Any:
        """A dotted path into the JSON body, or ``_MISSING``.

        ``body.`` is accepted as a prefix because that is how the plan writes a
        body path (``body.token``) while the walk itself starts at the root.
        """
        target = path.strip()
        if target.startswith("body."):
            target = target[len("body.") :]

        current = self.json

        for part in [piece for piece in target.split(".") if piece != ""]:
            if isinstance(current, Mapping):
                if part not in current:
                    return _MISSING
                current = current[part]
            elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
                if not part.lstrip("-").isdigit():
                    return _MISSING
                index = int(part)
                if index >= len(current) or index < -len(current):
                    return _MISSING
                current = current[index]
            else:
                return _MISSING

        return current


@dataclass
class _StepOutcome:
    """Why a step stopped before its assertions, when it did."""

    code: str
    detail: str
    response: _Response | None = None


@dataclass
class _ScenarioOutcome:
    status: str
    failed_step_key: str | None = None
    code: str | None = None
    detail: str | None = None


# --------------------------------------------------------------------------- #
# Variables, URLs and auth
# --------------------------------------------------------------------------- #


def resolve_variables(text: str, context: RunExecutionContext) -> tuple[str, list[str]]:
    """Substitute ``{{name}}`` in ``text``, and report the names that have no value.

    Runtime values win over environment values -- an ``extract`` step exists to
    replace what the environment carried with what the API actually returned.

    A name with no value is **not** replaced with an empty string and is not
    left as a template that would be sent as a literal: it is collected, and the
    caller fails the step before any request is made.  Sending
    ``/orders/{{order_id}}`` to a server and calling the resulting 404 a test
    result would be the worst of the three options.
    """
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)

        if name in context.runtime:
            return context.runtime[name]

        if name in context.variables:
            return context.variables[name]

        missing.append(name)

        return match.group(0)

    return VARIABLE_PATTERN.sub(substitute, text), missing


def build_url(*, base_url: str, path: str) -> str:
    """``base_url`` + ``path``, unless the path is already a URL of its own.

    A plan may address the environment's API with a relative path or name a
    different host outright; concatenating unconditionally would turn the second
    case into an address that does not exist.
    """
    if path.startswith(("http://", "https://")):
        return path

    return base_url.rstrip("/") + "/" + path.lstrip("/")


def auth_parts(
    *,
    auth_type: str,
    config: Mapping[str, Any],
    context: RunExecutionContext,
) -> tuple[dict[str, str], list[str]]:
    """The headers, and any query fragment, an environment's auth rule adds.

    The rule shape is the one this repository already defines for an auth editor
    (``frontend/src/types/api.ts``): a ``type`` of ``bearer`` / ``basic` / ``apiKey``
    plus the fields for all three, stored flat so switching scheme in the UI does
    not discard what was typed under another one.  Values may reference
    ``{{variables}}`` and are resolved here like any other text.

    An unknown or ``none`` type adds nothing rather than raising: an environment
    with no auth is the ordinary case, and a run should not fail because a rule
    this build does not know about was configured.
    """
    headers: dict[str, str] = {}
    query: list[str] = []

    def value(key: str) -> str:
        raw = config.get(key)
        if not isinstance(raw, str) or raw == "":
            return ""

        return resolve_variables(raw, context)[0]

    if auth_type == "bearer":
        token = value("bearerToken")
        if token != "":
            headers["Authorization"] = "Bearer " + token
    elif auth_type == "basic":
        username = value("username")
        password = value("password")
        if username != "" or password != "":
            encoded = base64.b64encode((username + ":" + password).encode("utf-8")).decode("ascii")
            headers["Authorization"] = "Basic " + encoded
    elif auth_type in ("apiKey", "api_key"):
        name = value("apiKeyName")
        secret = value("apiKeyValue")
        if name != "" and secret != "":
            if config.get("apiKeyIn") == "query":
                query.append(quote(name, safe="") + "=" + quote(secret, safe=""))
            else:
                headers[name] = secret

    return headers, query


# --------------------------------------------------------------------------- #
# Reading a response
# --------------------------------------------------------------------------- #


def parse_json(text: str) -> Any:
    """The body as JSON, or ``None`` when it is not JSON.

    Not an error: plenty of endpoints answer with HTML or an empty body, and the
    assertions that care about a body are the ones that should say so.
    """
    if text.strip() == "":
        return None

    try:
        return json.loads(text)
    except ValueError:
        return None


def find_value(document: Any, name: str, *, depth: int = 4) -> Any:
    """``name`` from a JSON document: the top level first, then nested.

    The search is bounded (``depth``) and breadth-first, so
    ``{"token": "a", "data": {"token": "b"}}`` yields the outer one, a document
    that never mentions the name yields ``_MISSING``, and a deeply self-referential
    document cannot turn an extract step into a walk of the whole payload.
    """
    level: list[Any] = [document]

    for _ in range(depth):
        if not level:
            break

        following: list[Any] = []

        for item in level:
            if isinstance(item, Mapping):
                if name in item:
                    return item[name]
                following.extend(item.values())
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                following.extend(item)

        level = following

    return _MISSING


def evaluate_assertion(assertion: _Assertion, response: _Response) -> tuple[str, str | None, str | None]:
    """Judge one assertion: ``(status, actual, reason)``.

    ``actual`` is text because that is what the run assertion column and the
    event both carry -- normalised with the very function the read path uses, so
    a value written here and the same value read back from JSONB render
    identically.  ``reason`` is set only where the result needs explaining, and it
    never contains a response value.
    """
    if assertion.kind == "status":
        actual = str(response.status_code)

        return _verdict(actual, assertion.expected), actual, None

    if assertion.kind == "header":
        actual = response.header(assertion.target)

        if actual is None:
            return FAILED, None, "the response carried no such header"

        return _verdict(actual, assertion.expected), actual, None

    if assertion.kind == "field":
        found = response.field(assertion.target)

        if found is _MISSING:
            return FAILED, None, "the response body did not carry this field"

        return _verdict(_as_text(found), assertion.expected), _as_text(found), None

    if assertion.kind == "schema":
        return SKIPPED, None, "schema assertions are not executable in Phase 7.3"

    return SKIPPED, None, "this build does not know that assertion kind"


def _verdict(actual: str, expected: Any) -> str:
    return PASSED if actual == _as_text(expected) else FAILED


def _failure_message(exception: Exception) -> str:
    """A transport failure in words that describe it and nothing else.

    Never ``str(exception)``: httpx puts the request URL in its messages, and a
    URL can carry an API key the plan put in a query parameter.  The full
    exception goes to the server log; this is what a client may read.
    """
    if isinstance(exception, httpx.TimeoutException):
        return "the request timed out after " + str(HTTP_TIMEOUT_SECONDS) + "s"

    if isinstance(exception, httpx.ConnectError):
        return "the host could not be reached"

    if isinstance(exception, httpx.InvalidURL):
        return "the resolved URL is not valid"

    return "the request could not be completed"


# --------------------------------------------------------------------------- #
# Reading the run's snapshot
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RunFacts:
    project_id: uuid.UUID
    environment_id: uuid.UUID | None
    base_url: str
    status: str


async def _load_run(session: AsyncSession, run_id: uuid.UUID) -> _RunFacts | None:
    row = (
        await session.execute(
            select(
                TestRun.project_id,
                TestRun.environment_id,
                TestRun.base_url,
                TestRun.status,
            ).where(TestRun.id == run_id)
        )
    ).one_or_none()

    if row is None:
        return None

    return _RunFacts(
        project_id=row.project_id,
        environment_id=row.environment_id,
        base_url=row.base_url,
        status=row.status,
    )


async def _load_variables(session: AsyncSession, environment_id: uuid.UUID | None) -> dict[str, str]:
    """The environment's variables, by name -- the values the run may use.

    Only enabled rows.  Nothing here is logged, echoed or persisted: the values
    exist for the length of the run and are substituted into the places the plan
    put a template.
    """
    if environment_id is None:
        return {}

    rows = (
        await session.execute(
            select(EnvironmentVariable.key, EnvironmentVariable.value_encrypted).where(
                EnvironmentVariable.environment_id == environment_id,
                EnvironmentVariable.enabled.is_(True),
            )
        )
    ).all()

    return {key: value for key, value in rows}


async def _load_auth(
    session: AsyncSession, environment_id: uuid.UUID | None
) -> tuple[str, Mapping[str, Any]] | None:
    """The environment's default, enabled auth rule, if it has one."""
    if environment_id is None:
        return None

    row = (
        await session.execute(
            select(EnvironmentAuth.auth_type, EnvironmentAuth.config).where(
                EnvironmentAuth.environment_id == environment_id,
                EnvironmentAuth.is_enabled.is_(True),
                EnvironmentAuth.is_default.is_(True),
            )
        )
    ).one_or_none()

    return None if row is None else (row.auth_type, row.config)


async def _load_produced(session: AsyncSession, step_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Which variable each step produces -- the one field the snapshot does not carry.

    ``run_steps`` has no ``produces`` column (the plan's step does), so an
    ``extract`` step learns its variable here, through the ``source_step_id`` link
    the create path already writes.  A step whose plan row has since gone keeps a
    NULL link and simply has nothing to extract into -- which the extract step
    reports as its own failure rather than as a crash.
    """
    if not step_ids:
        return {}

    rows = (
        await session.execute(
            select(RunStep.id, TestStep.produces)
            .join(TestStep, TestStep.id == RunStep.source_step_id)
            .where(RunStep.id.in_(step_ids))
        )
    ).all()

    return {step_id: produces for step_id, produces in rows if produces is not None}


async def _load_tree(session: AsyncSession, run_id: uuid.UUID) -> list[_Scenario]:
    """The run's scenarios, steps and assertions, each level ordered explicitly.

    The same ordering the detail endpoint reads by -- ``sort_order`` with the stable
    key as a tiebreaker, and ``assertion_key`` for the rows that have no order
    column -- because a run executed in one order and drawn in another is a run
    nobody can debug.
    """
    scenario_rows = (
        await session.execute(
            select(RunScenario.id, RunScenario.scenario_key)
            .where(RunScenario.run_id == run_id)
            .order_by(RunScenario.sort_order, RunScenario.scenario_key)
        )
    ).all()

    if not scenario_rows:
        return []

    scenario_ids = [row.id for row in scenario_rows]

    step_rows = (
        await session.execute(
            select(
                RunStep.id,
                RunStep.run_scenario_id,
                RunStep.step_key,
                RunStep.step_type,
                RunStep.method,
                RunStep.path,
            )
            .where(RunStep.run_scenario_id.in_(scenario_ids))
            .order_by(RunStep.run_scenario_id, RunStep.sort_order, RunStep.step_key)
        )
    ).all()

    assertion_rows = (
        await session.execute(
            select(
                RunAssertion.id,
                RunAssertion.run_scenario_id,
                RunAssertion.assertion_key,
                RunAssertion.assertion_type,
                RunAssertion.target,
                RunAssertion.expected_value,
                RunAssertion.run_step_id,
            )
            .where(RunAssertion.run_scenario_id.in_(scenario_ids))
            .order_by(RunAssertion.run_scenario_id, RunAssertion.assertion_key)
        )
    ).all()

    produced = await _load_produced(session, [row.id for row in step_rows])

    steps_by_scenario: dict[uuid.UUID, list[_Step]] = {}
    for row in step_rows:
        steps_by_scenario.setdefault(row.run_scenario_id, []).append(
            _Step(
                id=row.id,
                key=row.step_key,
                kind=row.step_type,
                method=row.method,
                path=row.path,
                produces=produced.get(row.id),
            )
        )

    assertions_by_scenario: dict[uuid.UUID, list[_Assertion]] = {}
    for row in assertion_rows:
        assertions_by_scenario.setdefault(row.run_scenario_id, []).append(
            _Assertion(
                id=row.id,
                key=row.assertion_key,
                kind=row.assertion_type,
                target=row.target,
                expected=row.expected_value,
                step_id=row.run_step_id,
            )
        )

    return [
        _Scenario(
            id=row.id,
            key=row.scenario_key,
            steps=tuple(steps_by_scenario.get(row.id, [])),
            assertions=tuple(assertions_by_scenario.get(row.id, [])),
        )
        for row in scenario_rows
    ]


# --------------------------------------------------------------------------- #
# Writing what happened
# --------------------------------------------------------------------------- #


async def _still_running(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Whether this run may continue, read fresh every time it is asked.

    Cached state would be the bug this exists to prevent: a cancel commits in
    another transaction, and the only way to see it is to ask the database
    again.  One indexed read per boundary is the price of a run that stops when
    it is told to.
    """
    status = (
        await session.execute(select(TestRun.status).where(TestRun.id == run_id))
    ).scalar_one_or_none()

    return status == RUNNING


async def _start_scenario(session: AsyncSession, scenario: _Scenario, *, now: datetime) -> None:
    await session.execute(
        update(RunScenario)
        .where(RunScenario.id == scenario.id)
        .values(status=RUNNING, started_at=now)
    )


async def _finish_scenario(
    session: AsyncSession, scenario: _Scenario, *, status: str, now: datetime
) -> None:
    await session.execute(
        update(RunScenario)
        .where(RunScenario.id == scenario.id)
        .values(status=status, finished_at=now)
    )


async def _start_step(session: AsyncSession, step: _Step, *, now: datetime) -> None:
    await session.execute(
        update(RunStep).where(RunStep.id == step.id).values(status=RUNNING, started_at=now)
    )


async def _finish_step(
    session: AsyncSession,
    step: _Step,
    *,
    status: str,
    now: datetime,
    duration_ms: int,
    code: str | None = None,
    detail: str | None = None,
) -> None:
    await session.execute(
        update(RunStep)
        .where(RunStep.id == step.id)
        .values(
            status=status,
            finished_at=now,
            duration_ms=duration_ms,
            error_code=code,
            error_message=detail,
        )
    )


async def _skip_pending_steps(session: AsyncSession, scenario_ids: Sequence[uuid.UUID]) -> None:
    """Steps that never ran are ``skipped``, not left ``pending``.

    A step left pending reads, to anyone looking at a finished run, as one that
    still might run -- which is exactly the difference between "not yet" and
    "never" that the console draws.
    """
    if not scenario_ids:
        return

    await session.execute(
        update(RunStep)
        .where(RunStep.run_scenario_id.in_(list(scenario_ids)), RunStep.status == "pending")
        .values(status=SKIPPED)
    )


async def _abandon_step(
    session: AsyncSession, scenario_ids: Sequence[uuid.UUID]
) -> None:
    """Steps a cancellation caught: announced, never finished.

    A step in this state is ``running`` in the row and ``skipped`` in the console's
    own view of the same event, because ``settleRemaining`` treats pending and
    running alike when a run ends.  Leaving the row ``running`` would make a
    reloaded page contradict the page it replaced, so both are settled here.
    """
    if not scenario_ids:
        return

    await session.execute(
        update(RunStep)
        .where(
            RunStep.run_scenario_id.in_(list(scenario_ids)),
            RunStep.status.in_(("pending", "running")),
        )
        .values(status=SKIPPED)
    )


async def _settle_unfinished(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Mark what never ran as skipped, without committing.

    The transaction core of :func:`_settle_after_cancel`, separated so a caller
    that is already in a transaction of its own can use it without inheriting a
    ``commit()``.  Recovery is that caller: it has to mark the run failed, settle
    these rows and append one ``run.failed`` event as a single unit, or leave
    nothing behind at all.

    The status filters make it idempotent -- a second pass updates no row -- and
    safe for a run that had already produced results: a step that finished keeps
    its status, and an assertion that was judged keeps it.
    """
    scenario_ids = select(RunScenario.id).where(RunScenario.run_id == run_id)

    await session.execute(
        update(RunStep)
        .where(
            RunStep.run_scenario_id.in_(scenario_ids),
            RunStep.status.in_(("pending", "running")),
        )
        .values(status=SKIPPED)
    )
    await session.execute(
        update(RunAssertion)
        .where(
            RunAssertion.run_scenario_id.in_(
                select(RunScenario.id).where(RunScenario.run_id == run_id)
            ),
            RunAssertion.status.not_in((PASSED, FAILED)),
        )
        .values(status=SKIPPED)
    )
    await session.execute(
        update(RunScenario)
        .where(RunScenario.run_id == run_id, RunScenario.status == "pending")
        .values(status=SKIPPED)
    )


async def _settle_after_cancel(session: AsyncSession, run_id: uuid.UUID) -> None:
    """What never ran, after a cancel: marked skipped and committed.

    The live page settles its own view; this is what a *reload* reads.  The run
    row itself is left alone -- the cancel route already decided it.
    """
    await _settle_unfinished(session, run_id)
    await session.commit()


async def _add_evidence(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    step_id: uuid.UUID,
    label: str,
    evidence_type: str,
    value: str,
) -> dict[str, Any]:
    """Write one evidence row, and return the shape the event carries.

    One row, two readings: the database keeps it for the detail page, and the
    same label/value pair travels in the ``step.completed`` payload so the live
    page does not have to fetch anything to draw it.
    """
    session.add(
        RunEvidence(
            run_id=run_id,
            run_step_id=step_id,
            evidence_type=evidence_type,
            label={"key": label},
            value=value,
        )
    )

    return {"label": {"key": label}, "value": value}


async def _write_assertion(
    session: AsyncSession,
    assertion: _Assertion,
    *,
    status: str,
    actual: str | None,
    reason: str | None,
) -> None:
    await session.execute(
        update(RunAssertion)
        .where(RunAssertion.id == assertion.id)
        .values(status=status, actual_value=actual, error_message=reason)
    )


def _elapsed_ms(started_at: datetime | None, finished_at: datetime) -> int:
    """A duration, from two instants, never negative.

    The same rule the read path applies to a run (``_duration_ms_of``): half a
    lifecycle is not a duration, and a clock that went backwards is not a small
    one.  A run that never started measures zero rather than nothing, because a
    cancelled or never-started run is a finished one.
    """
    if started_at is None:
        return 0

    elapsed = round((finished_at - started_at).total_seconds() * 1000)

    return elapsed if elapsed >= 0 else 0


# --------------------------------------------------------------------------- #
# Executing one step
# --------------------------------------------------------------------------- #


async def _execute_step(
    *,
    step: _Step,
    context: RunExecutionContext,
    auth: tuple[str, Mapping[str, Any]] | None,
    client: httpx.AsyncClient,
    response: _Response | None,
) -> tuple[_StepOutcome | None, _Response | None, list[dict[str, Any]]]:
    """Run one step: ``(failure, response, evidence)``.

    ``request`` sends the call, ``extract`` lifts a value out of the last
    response, and ``assert`` is a marker the assertions attach to -- the frontend
    models it that way and the plan generator emits it that way, so it is walked
    like any other step and does nothing of its own.
    """
    if step.kind == "extract":
        return _extract(step=step, context=context, response=response)

    if step.kind != "request":
        return None, response, []

    if step.method is None or step.path is None:
        return (
            _StepOutcome(
                code=NOT_EXECUTABLE,
                detail="the step names no method or path, so there is nothing to call",
            ),
            response,
            [],
        )

    # The evidence is built from the *template*, before anything is resolved: a
    # resolved URL can carry a token that the plan put in a query parameter, and
    # a history anybody can read is the wrong place for it.
    evidence = [
        {
            "label": {"key": EVIDENCE_ENDPOINT},
            "value": step.method + " " + step.path,
        }
    ]

    path, missing = resolve_variables(step.path, context)

    if missing:
        return (
            _StepOutcome(
                code=MISSING_VARIABLE,
                detail="this run has no value for: " + ", ".join(sorted(set(missing))),
            ),
            response,
            evidence,
        )

    headers: dict[str, str] = {}
    query: list[str] = []

    if auth is not None:
        auth_type, auth_config = auth
        headers, query = auth_parts(auth_type=auth_type, config=auth_config, context=context)

    url = build_url(base_url=context.base_url, path=path)

    if query:
        url = url + ("&" if "?" in url else "?") + "&".join(query)

    try:
        called = await client.request(step.method, url, headers=headers)
    except httpx.HTTPError as exc:
        # The exception's own text names the URL, so it goes to the log and the
        # client gets a sentence that describes the failure without repeating it.
        logger.warning(
            "run %s step %s: %s while calling %s %s",
            context.run_id,
            step.key,
            type(exc).__name__,
            step.method,
            step.path,
        )

        return _StepOutcome(code=TRANSPORT_ERROR, detail=_failure_message(exc)), response, evidence

    return (
        None,
        _Response(
            status_code=called.status_code,
            headers=dict(called.headers),
            text=called.text,
            json=parse_json(called.text),
        ),
        evidence,
    )


def _extract(
    *,
    step: _Step,
    context: RunExecutionContext,
    response: _Response | None,
) -> tuple[_StepOutcome | None, _Response | None, list[dict[str, Any]]]:
    """Lift the step's variable out of the scenario's most recent response."""
    if step.produces is None:
        return (
            _StepOutcome(
                code=EXTRACT_FAILED,
                detail="this step names no variable to extract",
            ),
            response,
            [],
        )

    # The variable's *name*, never its value: the console shows this line.
    evidence = [{"label": {"key": EVIDENCE_EXTRACTED}, "value": step.produces}]

    if response is None:
        return (
            _StepOutcome(
                code=EXTRACT_FAILED,
                detail="no response has been received in this scenario yet",
            ),
            response,
            evidence,
        )

    if response.json is None:
        return (
            _StepOutcome(
                code=EXTRACT_FAILED,
                detail="the last response was not JSON",
            ),
            response,
            evidence,
        )

    found = find_value(response.json, step.produces)

    if found is _MISSING:
        return (
            _StepOutcome(
                code=EXTRACT_FAILED,
                detail="the response did not carry " + step.produces,
            ),
            response,
            evidence,
        )

    context.runtime[step.produces] = _as_text(found)

    return None, response, evidence


_EVIDENCE_TYPES = {
    EVIDENCE_ENDPOINT: _REQUEST_EVIDENCE_TYPE,
    EVIDENCE_EXTRACTED: _EXTRACT_EVIDENCE_TYPE,
    EVIDENCE_CHECKED: _CHECK_EVIDENCE_TYPE,
}


async def _record_evidence(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    step: _Step,
    evidence: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Write the step's evidence rows and return the payload the event carries."""
    items: list[dict[str, Any]] = []

    for item in evidence:
        label = str(item["label"]["key"])
        items.append(
            await _add_evidence(
                session,
                run_id=run_id,
                step_id=step.id,
                label=label,
                evidence_type=_EVIDENCE_TYPES.get(label, _CHECK_EVIDENCE_TYPE),
                value=str(item["value"]),
            )
        )

    return items


# --------------------------------------------------------------------------- #
# Executing one scenario
# --------------------------------------------------------------------------- #


async def _run_scenario(
    *,
    session: AsyncSession,
    scenario: _Scenario,
    context: RunExecutionContext,
    auth: tuple[str, Mapping[str, Any]] | None,
    client: httpx.AsyncClient,
) -> _ScenarioOutcome:
    """Walk the scenario's steps, then judge its assertions.

    The order is the plan's: steps by ``sort_order``, assertions after them by
    ``assertion_key``.  A step that fails stops the scenario -- the steps after it
    never run and are recorded as skipped -- and the assertions are left as they
    were, because there is no response to judge.  Whether the *next* scenario
    runs is the caller's decision, and it runs.

    The step the assertions belong to finishes **after** them.  Its outcome is
    their outcome: reporting it complete first and then correcting it would put
    two contradictory frames on the wire for one step.
    """
    run_id = context.run_id

    await _start_scenario(session, scenario, now=datetime.now(timezone.utc))
    await session.commit()

    step_keys = {step.id: step.key for step in scenario.steps}
    checkpoint_id = next(
        (assertion.step_id for assertion in scenario.assertions if assertion.step_id is not None),
        None,
    )

    response: _Response | None = None
    failure: _StepOutcome | None = None
    failed_step: _Step | None = None
    deferred: _Step | None = None
    deferred_evidence: Sequence[Mapping[str, Any]] = ()
    deferred_duration = 0
    started_any = False

    for step in scenario.steps:
        if not await _still_running(session, run_id):
            await _stop_scenario(
                session=session, run_id=run_id, scenario=scenario, started_any=started_any
            )
            return _ScenarioOutcome(status=SKIPPED)

        step_context = replace(context, current_step=step.key)

        await _start_step(session, step, now=datetime.now(timezone.utc))
        await append_run_event(
            session,
            run_id=run_id,
            event_type="step.started",
            payload={"scenarioId": scenario.key, "stepId": step.key},
        )
        await session.commit()

        started_any = True

        # The last check before the wire.  A cancel that landed while this step
        # was being announced stops it here rather than after the call.
        if not await _still_running(session, run_id):
            await _stop_scenario(
                session=session, run_id=run_id, scenario=scenario, started_any=started_any
            )
            return _ScenarioOutcome(status=SKIPPED)

        clock = time.monotonic()
        outcome, response, evidence = await _execute_step(
            step=step,
            context=step_context,
            auth=auth,
            client=client,
            response=response,
        )
        duration_ms = max(0, round((time.monotonic() - clock) * 1000))
        finished_at = datetime.now(timezone.utc)

        if step.kind == "assert":
            evidence = [
                {
                    "label": {"key": EVIDENCE_CHECKED},
                    "value": str(len(scenario.assertions)),
                }
            ]

        if outcome is not None:
            failure = outcome
            failed_step = step

            await _finish_step(
                session,
                step,
                status=FAILED,
                now=finished_at,
                duration_ms=duration_ms,
                code=outcome.code,
                detail=outcome.detail,
            )
            await _record_evidence(session, run_id=run_id, step=step, evidence=evidence)
            await append_run_event(
                session,
                run_id=run_id,
                event_type="step.failed",
                payload={
                    "scenarioId": scenario.key,
                    "stepId": step.key,
                    "durationMs": duration_ms,
                    "failure": run_failure_dict(outcome.code, outcome.detail),
                },
            )
            await session.commit()
            break

        if step.id == checkpoint_id and scenario.assertions:
            deferred = step
            deferred_evidence = evidence
            deferred_duration = duration_ms
            continue

        await _finish_step(session, step, status=PASSED, now=finished_at, duration_ms=duration_ms)
        items = await _record_evidence(session, run_id=run_id, step=step, evidence=evidence)
        await append_run_event(
            session,
            run_id=run_id,
            event_type="step.completed",
            payload={
                "scenarioId": scenario.key,
                "stepId": step.key,
                "durationMs": duration_ms,
                "evidence": items,
            },
        )
        await session.commit()

    assertion_failed = False

    if failure is None:
        for assertion in scenario.assertions:
            if response is None:
                status, actual, reason = SKIPPED, None, "there was no response to check"
            else:
                status, actual, reason = evaluate_assertion(assertion, response)

            await _write_assertion(session, assertion, status=status, actual=actual, reason=reason)

            checkpoint_key = step_keys.get(assertion.step_id) if assertion.step_id is not None else None

            await append_run_event(
                session,
                run_id=run_id,
                event_type="assertion.completed",
                payload={
                    "scenarioId": scenario.key,
                    # The step the assertion hangs off, or -- for a scenario with
                    # no steps at all -- the assertion's own key, which is the
                    # fallback the console's script uses for the same case.
                    "stepId": checkpoint_key or assertion.key,
                    "assertionStepId": checkpoint_key,
                    "assertionId": assertion.key,
                    "status": status,
                    "expected": _as_text(assertion.expected),
                    "actual": actual,
                },
            )
            await session.commit()

            if status == FAILED:
                assertion_failed = True

    if deferred is not None:
        step_status = FAILED if assertion_failed else PASSED
        items = await _record_evidence(
            session, run_id=run_id, step=deferred, evidence=deferred_evidence
        )
        await _finish_step(
            session,
            deferred,
            status=step_status,
            now=datetime.now(timezone.utc),
            duration_ms=deferred_duration,
            code=ASSERTION_FAILED if assertion_failed else None,
            detail="one or more assertions failed" if assertion_failed else None,
        )

        payload: dict[str, Any] = {
            "scenarioId": scenario.key,
            "stepId": deferred.key,
            "durationMs": deferred_duration,
        }

        if assertion_failed:
            payload["failure"] = run_failure_dict(
                ASSERTION_FAILED, "one or more assertions failed"
            )
        else:
            payload["evidence"] = items

        await append_run_event(
            session,
            run_id=run_id,
            event_type=("step.failed" if assertion_failed else "step.completed"),
            payload=payload,
        )
        await session.commit()

    if failure is not None:
        await _skip_pending_steps(session, [scenario.id])
        status = FAILED
    elif assertion_failed:
        status = FAILED
    else:
        status = PASSED

    await _finish_scenario(session, scenario, status=status, now=datetime.now(timezone.utc))
    await session.commit()

    return _ScenarioOutcome(
        status=status,
        # A step that failed outright names itself; a scenario that failed on its
        # assertions names the step those assertions belong to, which is the step
        # the console paints red.
        failed_step_key=(
            failed_step.key
            if failed_step is not None
            else (deferred.key if assertion_failed and deferred is not None else None)
        ),
        code=(
            failure.code
            if failure is not None
            else (ASSERTION_FAILED if assertion_failed else None)
        ),
        detail=(
            failure.detail
            if failure is not None
            else ("one or more assertions failed" if assertion_failed else None)
        ),
    )


async def _stop_scenario(
    *, session: AsyncSession, run_id: uuid.UUID, scenario: _Scenario, started_any: bool
) -> None:
    """Leave a scenario the way a cancellation found it.

    The steps that never ran are skipped.  The scenario itself is only marked
    skipped when nothing in it started: a scenario whose steps were already
    running keeps the status it had, which is exactly what the console's own
    reducer does with the same event -- the two views of a cancelled run have to
    agree, or a reload contradicts the page it replaces.
    """
    await _skip_pending_steps(session, [scenario.id])
    await _abandon_step(session, [scenario.id])

    if not started_any:
        await _finish_scenario(
            session, scenario, status=SKIPPED, now=datetime.now(timezone.utc)
        )

    await session.commit()


# --------------------------------------------------------------------------- #
# Executing the run
# --------------------------------------------------------------------------- #


async def _finish_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    started_at: datetime,
    failed: bool,
    code: str | None,
    detail: str | None,
    failed_step_key: str | None,
) -> None:
    """Set the terminal status and announce it, or leave the run alone.

    The UPDATE is conditional on the run still being ``running``, which is what
    makes a cancel final: when it has already won, this matches no row, nothing
    is written and ``run.completed`` / ``run.failed`` is never emitted.  A
    finished-run event after a cancellation would tell every connected client
    that a run it watched stop had in fact passed.
    """
    now = datetime.now(timezone.utc)

    updated = (
        await session.execute(
            update(TestRun)
            .where(TestRun.id == run_id, TestRun.status == RUNNING)
            .values(
                status=FAILED if failed else PASSED,
                finished_at=now,
                error_code=code if failed else None,
                error_message=detail if failed else None,
            )
            .returning(TestRun.id)
        )
    ).scalar_one_or_none()

    if updated is None:
        await session.rollback()
        logger.info("run %s: not finished here, it is no longer running", run_id)
        return

    payload: dict[str, Any] = {
        "finishedAt": _sse_timestamp(now),
        "durationMs": _elapsed_ms(started_at, now),
    }

    if failed:
        payload["failedStepId"] = failed_step_key
        payload["failure"] = run_failure_dict(code or FAILED, detail)

    await append_run_event(
        session,
        run_id=run_id,
        event_type="run.failed" if failed else "run.completed",
        payload=payload,
    )
    await session.commit()

    logger.info("run %s: %s", run_id, FAILED if failed else PASSED)


async def _execute(run_id: uuid.UUID) -> None:
    """One run, from ``queued`` to a terminal state, one committed boundary at a time.

    The snapshot is read once -- it is frozen -- and the run's *status* is read
    again at every boundary, because that one can change underneath.
    """
    async with AsyncSessionLocal() as session:
        facts = await _load_run(session, run_id)

        if facts is None or facts.status != QUEUED:
            logger.info(
                "run %s: not started, its status is %s",
                run_id,
                "gone" if facts is None else facts.status,
            )

            # A cancel that arrived first still owes the run a settled tree: the
            # rows it never touched would otherwise read as "pending" forever.
            if facts is not None and facts.status == CANCELLED:
                await _settle_after_cancel(session, run_id)

            return

        variables = await _load_variables(session, facts.environment_id)
        auth = await _load_auth(session, facts.environment_id)
        scenarios = await _load_tree(session, run_id)

        context = RunExecutionContext(
            run_id=run_id,
            project_id=facts.project_id,
            environment_id=facts.environment_id,
            base_url=facts.base_url,
            variables=variables,
            runtime={},
        )

        started_at = datetime.now(timezone.utc)

        started = (
            await session.execute(
                update(TestRun)
                .where(TestRun.id == run_id, TestRun.status == QUEUED)
                .values(status=RUNNING, started_at=started_at)
                .returning(TestRun.id)
            )
        ).scalar_one_or_none()

        if started is None:
            await session.rollback()
            logger.info("run %s: not started, it is no longer queued", run_id)
            return

        await append_run_event(
            session,
            run_id=run_id,
            event_type="run.started",
            payload={"startedAt": _sse_timestamp(started_at)},
        )
        await session.commit()

        logger.info("run %s: running %d scenario(s)", run_id, len(scenarios))

        failures: list[tuple[str, _ScenarioOutcome]] = []

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            for scenario in scenarios:
                if not await _still_running(session, run_id):
                    await _settle_after_cancel(session, run_id)
                    logger.info("run %s: cancelled before scenario %s", run_id, scenario.key)
                    return

                outcome = await _run_scenario(
                    session=session,
                    scenario=scenario,
                    context=replace(context, current_scenario=scenario.key, current_step=None),
                    auth=auth,
                    client=client,
                )

                if outcome.status == SKIPPED:
                    await _settle_after_cancel(session, run_id)
                    logger.info("run %s: cancelled during scenario %s", run_id, scenario.key)
                    return

                if outcome.status == FAILED:
                    failures.append((scenario.key, outcome))

        first = failures[0][1] if failures else None

        await _finish_run(
            session,
            run_id=run_id,
            started_at=started_at,
            failed=bool(failures),
            code=first.code if first is not None else None,
            detail=(
                "scenario " + failures[0][0] + ": " + (first.detail or "the scenario failed")
                if first is not None and first.detail is not None
                else ("scenario " + failures[0][0] + " failed" if failures else None)
            ),
            failed_step_key=first.failed_step_key if first is not None else None,
        )


async def _fail_run(run_id: uuid.UUID, *, code: str, detail: str) -> None:
    """Record that the executor itself could not finish, safely.

    ``queued`` and ``running`` both qualify: a failure before the run started is
    still a run that will never start, and leaving it queued forever is the one
    outcome nobody can act on.  A ``cancelled`` run is left alone.
    """
    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            started_at = (
                await session.execute(select(TestRun.started_at).where(TestRun.id == run_id))
            ).scalar_one_or_none()

            updated = (
                await session.execute(
                    update(TestRun)
                    .where(TestRun.id == run_id, TestRun.status.in_(_ACTIVE_STATUSES))
                    .values(
                        status=FAILED,
                        finished_at=now,
                        error_code=code,
                        error_message=detail,
                    )
                    .returning(TestRun.id)
                )
            ).scalar_one_or_none()

            if updated is None:
                await session.rollback()
                return

            await append_run_event(
                session,
                run_id=run_id,
                event_type="run.failed",
                payload={
                    "finishedAt": _sse_timestamp(now),
                    "durationMs": _elapsed_ms(started_at, now),
                    "failedStepId": None,
                    "failure": run_failure_dict(code, detail),
                },
            )
            await session.commit()
    except Exception:
        # The failure of the failure path is the end of the line: log it and let
        # the task finish.  Retrying here would be a second executor.
        logger.exception("run %s: the executor failure could not be recorded", run_id)


async def execute_run(run_id: uuid.UUID) -> None:
    """Execute a run.  Never raises: a run is left in a readable state either way.

    The exception is logged in full for whoever is debugging, and the run is
    marked failed with a code and a sentence that contain nothing from the
    traceback -- no SQL, no DSN, no filesystem path, no header.
    """
    try:
        await _execute(run_id)
    except Exception:
        logger.exception("run %s: the executor could not complete this run", run_id)
        await _fail_run(
            run_id,
            code=EXECUTOR_FAILED,
            detail="the executor could not complete this run",
        )


async def schedule_run(run_id: uuid.UUID) -> None:
    """Start executing a run that has just been committed.

    Called by the create path *after* its commit, and never before: the task
    opens its own session and would not see an uncommitted row, so the run would
    fail to start or read a run that does not exist yet.

    ``asyncio.create_task`` rather than FastAPI's ``BackgroundTasks``, for a
    reason this repository can demonstrate: every verification script drives the
    app through ``httpx.ASGITransport`, and Starlette runs background tasks
    before the ASGI call returns -- so ``POST /runs`` would answer 201 only once
    the whole run had finished, and the queued state would be unobservable.
    ``create_task`` returns immediately and the run proceeds alongside.

    The registry keeps a reference so the task cannot be garbage collected
    mid-run, and gives "one executor per run" somewhere to be enforced.
    """
    if os.getenv(EXECUTOR_DISABLED_ENV, "").strip().lower() in ("1", "true", "yes"):
        logger.info("run %s: not scheduled, %s is set", run_id, EXECUTOR_DISABLED_ENV)
        return

    if run_id in _RUNNING_TASKS:
        logger.warning("run %s: an executor is already scheduled", run_id)
        return

    try:
        task = asyncio.create_task(execute_run(run_id), name="run-executor-" + str(run_id))
    except Exception:
        # Scheduling is the one step that can leave a run queued with nothing
        # running it, so it is the one step that fails the run instead.
        logger.exception("run %s: could not be scheduled", run_id)
        await _fail_run(
            run_id,
            code=EXECUTOR_FAILED,
            detail="the run could not be started",
        )
        return

    _RUNNING_TASKS[run_id] = task
    task.add_done_callback(lambda finished, key=run_id: _forget(key, finished))


def _forget(run_id: uuid.UUID, task: asyncio.Task[None]) -> None:
    """Drop a finished task, and say so if it ended badly."""
    _RUNNING_TASKS.pop(run_id, None)

    if task.cancelled():
        logger.warning("run %s: the executor task was cancelled", run_id)
        return

    error = task.exception()

    if error is not None:
        logger.error(
            "run %s: the executor task ended with %s", run_id, type(error).__name__
        )


# --------------------------------------------------------------------------- #
# Startup recovery, phase one: runs that never started
# --------------------------------------------------------------------------- #

RUN_RECOVERY_MAX_AGE_ENV = "RUN_RECOVERY_QUEUED_MAX_AGE_SECONDS"
RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS = 300.0
"""How long a queued run may sit with nothing executing it before it is an orphan.

schedule_run is called by the create path immediately after its commit, so a run
that is still queued some minutes later was queued by a process that is no longer
around -- it either died between the commit and the schedule, or was started with
RUN_EXECUTOR_DISABLED set and never intended to run.

Why a threshold at all: the only two options for an orphan are to execute it or to
close it, and executing it is not recoverable.  A run carries a base URL and an
environment; replaying one days later means really calling whatever that address
answers today, with whatever credentials it holds now.  So the young ones -- the
ones whose queueing process died moments ago -- are re-scheduled, and the old ones
are closed with a failure that says why.  Neither branch ever re-sends a request: a
run that has actually started is running, and this module never writes to a running
row.

The window is not a proof.  Nothing in the schema records which process queued a
run, so no threshold can tell 'orphaned nine seconds ago' from 'queued nine seconds
ago and about to be picked up'.  300 seconds is simply long enough that the second
case cannot happen, because the scheduling call is synchronous with the create
request.  Being wrong in the other direction is the expensive one, and the
threshold is chosen to avoid it.
"""


def recovery_max_age_seconds() -> float:
    """The configured window, or the default when it is unusable.

    Read per call rather than at import: create_app() is a factory precisely so a
    process can choose its environment, and a deployment that edits this should not
    have to be careful about import order.  A value that is not a positive number is
    refused loudly and the default is used -- a typo must not silently turn either
    branch into an unlimited one.
    """
    raw = os.getenv(RUN_RECOVERY_MAX_AGE_ENV, "").strip()

    if raw == "":
        return RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using %s seconds",
            RUN_RECOVERY_MAX_AGE_ENV,
            raw,
            RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS,
        )
        return RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS

    if not math.isfinite(value):
        # inf and nan are refused before the sign test: float("1e999") is inf, and a
        # window of inf would make "age > window" false forever, so recovery would
        # silently stop closing orphans -- the opposite of a typo that is too strict.
        logger.warning(
            "%s=%r is not finite; using %s seconds",
            RUN_RECOVERY_MAX_AGE_ENV,
            raw,
            RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS,
        )
        return RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS

    if value <= 0:
        logger.warning(
            "%s=%r is not positive; using %s seconds",
            RUN_RECOVERY_MAX_AGE_ENV,
            raw,
            RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS,
        )
        return RUN_RECOVERY_MAX_AGE_DEFAULT_SECONDS

    return value


def _orphan_reason(max_age_seconds: float) -> str:
    """Why a run was closed, in a sentence that survives being read later.

    Rendered to the user as-is: executor-failed has no dictionary sentence, so the
    read path falls back to a literal of the code and carries this as the detail.
    It says what happened and under which threshold -- someone looking at a failed
    run months from now has to be able to tell an orphan from a crash.
    """
    window = int(max_age_seconds) if max_age_seconds.is_integer() else max_age_seconds

    return (
        "queued for more than "
        + str(window)
        + "s with no executor: treated as orphaned and closed without running. "
        + "Threshold "
        + RUN_RECOVERY_MAX_AGE_ENV
        + ", decided "
        + _sse_timestamp(datetime.now(timezone.utc))
        + "."
    )


async def _claim_orphaned_queued(
    session: AsyncSession, *, run_id: uuid.UUID, max_age_seconds: float
) -> bool:
    """Close a queued run that never started, if it still qualifies.  One statement.

    Every condition the decision rests on is re-checked here, against the row as the
    database holds it now:

    * status = 'queued' -- not IN (queued, running).  A run another process has
      already claimed is 'running', and this must not touch it.  It is also what
      makes two concurrent recoveries safe: the second blocks on the first one's row
      lock, re-evaluates its WHERE against the committed row and matches nothing.
    * started_at IS NULL -- the claim writes status and started_at together, so a
      non-NULL started_at means something began even if the status disagrees.
    * created_at older than the window, compared by the DATABASE clock.  Reading
      the age in Python and then writing would decide on a value another transaction
      can invalidate between the two statements.
    * no run.started event -- the third independent witness that nothing ran.
      started_at NULL with a run.started row is inconsistent data, and inconsistent
      data is not an orphan; it is left for a human.

    Returns whether this caller is the one that closed it.  False is a normal
    outcome, not an error: it means somebody else got there first.
    """
    already_started = (
        select(RunEvent.id)
        .where(RunEvent.run_id == TestRun.id, RunEvent.event_type == "run.started")
        .exists()
    )

    claimed = (
        await session.execute(
            update(TestRun)
            .where(
                TestRun.id == run_id,
                TestRun.status == QUEUED,
                TestRun.started_at.is_(None),
                TestRun.created_at
                < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, max_age_seconds),
                ~already_started,
            )
            .values(
                status=FAILED,
                finished_at=datetime.now(timezone.utc),
                error_code=EXECUTOR_FAILED,
                error_message=_orphan_reason(max_age_seconds),
            )
            .returning(TestRun.id)
        )
    ).scalar_one_or_none()

    return claimed is not None


async def _close_orphaned_queued(
    run_id: uuid.UUID, *, max_age_seconds: float
) -> bool | None:
    """Claim an orphaned queued run and leave it terminal, in one transaction.

    The claim, the settlement of its unfinished rows and the event are one unit
    because each half is wrong on its own: a failed run whose steps are still
    pending is a page that contradicts itself, and settled steps under a run that
    is still queued is a run nothing will ever finish.

    Three outcomes, and the caller must be able to tell them apart:

    * ``True``  -- this caller claimed the run and the transaction committed.
    * ``False`` -- the conditional UPDATE matched nothing, so another writer got
      there first.  Nothing was written; this is a normal outcome, not a failure.
    * ``None``  -- the transaction raised.  It was rolled back whole, and the
      failure is reported as a failure rather than as somebody else winning a
      race: those two want different sentences in a log and different counters.
    """
    try:
        async with AsyncSessionLocal() as session:
            if not await _claim_orphaned_queued(
                session, run_id=run_id, max_age_seconds=max_age_seconds
            ):
                await session.rollback()
                logger.info(
                    "run %s: not closed here, another writer claimed it first",
                    run_id,
                )
                return False

            await _settle_unfinished(session, run_id)

            # The one writer for run_events, called exactly as the executor and the
            # cancel route call it: no second allocator, no hand-built seq.
            await append_run_event(
                session,
                run_id=run_id,
                event_type="run.failed",
                payload={
                    "finishedAt": _sse_timestamp(datetime.now(timezone.utc)),
                    "durationMs": 0,
                    "failedStepId": None,
                    "failure": run_failure_dict(
                        EXECUTOR_FAILED, _orphan_reason(max_age_seconds)
                    ),
                },
            )
            await session.commit()

        logger.warning(
            "run %s: closed as an orphan, queued for more than %ss",
            run_id,
            max_age_seconds,
        )

        return True
    except Exception:
        logger.exception("run %s: the orphaned run could not be closed", run_id)
        # None, not False: the caller must not report a rolled-back transaction as
        # a lost race.  The rollback itself is the session context manager's.
        return None


async def _queued_age_seconds(run_id: uuid.UUID) -> float | None:
    """How long the run has been queued, by the database clock, or None if gone.

    Computed by PostgreSQL so that the value in Python only ever picks a branch;
    the branch that writes re-derives the comparison itself.
    """
    async with AsyncSessionLocal() as session:
        seconds = (
            await session.execute(
                select(func.extract("epoch", func.now() - TestRun.created_at)).where(
                    TestRun.id == run_id
                )
            )
        ).scalar_one_or_none()

    return None if seconds is None else float(seconds)


async def _recover_one(run_id: uuid.UUID, *, max_age_seconds: float) -> str:
    """Decide what one non-terminal run needs, and do only that.

    running is deliberately absent from every branch below.  A run in that state
    may be executing in this process, in another one, or nowhere -- and nothing in
    the schema tells them apart, so the only safe action is none.  _RUNNING_TASKS
    is not evidence either: it is this process's own memory, and a run missing from
    it may be running happily somewhere else.  Reliable recovery of 'running' needs
    an executor lease or heartbeat, which this build does not have.

    Returns a word describing what happened, for the caller to count.
    """
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(TestRun.status, TestRun.started_at).where(TestRun.id == run_id)
                )
            ).one_or_none()

            if row is None:
                return "missing"

            status, started_at = row

            if status not in _ACTIVE_STATUSES:
                return "terminal"

            if status == RUNNING:
                logger.info(
                    "run %s: running, left alone (recovery does not judge liveness)",
                    run_id,
                )
                return "running"

            started_event = (
                await session.execute(
                    select(RunEvent.id)
                    .where(
                        RunEvent.run_id == run_id,
                        RunEvent.event_type == "run.started",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

        if started_at is not None or started_event is not None:
            logger.warning(
                "run %s: queued but shows signs of having started; left for a human",
                run_id,
            )
            return "inconsistent"

        # Its own connection, its own transaction: the closure re-checks the age and
        # the status against the row as it stands, so this comparison decides only
        # which statement to run, never the outcome.
        age = await _queued_age_seconds(run_id)

        if age is None:
            return "gone"

        if age <= max_age_seconds:
            await schedule_run(run_id)
            return "rescheduled"

        closed = await _close_orphaned_queued(run_id, max_age_seconds=max_age_seconds)

        if closed is None:
            return "error"
        return "closed" if closed else "lost-race"
    except Exception:
        logger.exception("run %s: recovery could not decide what to do with it", run_id)
        return "error"


async def recover_queued_runs() -> dict[str, int]:
    """Phase one of startup recovery: nothing but runs that never started.

    Called from the application lifespan, once, before the server answers requests.
    It is safe to call again at any time and safe to call from several processes at
    once -- every decision that writes is made by a conditional UPDATE in the
    database, so the losers of a race are no-ops.

    It is also safe to call when there is nothing to do, which is the normal case:
    a process that shut down cleanly leaves no non-terminal runs.

    RUN_EXECUTOR_DISABLED turns the whole thing off, matching schedule_run.  The
    verification scripts set it because their runs are fixtures that must stay
    exactly as created; recovery that ignored it would rewrite them the next time a
    real server started against that database.

    Nothing here raises.  Recovery is a repair, not a prerequisite: a database that
    is unreachable, a row that cannot be read and a run that cannot be closed all
    end in a log line, and the application starts anyway.
    """
    counts: dict[str, int] = {}

    if os.getenv(EXECUTOR_DISABLED_ENV, "").strip().lower() in ("1", "true", "yes"):
        logger.info(
            "run recovery: skipped, %s is set",
            EXECUTOR_DISABLED_ENV,
        )
        return counts

    max_age_seconds = recovery_max_age_seconds()

    try:
        async with AsyncSessionLocal() as session:
            candidates = list(
                (
                    await session.execute(
                        select(TestRun.id)
                        .where(TestRun.status.in_(_ACTIVE_STATUSES))
                        .order_by(TestRun.created_at)
                    )
                ).scalars()
            )
    except Exception:
        logger.exception("run recovery: the non-terminal runs could not be listed")
        return counts

    for run_id in candidates:
        outcome = await _recover_one(run_id, max_age_seconds=max_age_seconds)
        counts[outcome] = counts.get(outcome, 0) + 1

    if counts:
        logger.info("run recovery: %s", counts)

    return counts
