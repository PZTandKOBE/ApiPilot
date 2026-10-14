"""The Run service: ``POST /api/projects/{project_id}/runs``.

A run is the first thing this service writes that the browser cannot compute
for itself, and it writes a lot of it.  ``test_runs`` has four NOT NULL foreign
keys -- ``project_id``, ``plan_id``, ``spec_id``, ``environment_id`` -- and none
of the rows they point at exist on a fresh database.  Plans are generated in the
browser; specs are parsed in the browser; nothing has ever written either to
PostgreSQL.  So creating one run means materialising the spec, the whole plan
tree, and the execution snapshot, in one transaction, or writing nothing at all.

Four rules shape the code below, and each of them is a decision rather than a
preference.

**1. The transaction is all-or-nothing, and it is committed here.**
``get_session()`` rolls back on an exception and commits nothing on success, so
a missing ``commit()`` produces a 201 that wrote nothing, with no error
anywhere.  Equally, a ``test_runs`` row whose ``run_scenarios`` are missing is
worse than no run: ``frontend/src/utils/runState.ts`` updates its rows by id
equality with no positional fallback *and* has no insert path, so a run whose
tree is half-written renders as a shell whose rows never update and never
raises.

**2. The approval gate is a mirror, not an authority.**  ``plan.status``
arrives in the request body, so checking it here enforces the *same rule the
client already enforces* (``frontend/src/stores/runs.ts`` refuses to send a
non-approved plan) and stops a caller from bypassing the browser.  It is **not**
database-backed approval authority, because the plan row this service writes is
itself built from the same untrusted payload.  There is no Plan Approval API
yet; when there is one, this check should read the stored ``status`` instead.
Nothing in this module may describe the current check as verification.

**3. Variable names are persisted; values are not.**  ``test_runs.variable_keys``
is a sorted list of names.  The values in ``RunCreateRequest.variables`` are
secrets in flight, are used by nothing here, and must never be written to a
column, an error body or a log line.

**4. Plan rows are reused, not rewritten.**  ``UNIQUE(project_id, public_id)``
with get-or-create means the second run of a plan attaches to the same
``test_plans`` row.  The plan tree is *not* re-materialised on the reuse path,
so a reused ``test_plans`` row may no longer match the payload an earlier run
was created from.  That is deliberate, and it is the reason
``test_runs.plan_name`` is a frozen copy rather than a join.

The reuse path is also the only path that reads a step's request target out of
the stored plan: a create that states no method or path for a ``request`` step
gets them from ``test_steps.config``, so a plan the server already holds stays
executable on its own.  See ``_config_target`` / ``_request_target``.

**5. Reads are a constant number of queries, whatever the page size.**  A run
list needs four things per row that ``test_runs`` does not store: the plan's
``public_id``, the spec's slug, the environment's ``public_id`` and seven
counts.  Each of those is a join or an aggregate away, and doing them per row is
the N+1 this service exists to not have.  ``list_runs`` issues three statements
for any page -- the project lookup, the page itself, and one grouped
aggregation -- and the aggregation covers the whole page at once.  See
``_fetch_run_page`` and ``_fetch_run_counts``.

**6. The detail is seven statements, and the order is the database's.**  A run
detail is the same row as a list item plus a whole tree, so ``get_run_detail``
reads the tree as *sets*: the run row, its scenarios, steps, assertions,
evidence, the seven counts and the event high-water mark are one statement each,
never one per row, and no relationship is ever walked -- every ``run_*``
relationship is ``lazy="raise"`` and stays that way.  A run with no scenarios
costs three of the seven, because it has no tree to read and its summary is
structurally zeroes.
Nothing is ordered by PostgreSQL's default: scenarios and steps sort on
``sort_order`` with their stable key as the tiebreaker, assertions -- which have
no ``sort_order`` column -- sort on ``assertion_key``, and evidence on
``(created_at, id)``.  A tiebreaker is not decoration: the frontend matches rows
by id equality with no positional fallback, so two rows that swap places between
two reads are two rows the page updates in the wrong order.

Several columns are *wider* than the contract they feed, and each is narrowed
here rather than at the edge.  ``run_assertions.expected_value`` / ``actual_value``
are JSONB while ``RunAssertion.expected`` / ``actual`` are ``str``, and
``run_assertions.description`` / ``run_evidence.label`` are nullable JSONB while
the contract wants a ``LocalizedText``.  A response model that raises on data
the database permits is a 500 on a page that has an answer, so ``_as_text`` and
``_localized`` make both total.  Every other column is copied as stored: the
create path writes them from the plan in exactly the shape the contract uses.

``run_steps.endpoint_id`` is a UUID foreign key while ``RunStep.endpointId`` is the
endpoint's *public* id (``ep_post_api_orders``).  The steps query therefore joins
``api_endpoints`` to read the public id rather than stringifying the key it
stores: an internal UUID in that field would be a value the client cannot tell
apart from a real one, in a field it does not render today.

**7. Cancel asks the database to make the transition, and reads the answer.**
``cancel_run`` does not read a status and then decide -- it issues
``UPDATE test_runs SET status = 'cancelled', finished_at = now() WHERE id = :id
AND status IN ('queued', 'running')`` and reads the answer off the row count.
Two cancels arriving together therefore serialise on that row instead of racing
over it: the second matches nothing, writes no event, and answers 200 with the
state the first one produced -- which is the same answer cancelling an
already-terminal run gets.  The event goes in the same transaction as the
update, so the snapshot (``GET /api/runs/{id}``) and the stream cannot disagree
about whether a run was cancelled, and a body that cannot be built rolls the
whole thing back rather than leaving a cancelled run behind an error.

The cancel path is the first writer of ``run_events`` in this service, and it
writes one row that nothing reads yet -- there is no stream.  It is still worth
writing: ``lastSeq`` is already part of the detail contract, and a cancellation
that left the high-water mark alone would make the next reader replay a tail
that no longer describes the run.

**8. Replay reads, and only reads.**  ``get_run_events`` is the one endpoint
here that exists purely to hand back what a writer stored.  It filters on
``seq`` (inclusive) and orders on ``seq`` -- the run's own sequence, which
``UNIQUE(run_id, seq)`` makes total -- and it returns the ``payload`` column
untouched rather than re-deriving a stream frame the frontend has not fixed yet.
Two statements whatever the run holds: the existence check, and the events.  A
run that exists with no events is ``200`` and ``[]``, which is a different
answer from the ``404`` a run that does not exist gets, and the endpoint must
never merge the two.

``fromSeq`` is inclusive, so ``fromSeq=3`` replays 3 onwards: a client resuming
from the high-water mark ``GET /api/runs/{id}`` handed it has to receive the
event at that mark, not the one after it.

**9. The live stream reads the same rows the replay does.**  ``stream_run_events``
is a polling loop over ``run_events`` -- no queue, no broker, no second source of
truth: an event is live because a writer committed it, which is also what makes
it replayable, so the two paths cannot disagree about what happened.  One
statement per pass returns the run's status *and* whatever it has said since the
last frame, so an idle connection costs one indexed read per interval rather
than a query per question.  The loop closes when the run is finished and drained,
and it asks the caller between passes whether the client is still there, so
someone who walks away stops the queries instead of leaving them running.

The stream's frame is the frontend's ``RunEvent`` -- ``eventType`` as ``type``,
the payload's fields lifted to the top level -- while replay returns the row's
shape.  That difference is the contract, not an oversight: replay hands back what
was stored, a stream hands the client something it can fold.  See
``stream_event`` for what happens to a payload the union cannot express.

Known latent issue, recorded rather than fixed: ``test_runs.environment_id`` is
nullable ``SET NULL`` while ``RunResponse.environment_id`` is a required
``str``.  Deleting an environment would null the column and make the *read*
path unable to build a response -- a 500 on data that already exists.  Nothing
deletes environments today, and no route can: there is no environment CRUD.

``list_runs`` is where that issue stops being theoretical, and it resolves it in
the one direction that does not touch the wire contract: the run is *not*
silently dropped from the page and the id is *not* invented.  A listed run whose
environment row is gone raises a 500 naming the run, because the alternative --
a list that quietly omits runs -- is the failure nobody notices.  Fixing it
properly means either a nullable response field (a frontend contract change) or
a snapshot column (a migration); both are out of scope, so this note is the
whole of the change.  ``get_run_detail`` inherits that policy rather than
re-deciding it: both read paths build their body through ``_run_fields``, so
one run answers the question once, and answers it the same way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Row, Select, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import SQLSTATE_UNIQUE_VIOLATION, AppError, constraint_of
from backend.db.database import AsyncSessionLocal
from backend.db.models.agent import TestAssertion, TestPlan, TestScenario, TestStep
from backend.db.models.project import ApiEndpoint, ApiSpec, Environment, Project
from backend.db.models.result import (
    RunAssertion,
    RunEvidence,
    RunEvent,
    RunScenario,
    RunStep,
    TestRun,
)
from backend.schemas.common import LiteralMessage, LocalizedMessage, LocalizedText
from backend.schemas.run import (
    PlanPayload,
    PlanScenario,
    RunAssertionResponse,
    RunCancelResponse,
    RunCreateRequest,
    RunDetailResponse,
    RunEventResponse,
    RunEvidenceResponse,
    RunFailureResponse,
    RunListItem,
    RunResponse,
    RunScenarioResponse,
    RunStepResponse,
    RunSummaryResponse,
)
from backend.services.spec_identity import (
    DocumentFacts,
    SpecIdentity,
    derive_spec_identity,
    probe_document,
    spec_id_for,
)

__all__ = [
    "cancel_run",
    "create_run",
    "get_run_detail",
    "get_run_events",
    "list_runs",
    "append_run_event",
    "resolve_run_for_stream",
    "run_failure_dict",
    "stream_run_events",
]

logger = logging.getLogger(__name__)

SSE_POLL_INTERVAL_SECONDS = 0.5
"""How long a stream waits between two reads of ``run_events``.

The simple polling this phase chose over a broker: one indexed read per interval
per connection, no LISTEN/NOTIFY, no queue, no second source of truth.  The
number is a constant rather than a literal inside the loop so there is one place
to change it, and a test may rebind it: it is read when a stream starts, not
captured in a default argument.
"""

SSE_HEARTBEAT_SECONDS = 30.0
"""How long a quiet stream may go before it says ``: ping``.

Long enough that a healthy connection is not chatty and short enough that a proxy
or a load balancer does not decide an idle connection is a dead one.  Half a
second of polling is not a heartbeat -- it is a query.
"""

_SSE_KEEPALIVE = ": ping\n\n"
"""The heartbeat frame: an SSE comment.

A comment, not an event: it must not appear in ``run_events``, must not take a
``seq``, and must not be readable as a ``RunEvent`` by the client -- which is
exactly what a line starting with a colon is.
"""

_TERMINAL_STATUSES = frozenset({"passed", "failed", "cancelled"})
"""The three states a run does not leave.

A stream closes once the run is in one of them *and* every event that exists has
been sent.  A status outside the vocabulary -- including one this service has
never heard of -- is not treated as terminal: ending a live connection is the
expensive mistake, and waiting one more interval costs a read.
"""

_CREATE_FAILED = "console.runs.errors.createFailed"
_NOT_APPROVED = "console.runs.errors.notApproved"
_LIST_FAILED = "console.runs.errors.loadFailed"
_NOT_FOUND = "console.runs.errors.notFound"
_CANCEL_FAILED = "console.runs.errors.cancelFailed"

_CANCELLABLE_STATUSES: tuple[str, ...] = ("queued", "running")
"""The two states a cancel is allowed to leave.

Everything else in ``test_runs.status`` -- ``passed``, ``failed``,
``cancelled`` -- is terminal, and cancelling a terminal run is not a transition:
it is the same run, returned again.  This tuple is what the conditional UPDATE
matches on, so it is also the module's definition of "already finished"; a
status it does not name and that is not terminal either is data outside the
vocabulary the API declares, and it is answered the same way -- no transition,
return what is there.  Treating an unknown value as cancellable would rewrite a
state nobody has defined.

Named rather than inlined because the same two words decide three things: the
UPDATE's WHERE clause, whether an event is written, and what the 200 body means.
"""

RUN_CANCELLED_EVENT = "run.cancelled"
"""The event name, spelled as ``RUN_EVENT_NAMES`` in ``frontend/src/types/run.ts``.

One of the eight names the frontend declares closed, and the one its reducer
reads as "the run stopped because it was stopped" -- as opposed to
``run.completed`` / ``run.failed``, the other two ways a run ends.
"""

# The two constraints a *concurrent* create can trip.  Both are the
# get-or-create race: two requests for the same (project, slug) or the same
# (project, plan public_id) that both saw "not present" and both inserted.  A
# 409 is honest -- the caller can retry and the retry will reuse.
_RACE_CONSTRAINTS = frozenset(
    {"uq_test_plans_project_public_id", "uq_api_specs_project_slug"}
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def _create_failed(status_code: int, **details: Any) -> AppError:
    """Every create-path failure the frontend cannot tell apart, in one place.

    The five members of ``RunErrorCode`` in the frontend leave no room for
    "project not found", "environment not found" or "spec conflict", and the
    brief forbids new message keys -- so all of them collapse onto
    ``create-failed`` / ``console.runs.errors.createFailed``.  The distinction
    survives in ``details``, which is logged and never rendered.
    """
    return AppError(
        status_code,
        code="create-failed",
        message_key=_CREATE_FAILED,
        details=details or None,
    )


def _list_failed(status_code: int, **details: Any) -> AppError:
    """The read path's one failure, in the envelope the frontend already renders.

    ``code`` is ``run-not-found`` because it is the only member of the frontend's
    closed ``RunErrorCode`` union that can describe a resource being absent --
    there is no ``project-not-found`` and no ``load-failed``.  What the user
    actually reads is ``messageKey``, and ``console.runs.errors.loadFailed``
    ("The run could not be loaded.") is the sentence that is true of a list that
    could not be produced.  The mismatch is a recorded gap, not a decision: the
    status-code / code / messageKey mapping table is still undefined on the
    frontend side (``frontend/docs/phase-6.2-backend-rest-contract.md`` §16).
    """
    return AppError(
        status_code, code="run-not-found", message_key=_LIST_FAILED, details=details or None
    )


def _translate_integrity_error(exc: IntegrityError) -> AppError:
    """Turn a constraint violation into an ``AppError``.

    Called *after* the rollback (see :func:`create_run`) -- the caller must not
    touch the session before rolling back, because a failed statement leaves
    the transaction aborted and every later query raises ``25P02``.

    The constraint name and SQLSTATE come from :func:`constraint_of`, which
    reads them off the exception objects.  **The message text is never
    parsed**: this PostgreSQL instance emits localised (Chinese) messages, and
    SQLAlchemy prefixes them with the exception's class name, so any regex on
    English prose fails here.
    """
    name, sqlstate = constraint_of(exc)

    if sqlstate == SQLSTATE_UNIQUE_VIOLATION and name in _RACE_CONSTRAINTS:
        return _create_failed(409, constraint=name, sqlstate=sqlstate)

    return _create_failed(500, constraint=name, sqlstate=sqlstate)


# --------------------------------------------------------------------------- #
# Pre-flight checks -- all of them run before the first statement
# --------------------------------------------------------------------------- #


def _display_name(name: LocalizedText) -> str:
    """The value the ``notApproved`` sentence interpolates.

    ``console.runs.errors.notApproved`` is
    ``"“{plan}” has to be approved before it can run."`` -- a sentence with a
    placeholder, so ``params`` must be present and non-null or the frontend's
    ``interpolate()`` throws ``TypeError`` and the user gets a blank page.

    The client sends ``localize(plan.name)``: the *translated* text at the
    moment of refusal.  The server cannot translate -- it holds no dictionary
    -- so it sends the i18n key for an authored name and the literal for a
    generated one.  That is a real divergence from what the browser would have
    shown, and the closest available approximation.
    """
    if isinstance(name, LocalizedMessage):
        return name.key
    return name.text


def _check_approval(plan: PlanPayload) -> None:
    """Refuse anything that is not approved, before touching the database."""
    if plan.status == "approved":
        return

    raise AppError(
        409,
        code="not-approved",
        message_key=_NOT_APPROVED,
        params={"plan": _display_name(plan.name)},
        details={"status": plan.status},
    )


def _mismatch(field: str, expected: str, received: str) -> AppError:
    return _create_failed(400, field=field, expected=expected, received=received)


def _check_identity(*, project_id: str, payload: RunCreateRequest) -> None:
    """The five places a project or spec identity is stated must agree.

    ``RunCreateRequest`` carries the project id in the URL *and* in the body,
    the spec id twice, and the plan id twice.  Nothing in the schema ties any
    pair together, so a client can send a plan for one spec and a spec id for
    another, and the result is a ``test_runs`` row whose ``spec_id`` does not
    describe the plan it ran.

    Writing that row would be worse than refusing it: the ids are what the
    *next* request will use to find these rows again, so an inconsistent pair
    creates a duplicate spec or plan on the retry.
    """
    plan = payload.plan

    if payload.project_id != project_id:
        raise _mismatch("projectId", project_id, payload.project_id)

    if plan.project_id != payload.project_id:
        raise _mismatch("plan.projectId", payload.project_id, plan.project_id)

    if plan.spec_id != payload.spec_id:
        raise _mismatch("plan.specId", payload.spec_id, plan.spec_id)

    if plan.id != payload.plan_id:
        raise _mismatch("plan.id", payload.plan_id, plan.id)


def _check_spec_identity(*, payload: RunCreateRequest, identity: SpecIdentity) -> None:
    """When the slug was recomputed, the client's ``specId`` has to match it.

    ``verified`` is ``False`` for an untitled or non-JSON document, where the
    slug was taken from the client's id because the derivation needs the
    uploaded filename, which the request does not carry.  There is nothing to
    compare in that case -- and treating "could not check" as "checked" is the
    one outcome that would be worse than either.
    """
    if not identity.verified:
        return

    expected = spec_id_for(identity.slug)
    if expected != payload.spec_id:
        raise _mismatch("specId", expected, payload.spec_id)


def _check_lengths(
    *, payload: RunCreateRequest, facts: DocumentFacts, identity: SpecIdentity
) -> None:
    """Refuse anything that would not fit its column.

    PostgreSQL raises ``StringDataRightTruncation`` (SQLSTATE 22001) for an
    over-long value, which surfaces as an unattributed 500.  The ids here are
    built by the generator from endpoint *paths*, so ``scenario_smoke_get_...``
    against a deep route can genuinely reach 100 characters -- it is a payload
    problem, and it should read like one.
    """
    plan = payload.plan
    name = facts.title or identity.slug

    violations: list[dict[str, Any]] = []

    def check(field: str, value: str | None, limit: int) -> None:
        if value is not None and len(value) > limit:
            violations.append({"field": field, "limit": limit, "length": len(value)})

    check("baseUrl", payload.base_url, 1000)
    check("planId", payload.plan_id, 255)
    check("api_specs.name", name, 200)
    check("api_specs.slug", identity.slug, 255)

    for scenario in plan.scenarios:
        check("scenario.id", scenario.id, 100)
        for step in scenario.steps:
            check("step.id", step.id, 100)
            check("step.path", step.path, 1000)
            check("step.produces", step.produces, 255)
        for assertion in scenario.assertions:
            check("assertion.id", assertion.id, 100)
            check("assertion.target", assertion.target, 255)

    if violations:
        raise _create_failed(400, violations=violations)


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #


async def _find_project(session: AsyncSession, public_id: str) -> Project | None:
    """``projects.public_id`` is the one public id that is globally unique.

    Returns ``None`` rather than raising so that the two callers can report the
    same absence differently: creating a run under a project that does not exist
    is a failed create, and listing one is a failed load.
    """
    return (
        await session.execute(select(Project).where(Project.public_id == public_id))
    ).scalar_one_or_none()


async def _lookup_project(session: AsyncSession, public_id: str) -> Project:
    project = await _find_project(session, public_id)

    if project is None:
        raise _create_failed(404, resource="project", publicId=public_id)

    return project


async def _lookup_environment(
    session: AsyncSession, project_id: uuid.UUID, public_id: str
) -> Environment:
    """Scoped to the project: an environment's public id is only unique there."""
    environment = (
        await session.execute(
            select(Environment).where(
                Environment.project_id == project_id,
                Environment.public_id == public_id,
            )
        )
    ).scalar_one_or_none()

    if environment is None:
        raise _create_failed(404, resource="environment", publicId=public_id)

    return environment


# --------------------------------------------------------------------------- #
# Spec
# --------------------------------------------------------------------------- #


async def _get_or_create_spec(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    spec_document: str,
    facts: DocumentFacts,
    identity: SpecIdentity,
) -> ApiSpec:
    """Find the spec by ``(project_id, slug)``, or store it.

    ``api_specs`` has no ``public_id``, so the ``specId`` on the request is not
    a column value -- it is ``spec_`` + ``slug``, and the slug comes from the
    document.  Re-uploading the same file therefore reuses the row, which is
    the point of a content-derived identity.

    Only three columns are filled beyond the identity: ``content`` is the
    document verbatim, and ``content_format`` / ``spec_type`` are the two facts
    ``detectFormat`` extracts.  ``version``, ``filename`` and ``server_url``
    stay NULL -- they live in the document, and recovering them would mean a
    YAML parser this service does not have.  ``source`` falls back to its
    server default of ``'upload'``: the request says nothing about provenance.
    """
    spec = (
        await session.execute(
            select(ApiSpec).where(
                ApiSpec.project_id == project_id, ApiSpec.slug == identity.slug
            )
        )
    ).scalar_one_or_none()

    if spec is not None:
        return spec

    spec = ApiSpec(
        project_id=project_id,
        name=facts.title or identity.slug,
        slug=identity.slug,
        spec_type=facts.spec_type,
        content_format=facts.content_format,
        # version / filename / server_url stay NULL.  The first two live in the
        # document (behind a parser this service does not have) and the third
        # in a `servers` block it does not read; `project.py` keeps the column
        # because `openapi-3 + yaml` is a real combination it must be able to
        # describe, not because every writer fills it.
        content=spec_document,
    )
    session.add(spec)
    await session.flush()

    return spec


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


class _PlanMaterialization:
    """The plan row, plus the ids the run rows point back at.

    Keyed by the *stable* keys, because that is the only join the payload and
    the stored tree share -- the payload carries no UUIDs.  Steps and
    assertions are keyed by ``(scenario_key, own_key)`` to match the
    ``UNIQUE(scenario_id, ...)`` scope they are stored under.

    ``step_configs`` carries each stored step's ``config`` blob alongside its id,
    because the request target lives there and the run snapshot may have to read
    it back.  It is filled from the rows just written on the create path and from
    the rows just read on the reuse path, so both paths can answer with it.
    """

    __slots__ = ("plan_id", "assertion_ids", "scenario_ids", "step_configs", "step_ids")

    def __init__(self, plan_id: uuid.UUID) -> None:
        self.plan_id = plan_id
        self.scenario_ids: dict[str, uuid.UUID] = {}
        self.step_ids: dict[tuple[str, str], uuid.UUID] = {}
        self.step_configs: dict[tuple[str, str], dict[str, Any]] = {}
        self.assertion_ids: dict[tuple[str, str], uuid.UUID] = {}


# --------------------------------------------------------------------------- #
# The step's request target
#
# ``test_steps`` describes a *test-plan operation*, not an HTTP request: the
# plan-side table has no method and no path column, and that is deliberate.  The
# pair therefore travels in the one column whose shape already varies by
# ``step_type`` -- ``config`` -- written when the plan is materialised and read
# back when a create does not carry it.  Two functions, one direction each.
# --------------------------------------------------------------------------- #

# The widths ``run_steps.method`` / ``run_steps.path`` can hold.  The payload
# side is closed by ``HttpMethod`` and checked by ``_check_lengths``; a value
# read out of JSONB has passed neither check.
_METHOD_LIMIT = 20
_PATH_LIMIT = 1000


def _config_target(step: PlanStep) -> dict[str, Any]:
    """The ``test_steps.config`` a plan step materialises to.

    Only a ``request`` step has a request to describe, so only it carries the
    pair; ``extract`` and ``assert`` steps keep the empty object they have always
    had, and a non-request step that names a method anyway is not turned into a
    request by this function.

    Keys are written only when the payload has a value.  ``{"method": null}``
    would be a key that looks like data and reads like absence, and the column's
    own default is already the empty object.
    """
    if step.kind != "request":
        return {}

    config: dict[str, Any] = {}

    if step.method is not None:
        config["method"] = step.method
    if step.path is not None:
        config["path"] = step.path

    return config


def _config_text(config: dict[str, Any], key: str, limit: int) -> str | None:
    """One string out of a JSONB blob, or ``None`` if it is not usable.

    ``config`` is JSONB, so nothing in the database stops a writer from putting a
    number, a nested object or an essay in it.  A value that is not a non-empty
    string within its column's width is treated as absent rather than handed to
    a driver that would raise on it.
    """
    value = config.get(key)

    if isinstance(value, str) and 0 < len(value) <= limit:
        return value

    return None


def _request_target(
    step: PlanStep, config: dict[str, Any]
) -> tuple[str | None, str | None]:
    """The method and path the run snapshot should carry for one step.

    **The submitted plan wins; the stored plan is the fallback.**  A create that
    carries the whole tree -- what the client sends today -- therefore snapshots
    exactly what it always did, byte for byte.  A create that names a plan the
    server already holds can leave the pair out, and it comes back from
    ``test_steps.config``: that is what makes "plan persisted first, run created
    later" possible without the plan-side table growing two columns.

    Only ``request`` steps consult the stored plan.  The other kinds have no
    request, so their snapshot fields stay exactly as the payload stated them.
    """
    if step.kind != "request":
        return step.method, step.path

    method = step.method
    if method is None:
        method = _config_text(config, "method", _METHOD_LIMIT)

    path = step.path
    if path is None:
        path = _config_text(config, "path", _PATH_LIMIT)

    return method, path


async def _get_or_create_plan(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    spec_id: uuid.UUID,
    plan: PlanPayload,
) -> _PlanMaterialization:
    """Reuse the stored plan for ``(project_id, public_id)``, or write the tree.

    ``public_id`` is the *whole* ``planId`` string -- ``plan_orders_api_1a2b``
    -- not the slug with the prefix stripped.  The plan id is derived from the
    spec's slug, but it is stored as its own value and stripped only in the
    spec direction, where there is no column to strip it for.

    **Reuse does not rewrite.**  A second run of the same plan attaches to the
    existing row and the existing tree, and the ids it resolves are looked up
    by stable key.  A payload scenario the stored plan has never seen gets no
    ``source_scenario_id`` rather than a fabricated one.

    Writing is delegated to ``_create_plan_tree``, which the agent pipeline also
    calls: one writer for the four plan-side tables, two callers that differ only
    in whether they set ``agent_task_id``.
    """
    existing = (
        await session.execute(
            select(TestPlan).where(
                TestPlan.project_id == project_id, TestPlan.public_id == plan.id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return await _load_plan_tree(session, existing.id)

    return await _create_plan_tree(
        session,
        project_id=project_id,
        spec_id=spec_id,
        plan=plan,
        agent_task_id=None,
    )


async def _create_plan_tree(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    spec_id: uuid.UUID,
    plan: PlanPayload,
    agent_task_id: uuid.UUID | None = None,
) -> _PlanMaterialization:
    """Write the plan row and its tree: the only writer of these four tables.

    Split out of the get-or-create wrapper because two callers write a plan for
    different reasons.  A run create attaches to whatever is already stored; the
    agent pipeline writes the plan it has just generated, together with the task
    it came from.  `agent_task_id` is the only difference between them, and
    `None` is what the run path has always written.
    """
    stored = TestPlan(
        agent_task_id=agent_task_id,
        project_id=project_id,
        spec_id=spec_id,
        public_id=plan.id,
        name=plan.name.model_dump(),
        # `goal` has no column of its own; `description` is the only prose field
        # on the table and the only place it can go.
        description=plan.goal.model_dump(),
        status=plan.status,
        risk_level=plan.risk_level,
        source=plan.source,
        approved_at=plan.approved_at,
        rejected_at=plan.rejected_at,
        rejection_reason=plan.rejection_reason,
    )
    session.add(stored)
    await session.flush()

    materialization = _PlanMaterialization(stored.id)

    for scenario in plan.scenarios:
        stored_scenario = TestScenario(
            plan_id=stored.id,
            scenario_key=scenario.id,
            name=scenario.name.model_dump(),
            description=scenario.description.model_dump(),
            expected=scenario.expected.model_dump(),
            risk_level=scenario.risk_level,
            sort_order=scenario.index,
        )
        session.add(stored_scenario)
        await session.flush()
        materialization.scenario_ids[scenario.id] = stored_scenario.id

        for step in scenario.steps:
            # The request target goes in `config`: the plan-side table has no
            # method or path column, and this is the write half of the pair that
            # `_request_target` reads back.
            config = _config_target(step)
            stored_step = TestStep(
                scenario_id=stored_scenario.id,
                step_key=step.id,
                description=step.description.model_dump(),
                step_type=step.kind,
                # No api_endpoints are materialised, so there is nothing for
                # this to point at.  The string `endpointId` on the plan is the
                # frontend's own id (`get_/orders/{id}`), not a UUID, and
                # nothing in the client renders the field.
                endpoint_id=None,
                # `depends_on` has no counterpart in the plan payload.
                depends_on=None,
                config=config,
                produces=step.produces,
                consumes=step.consumes,
                sort_order=step.index,
            )
            session.add(stored_step)
            await session.flush()
            materialization.step_ids[(scenario.id, step.id)] = stored_step.id
            materialization.step_configs[(scenario.id, step.id)] = config

        for assertion in scenario.assertions:
            stored_assertion = TestAssertion(
                scenario_id=stored_scenario.id,
                # `TestAssertion` in the frontend has no `stepId`, so every
                # assertion a plan can express is scenario-level.  That is why
                # `test_assertions.scenario_id` is the only anchor this row has
                # and why it is NOT NULL.
                step_id=None,
                assertion_key=assertion.id,
                assertion_type=assertion.kind,
                target=assertion.target,
                expected_value=assertion.expected,
                description=assertion.description.model_dump(),
            )
            session.add(stored_assertion)
            await session.flush()
            materialization.assertion_ids[(scenario.id, assertion.id)] = stored_assertion.id

    return materialization


async def _load_plan_tree(session: AsyncSession, plan_id: uuid.UUID) -> _PlanMaterialization:
    """Resolve a stored plan's stable keys to their row ids.

    Column selects rather than entity loads: the run rows only need the ids,
    and the plan-side relationships are ``lazy="raise"``, so loading entities
    would either raise or require loader options that say nothing new.
    """
    materialization = _PlanMaterialization(plan_id)

    scenarios = (
        await session.execute(
            select(TestScenario.id, TestScenario.scenario_key).where(
                TestScenario.plan_id == plan_id
            )
        )
    ).all()
    materialization.scenario_ids = {key: row_id for row_id, key in scenarios}

    if not scenarios:
        return materialization

    key_by_id = {row_id: key for row_id, key in scenarios}
    scenario_ids = list(key_by_id)

    steps = (
        await session.execute(
            select(
                TestStep.id,
                TestStep.scenario_id,
                TestStep.step_key,
                TestStep.config,
            ).where(TestStep.scenario_id.in_(scenario_ids))
        )
    ).all()
    materialization.step_ids = {
        (key_by_id[scenario_id], step_key): row_id
        for row_id, scenario_id, step_key, _config in steps
    }
    # Read, not assumed: `config` is JSONB, so a row written by something other
    # than this service may hold any JSON at all, or even a bare `null`.
    materialization.step_configs = {
        (key_by_id[scenario_id], step_key): config if isinstance(config, dict) else {}
        for _row_id, scenario_id, step_key, config in steps
    }

    assertions = (
        await session.execute(
            select(
                TestAssertion.id, TestAssertion.scenario_id, TestAssertion.assertion_key
            ).where(TestAssertion.scenario_id.in_(scenario_ids))
        )
    ).all()
    materialization.assertion_ids = {
        (key_by_id[scenario_id], assertion_key): row_id
        for row_id, scenario_id, assertion_key in assertions
    }

    return materialization


# --------------------------------------------------------------------------- #
# The run snapshot
# --------------------------------------------------------------------------- #


def _checkpoint_step_key(scenario: PlanScenario) -> str | None:
    """Port of ``checkpointOf`` from ``frontend/src/services/mock/run/script.ts``.

    A scenario's assertions hang off the step that decides them: the first
    ``assert``-kind step, or the scenario's last step, or nothing at all for an
    empty scenario.  ``RunAssertion.stepId`` is nullable and the frontend
    computes this same value when it builds a run locally, so a server that
    always wrote NULL would disagree with the model it is replacing.
    """
    for step in scenario.steps:
        if step.kind == "assert":
            return step.id
    if scenario.steps:
        return scenario.steps[-1].id
    return None


async def _insert_run_tree(
    session: AsyncSession,
    *,
    run: TestRun,
    plan: PlanPayload,
    materialization: _PlanMaterialization,
) -> None:
    """Fan the plan out into the execution rows.

    Every row is created here, before anything could execute, and that is not
    an optimisation -- it is required.  ``runState.ts`` has no insert path, so
    a row that does not exist when the first event names it is a silent no-op.

    Three flushes rather than relationship assignment: every ``run_*``
    relationship is ``lazy="raise"``, and assigning ``run_scenario=...`` fires
    a backref that touches the reverse collection.  Foreign keys do not.
    """
    for scenario in plan.scenarios:
        run_scenario = RunScenario(
            run_id=run.id,
            source_scenario_id=materialization.scenario_ids.get(scenario.id),
            scenario_key=scenario.id,
            name=scenario.name.model_dump(),
            risk_level=scenario.risk_level,
            sort_order=scenario.index,
            status="pending",
        )
        session.add(run_scenario)
        await session.flush()

        steps_by_key: dict[str, RunStep] = {}

        for step in scenario.steps:
            # The payload's target when it states one, the stored plan's when it
            # does not.  A create that carries the whole tree -- what the client
            # sends today -- is unchanged by this; a create against a plan the
            # server already holds still gets a callable step.
            method, path = _request_target(
                step, materialization.step_configs.get((scenario.id, step.id)) or {}
            )
            run_step = RunStep(
                run_scenario_id=run_scenario.id,
                source_step_id=materialization.step_ids.get((scenario.id, step.id)),
                step_key=step.id,
                description=step.description.model_dump(),
                step_type=step.kind,
                endpoint_id=None,
                # Snapshots, copied rather than joined: editing a step in the
                # plan must not rewrite what an earlier run reported.
                method=method,
                path=path,
                sort_order=step.index,
                status="pending",
            )
            session.add(run_step)
            steps_by_key[step.id] = run_step

        await session.flush()

        checkpoint = steps_by_key.get(_checkpoint_step_key(scenario) or "")

        for assertion in scenario.assertions:
            session.add(
                RunAssertion(
                    run_scenario_id=run_scenario.id,
                    run_step_id=checkpoint.id if checkpoint is not None else None,
                    source_assertion_id=materialization.assertion_ids.get(
                        (scenario.id, assertion.id)
                    ),
                    assertion_key=assertion.id,
                    assertion_type=assertion.kind,
                    target=assertion.target,
                    # Copied, not referenced. `RunAssertionResponse.expected` is
                    # a required string and `run_assertions.expected_value` is
                    # nullable, so a row written without it cannot be read back.
                    # Stored as the string it is: the response field is `str`,
                    # and Pydantic does not coerce an int into one.
                    expected_value=assertion.expected,
                    description=assertion.description.model_dump(),
                    # NOT NULL with no server default, and the frontend's
                    # RunAssertionStatus has no 'pending' -- an assertion that
                    # has not run is neither passed nor failed, and the two
                    # statuses that remain are 'skipped' and nothing else.
                    status="skipped",
                )
            )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def create_run(
    session: AsyncSession, *, project_id: str, payload: RunCreateRequest
) -> RunResponse:
    """Materialise everything ``test_runs`` needs, then write the run.

    Ordered so that every check that can fail happens before the first
    statement: the approval gate, the identity agreements and the column
    lengths are all decided from the payload alone.  A request that is going to
    be refused should not have written a spec row first.

    ``summary`` is computed from the rows just written rather than stored --
    there is no summary column -- and the frontend's ``summariseScenarios``
    counts every step and assertion regardless of status, so a freshly created
    run reports its full materialised shape with the passed/failed counts at
    zero.
    """
    plan = payload.plan

    _check_approval(plan)
    _check_identity(project_id=project_id, payload=payload)

    facts = probe_document(payload.spec_document)
    identity = derive_spec_identity(
        spec_document=payload.spec_document, spec_id=payload.spec_id, facts=facts
    )
    _check_spec_identity(payload=payload, identity=identity)
    _check_lengths(payload=payload, facts=facts, identity=identity)

    try:
        project = await _lookup_project(session, project_id)
        environment = await _lookup_environment(session, project.id, payload.environment_id)
        spec = await _get_or_create_spec(
            session,
            project_id=project.id,
            spec_document=payload.spec_document,
            facts=facts,
            identity=identity,
        )
        materialization = await _get_or_create_plan(
            session, project_id=project.id, spec_id=spec.id, plan=plan
        )

        run = TestRun(
            project_id=project.id,
            plan_id=materialization.plan_id,
            spec_id=spec.id,
            environment_id=environment.id,
            # The frozen copy, not a join: a renamed plan must not rewrite the
            # name on runs that already happened.
            plan_name=plan.name.model_dump(),
            base_url=payload.base_url,
            status="queued",
            # Names only. There is no path from this module that writes a
            # variable's value to a column.
            variable_keys=sorted(payload.variables),
        )
        session.add(run)
        await session.flush()

        await _insert_run_tree(
            session, run=run, plan=plan, materialization=materialization
        )

        await session.commit()
    except IntegrityError as exc:
        # Rollback first, always: the failed statement left the transaction
        # aborted, and every statement after it -- including one building an
        # error response -- fails with 25P02 until the rollback lands.
        await session.rollback()
        raise _translate_integrity_error(exc) from exc

    if run.created_at is None:  # pragma: no cover - PostgreSQL returns it
        await session.refresh(run)

    # The run is committed, and only now is it real enough to execute: the task
    # opens its own session, so anything still uncommitted would be invisible to
    # it.  The import is local because the executor imports this module back --
    # they share the event writer -- and a cycle at import time would make the
    # package unloadable depending on which module was imported first.
    from backend.services.run_executor import schedule_run

    await schedule_run(run.id)

    return _to_response(run=run, payload=payload)


def _to_response(*, run: TestRun, payload: RunCreateRequest) -> RunResponse:
    """Build the 201 body.

    The four public identifiers are echoed from the *request*, not read back
    from the run's foreign keys: they are the strings the client sent, and
    ``test_runs`` stores UUIDs.  ``id`` is the exception -- ``test_runs`` has no
    ``public_id``, so its row UUID is its external id.
    """
    plan = payload.plan

    steps = sum(len(scenario.steps) for scenario in plan.scenarios)
    assertions = sum(len(scenario.assertions) for scenario in plan.scenarios)

    return RunResponse(
        id=str(run.id),
        project_id=payload.project_id,
        plan_id=payload.plan_id,
        plan_name=plan.name,
        spec_id=payload.spec_id,
        environment_id=payload.environment_id,
        base_url=payload.base_url,
        variable_keys=sorted(payload.variables),
        status="queued",
        created_at=run.created_at,
        started_at=None,
        finished_at=None,
        duration_ms=None,
        failure=None,
        summary=RunSummaryResponse(
            scenarios=len(plan.scenarios),
            steps=steps,
            assertions=assertions,
            passed_steps=0,
            failed_steps=0,
            passed_assertions=0,
            failed_assertions=0,
        ),
    )


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RunCounts:
    """The seven numbers ``RunSummaryResponse`` needs, for one run.

    A dataclass with zero defaults rather than a ``None`` sentinel because the
    aggregation returns *no row at all* for a run with no scenarios, and "a run
    that materialised nothing" is a real state -- it is what a plan with an empty
    ``scenarios`` list produces -- whose summary is seven zeroes.
    """

    scenarios: int = 0
    steps: int = 0
    assertions: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    passed_assertions: int = 0
    failed_assertions: int = 0

    def response(self) -> RunSummaryResponse:
        return RunSummaryResponse(
            scenarios=self.scenarios,
            steps=self.steps,
            assertions=self.assertions,
            passed_steps=self.passed_steps,
            failed_steps=self.failed_steps,
            passed_assertions=self.passed_assertions,
            failed_assertions=self.failed_assertions,
        )


_RUN_FAILURE_MESSAGES: dict[str, LocalizedMessage] = {
    "not-executable": LocalizedMessage(key="console.runs.failure.notExecutable"),
}
"""The run-level ``error_code`` values that have a sentence in the dictionary.

**Nothing writes ``test_runs.error_code`` yet** -- there is no executor, so every
row this service can currently read has it NULL and the map is unreachable on
live data.  It is here because the read path has to decide what an unknown code
means *before* one exists, and because the alternative (a mapping added later,
under a run that is already displaying a failure) is how a code ends up
rendered raw.

``console.runs.failure.notExecutable`` is the only ``failure`` key the frontend
has (``frontend/src/locales/console/en-US.ts``), so it is the only code that can
become a ``LocalizedMessage`` -- a key the dictionary does not have renders to
the user as the key itself.  Everything else falls to a ``LiteralMessage`` of
the code, which is worse English and better information than dropping it.
"""


def _failure_of(error_code: str | None, error_message: str | None) -> RunFailureResponse | None:
    """``test_runs.error_code`` / ``error_message`` as the client's ``RunFailure``.

    ``message`` is a ``LocalizedText`` and neither column is one, so the mapping
    has to be made here.  An unmapped code is **not** dropped: returning ``None``
    for a run that carries a failure would report the run as having failed for no
    stated reason, or worse, as having no failure at all.  The code is a literal
    the client shows verbatim, which is exactly what ``LiteralMessage`` is for.
    """
    if error_code is None:
        return None

    return RunFailureResponse(
        message=_RUN_FAILURE_MESSAGES.get(error_code) or LiteralMessage(text=error_code),
        detail=error_message,
    )


def _duration_ms_of(
    started_at: datetime | None, finished_at: datetime | None
) -> int | None:
    """``RunResponse.durationMs``, derived from the two timestamps.

    Not a column and not going to be one: ``test_runs`` already stores both ends,
    and a third field holding their difference is a value that can disagree with
    the two it came from.

    Half a lifecycle is no duration, and neither is a negative one.  ``None`` for
    both: a run that has not finished has not taken any measurable time yet, and
    ``finished_at < started_at`` is a clock that went backwards -- reporting it as
    ``-412`` would put a negative number where the UI prints "1.2s".
    """
    if started_at is None or finished_at is None:
        return None

    elapsed = round((finished_at - started_at).total_seconds() * 1000)
    return elapsed if elapsed >= 0 else None


def _run_duration_ms(row: Row) -> int | None:
    """``RunResponse.durationMs``: the derived value, plus the cancelled-before-start rule.

    ``_duration_ms_of`` answers "how long did this run take" from the two
    timestamps, and refuses to answer when it has only one of them.  A run that
    was cancelled before it ever started is the case that rule gets wrong, and
    the contract settles it: ``queued`` -> ``cancelled`` reports ``0``, not
    ``null``.  The run *did* finish -- cancellation is terminal -- and it spent no
    execution time getting there, so zero is a measurement rather than a
    placeholder for a missing one.

    ``finished_at`` is still required.  A cancelled run without one has not been
    through this service's cancel path, and answering ``0`` for it would invent a
    finish that never happened; ``None`` is the honest answer there.

    The rule lives here rather than inside ``_duration_ms_of`` because it is about a
    *run*: a step derives its duration with the same helper and has no
    cancelled-before-start state to report.  Both the response body and the
    ``run.cancelled`` payload go through this function, which is what keeps the
    snapshot and the event from disagreeing about the same run.
    """
    derived = _duration_ms_of(row.started_at, row.finished_at)

    if derived is not None:
        return derived

    if row.status == "cancelled" and row.started_at is None and row.finished_at is not None:
        return 0

    return None


def _run_row_select() -> Select:
    """The columns a run-shaped response is built from, from ``test_runs`` outward.

    One builder for the list and the detail, because the two bodies have to be
    the *same* body: ``upsertRun`` in ``frontend/src/stores/runs.ts`` writes a list
    item, a creation response and a detail snapshot into one array keyed by
    ``id``, so any field present on one path and missing on the other vanishes
    from whichever row was touched last.  ``_run_fields`` is the other half of
    that guarantee; this is the half that decides where the values come from.

    Every foreign key resolved here is necessary, not a convenience:
    ``test_runs`` stores ``project_id`` / ``plan_id`` / ``spec_id`` /
    ``environment_id`` as UUIDs, while the contract carries the client-facing
    strings (``prj_orders``, ``plan_orders_api_1a2b``,
    ``spec_orders_api_pkqkbr``, ``env_orders_staging``).  Reading them back per
    row is the N+1 this service exists to not have.

    ``projects``, ``test_plans`` and ``api_specs`` are inner joins because all three
    foreign keys are ``NOT NULL`` -- a run without a project is not a state the
    schema permits, and a deleted project takes its runs with it.  The
    environment is an outer join because that column is nullable ``SET NULL``;
    see the module docstring for what happens when the row is gone.  The project
    join is what lets ``get_run_detail`` answer from a run id alone, with no
    second lookup by ``public_id``.
    """
    return (
        select(
            TestRun.id.label("run_id"),
            Project.public_id.label("project_public_id"),
            TestRun.plan_name.label("plan_name"),
            TestRun.base_url.label("base_url"),
            TestRun.status.label("status"),
            TestRun.variable_keys.label("variable_keys"),
            TestRun.created_at.label("created_at"),
            TestRun.started_at.label("started_at"),
            TestRun.finished_at.label("finished_at"),
            TestRun.error_code.label("error_code"),
            TestRun.error_message.label("error_message"),
            TestPlan.public_id.label("plan_public_id"),
            ApiSpec.slug.label("spec_slug"),
            Environment.public_id.label("environment_public_id"),
        )
        .select_from(TestRun)
        .join(Project, Project.id == TestRun.project_id)
        .join(TestPlan, TestPlan.id == TestRun.plan_id)
        .join(ApiSpec, ApiSpec.id == TestRun.spec_id)
        .outerjoin(Environment, Environment.id == TestRun.environment_id)
    )


async def _fetch_run_page(
    session: AsyncSession, project_uuid: uuid.UUID, *, limit: int, offset: int
) -> list[Row]:
    """One page of runs, newest first.

    The order is ``(created_at DESC, id DESC)`` rather than ``created_at`` alone.
    The frontend sorts by ``createdAt`` too (``stores/runs.ts:84``), but it sorts
    *strings*, and it re-sorts whatever it is given -- so the server's order has
    to be total, or two runs created in the same millisecond would swap places
    between a refresh and the next one.
    """
    page = (
        _run_row_select()
        .where(TestRun.project_id == project_uuid)
        .order_by(TestRun.created_at.desc(), TestRun.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return list((await session.execute(page)).all())


async def _fetch_run_row(session: AsyncSession, run_id: uuid.UUID) -> Row | None:
    """One run, by its own id.

    ``test_runs`` has no ``public_id``, so its row UUID *is* its external id and
    this is a primary key lookup -- which is why the detail route needs no
    project in its path and no project lookup before its query.
    """
    return (await session.execute(_run_row_select().where(TestRun.id == run_id))).one_or_none()


async def _fetch_run_counts(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, _RunCounts]:
    """Every count for every run on the page, in one statement.

    ``run_steps`` has no ``run_id`` and ``run_assertions`` has no ``run_id``
    either, so both counts have to travel through ``run_scenarios`` -- which is
    the reason this is one grouped query rather than two lazy relationships
    walked per run.

    The two count sets arrive as **pre-aggregated subqueries**, joined to
    ``run_scenarios`` one row per scenario.  Aggregating them in a single flat
    query instead would multiply the two joins against each other -- a scenario
    with 3 steps and 4 assertions contributes 12 rows -- and every ``COUNT`` in it
    would need a ``DISTINCT`` to undo the fan-out it had just caused.

    ``count(...).filter(...)`` is PostgreSQL's ``FILTER (WHERE ...)``: the counts
    are over the rows that matched, not over a ``CASE`` that produces NULLs, so
    each one is a single pass.
    """
    step_counts = (
        select(
            RunStep.run_scenario_id.label("run_scenario_id"),
            func.count(RunStep.id).label("steps"),
            func.count(RunStep.id).filter(RunStep.status == "passed").label("passed_steps"),
            func.count(RunStep.id).filter(RunStep.status == "failed").label("failed_steps"),
        )
        .group_by(RunStep.run_scenario_id)
        .subquery("step_counts")
    )

    assertion_counts = (
        select(
            RunAssertion.run_scenario_id.label("run_scenario_id"),
            func.count(RunAssertion.id).label("assertions"),
            func.count(RunAssertion.id)
            .filter(RunAssertion.status == "passed")
            .label("passed_assertions"),
            func.count(RunAssertion.id)
            .filter(RunAssertion.status == "failed")
            .label("failed_assertions"),
        )
        .group_by(RunAssertion.run_scenario_id)
        .subquery("assertion_counts")
    )

    # `coalesce(..., 0)` because SUM over a scenario whose subquery row is absent
    # is NULL, and `run_assertions.status` has no 'pending' -- an assertion that
    # never ran is stored as 'skipped', so it is counted in `assertions` and in
    # neither of the two outcomes, which is what the frontend's own summariser
    # does (frontend/src/utils/runState.ts).
    counts = (
        select(
            RunScenario.run_id.label("run_id"),
            func.count(RunScenario.id).label("scenarios"),
            func.coalesce(func.sum(step_counts.c.steps), 0).label("steps"),
            func.coalesce(func.sum(step_counts.c.passed_steps), 0).label("passed_steps"),
            func.coalesce(func.sum(step_counts.c.failed_steps), 0).label("failed_steps"),
            func.coalesce(func.sum(assertion_counts.c.assertions), 0).label("assertions"),
            func.coalesce(func.sum(assertion_counts.c.passed_assertions), 0).label(
                "passed_assertions"
            ),
            func.coalesce(func.sum(assertion_counts.c.failed_assertions), 0).label(
                "failed_assertions"
            ),
        )
        .select_from(RunScenario)
        .outerjoin(step_counts, step_counts.c.run_scenario_id == RunScenario.id)
        .outerjoin(assertion_counts, assertion_counts.c.run_scenario_id == RunScenario.id)
        .where(RunScenario.run_id.in_(run_ids))
        .group_by(RunScenario.run_id)
    )

    return {
        row.run_id: _RunCounts(
            scenarios=row.scenarios,
            steps=row.steps,
            assertions=row.assertions,
            passed_steps=row.passed_steps,
            failed_steps=row.failed_steps,
            passed_assertions=row.passed_assertions,
            failed_assertions=row.failed_assertions,
        )
        for row in (await session.execute(counts)).all()
    }


def _run_fields(row: Row, *, counts: _RunCounts) -> dict[str, Any]:
    """The constructor arguments every run-shaped response shares.

    A dict rather than a model because there are four response classes that must
    carry the *same* fields -- ``RunListItem``, ``RunResponse``,
    ``RunCancelResponse`` and the ``run`` inside ``RunDetailResponse`` -- and
    ``upsertRun`` merges all four into one array keyed by ``id``.  Building the
    body in one place is what makes that identity structural; three separate
    constructors that happen to agree today is the version that drifts.

    The three identifiers are composed the way ``api_specs`` / ``test_plans`` /
    ``environments`` describe them, not read as columns: ``spec_id`` is ``spec_``
    + ``slug`` and exists in no column (``db/models/project.py``), while
    ``plan_id`` *is* a column value but is stored under the name ``public_id``.
    ``RunScenarioResponse``'s rule holds here too -- the only UUID on the wire is
    ``test_runs.id``, which is that table's external id by design.
    """
    environment_public_id = row.environment_public_id
    if environment_public_id is None:
        # See the module docstring. A run whose environment was deleted cannot be
        # rendered against the current contract, and the two quiet ways out --
        # dropping the row, or sending "" where an id belongs -- are both worse
        # than saying so.
        raise AppError(
            500,
            code="internal-error",
            message_key=_LIST_FAILED,
            details={"runId": str(row.run_id), "field": "environmentId", "reason": "null"},
        )

    return {
        "id": str(row.run_id),
        "project_id": row.project_public_id,
        "plan_id": row.plan_public_id,
        "plan_name": _localized(row.plan_name),
        "spec_id": spec_id_for(row.spec_slug),
        "environment_id": environment_public_id,
        "base_url": row.base_url,
        # Names, sorted on read as the create path sorts on write -- so the same
        # run reports the same list whichever route last touched it, which is
        # what `upsertRun` needs to not churn the row.
        "variable_keys": sorted(row.variable_keys or []),
        "status": row.status,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": _run_duration_ms(row),
        "failure": _failure_of(row.error_code, row.error_message),
        "summary": counts.response(),
    }


def _to_list_item(row: Row, *, counts: _RunCounts) -> RunListItem:
    """One row of the list, from a page row and its counts."""
    return RunListItem(**_run_fields(row, counts=counts))


async def list_runs(
    session: AsyncSession, *, project_id: str, limit: int, offset: int
) -> list[RunListItem]:
    """One page of a project's runs, newest first.

    Three statements, whatever ``limit`` is: the project lookup, the page, and
    one aggregation covering every run on it.  Nothing here walks a relationship
    -- ``TestRun.run_scenarios`` and its siblings are ``lazy="raise"`` and stay
    that way, which is enforced rather than promised because a per-row load would
    raise instead of quietly issuing N queries.

    A project with no runs is an empty list, not a 404: the collection exists and
    is empty, and the frontend renders that as its empty state rather than as an
    error.  A project that does not exist *is* a 404, because the alternative is
    answering "no runs" to a typo'd id.

    ``limit`` / ``offset`` are applied by the database, and the caller cannot
    tell "that is all of them" from "that is the first page" -- the response is a
    bare array, as the contract requires.  A caller that needs to know compares
    the row count against ``limit``; the default is set high enough that a
    realistic project is not truncated, and the frontend has no paging UI to
    page with either way.
    """
    project = await _find_project(session, project_id)

    if project is None:
        raise _list_failed(404, resource="project", publicId=project_id)

    rows = await _fetch_run_page(session, project.id, limit=limit, offset=offset)

    if not rows:
        return []

    counts = await _fetch_run_counts(session, [row.run_id for row in rows])

    return [
        _to_list_item(row, counts=counts.get(row.run_id, _RunCounts())) for row in rows
    ]


# --------------------------------------------------------------------------- #
# Detail
# --------------------------------------------------------------------------- #


_LOCALIZED_TEXT = TypeAdapter(LocalizedText)
"""One JSONB column, validated against the union the response models use.

Built from the same annotated type, so ``union_mode="left_to_right"`` and the two
halves' ``extra="forbid"`` are the schema's rules rather than a second copy of
them.  A module-level adapter is compiled once instead of per row.
"""


def _as_text(value: Any) -> str:
    """A JSONB column as the ``str`` the contract declares.

    ``run_assertions.expected_value`` and ``actual_value`` are JSONB: the column
    holds a number, a list or an object as happily as a string, and the response
    field is a ``str``.  Pydantic does not coerce an int into one, so without this
    the detail page fails validation on a row the database accepted -- a 500 on a
    run that exists and has an answer.

    A string is passed through untouched: JSON-encoding it would put the quotes
    back and print them in the assertion cell.  Everything else is rendered as
    JSON, the one representation that keeps a nested value readable without
    flattening it; ``sort_keys`` is there so two reads of one row render the same
    string.  ``None`` becomes the empty string, which is what "nothing was
    recorded" looks like in a field with no null in it.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _localized(value: Any, *, fallback: str = "") -> LocalizedText:
    """A JSONB column as the ``LocalizedText`` the contract declares.

    Every row this service has written is well-formed here: a scenario's name, a
    step's and an assertion's description and an evidence label are all copied
    from the plan or supplied by the writer.  The columns are JSONB with no shape
    constraint and ``run_assertions.description`` is nullable besides, which is a
    different statement -- a row written by anything else, or a description that
    is simply absent, makes the response model raise, and a validation error on a
    run that exists reads to the client as a failed request.

    So the mapping is total.  Anything the union accepts is returned as itself;
    anything else becomes the literal that could not be resolved.  Dropping the
    field instead is not an option -- every one of these is required on the wire
    -- and dropping the row would lose the result it describes.
    """
    if value is None:
        return LiteralMessage(text=fallback)

    try:
        return _LOCALIZED_TEXT.validate_python(value)
    except ValidationError:
        return LiteralMessage(text=_as_text(value))


def _run_not_found(run_id: str) -> AppError:
    """The detail path's 404, in the envelope the frontend already renders.

    ``code`` is ``run-not-found`` -- the one member of the frontend's closed
    ``RunErrorCode`` union that describes a resource being absent, and the code
    the mock service throws for the same situation.  ``messageKey`` is
    ``console.runs.errors.notFound``, the sentence the detail page's empty state
    exists for.  It has no placeholder, so ``params`` is omitted rather than sent
    empty; see ``errors.build_error_payload``.  A missing *project* is answered with
    the same code and a different sentence (``_list_failed``).
    """
    return AppError(
        404,
        code="run-not-found",
        message_key=_NOT_FOUND,
        details={"resource": "run", "runId": run_id},
    )


def _run_uuid(run_id: str) -> uuid.UUID | None:
    """The path parameter as a UUID, or ``None`` when it cannot be one.

    ``RunId`` is a ``str`` on purpose -- the route may not constrain it to a UUID
    without turning "no such run" into a 422 -- and handing a non-UUID to
    PostgreSQL raises ``invalid input syntax for type uuid`` (SQLSTATE 22P02),
    which surfaces as a 500 for what is really a run that does not exist.  The id
    is opaque to the frontend and arrives out of the URL, so a stale bookmark and
    a hand-typed id are both ordinary inputs here.
    """
    try:
        return uuid.UUID(run_id)
    except ValueError:
        return None


async def _fetch_run_scenarios(session: AsyncSession, run_id: uuid.UUID) -> list[Row]:
    """The run's scenarios, in run order.

    ``(sort_order, scenario_key)`` rather than ``sort_order`` alone.  The order has
    to be total or it is not an order: ``UNIQUE(run_id, scenario_key)`` makes the
    key a tiebreaker PostgreSQL can always apply, so two scenarios that share a
    ``sort_order`` -- a plan whose ``index`` values repeat, which nothing forbids --
    cannot swap places between one read and the next.
    """
    statement = (
        select(
            RunScenario.id,
            RunScenario.scenario_key,
            RunScenario.name,
            RunScenario.risk_level,
            RunScenario.status,
            RunScenario.sort_order,
        )
        .where(RunScenario.run_id == run_id)
        .order_by(RunScenario.sort_order, RunScenario.scenario_key)
    )

    return list((await session.execute(statement)).all())


async def _fetch_run_steps(
    session: AsyncSession, scenario_ids: list[uuid.UUID]
) -> list[Row]:
    """Every step of every scenario in the run, in one statement.

    The join to ``api_endpoints`` is the only one here, and it is a translation
    rather than a convenience: ``run_steps.endpoint_id`` is a UUID foreign key and
    ``RunStep.endpointId`` is the endpoint's *public* id (``ep_post_api_orders``).
    Stringifying the key would put an internal UUID into a field the client reads
    as its own id -- a value it cannot tell apart from a real one, wrong in a way
    nothing raises on.  It is an outer join because the column is nullable and
    ``SET NULL``; the create path writes NULL for every step today, since it
    materialises no endpoints.
    """
    statement = (
        select(
            RunStep.id,
            RunStep.run_scenario_id,
            RunStep.step_key,
            RunStep.description,
            RunStep.step_type,
            RunStep.method,
            RunStep.path,
            RunStep.status,
            RunStep.sort_order,
            RunStep.duration_ms,
            RunStep.started_at,
            RunStep.finished_at,
            RunStep.error_code,
            RunStep.error_message,
            ApiEndpoint.public_id.label("endpoint_public_id"),
        )
        .outerjoin(ApiEndpoint, ApiEndpoint.id == RunStep.endpoint_id)
        .where(RunStep.run_scenario_id.in_(scenario_ids))
        .order_by(RunStep.run_scenario_id, RunStep.sort_order, RunStep.step_key)
    )

    return list((await session.execute(statement)).all())


async def _fetch_run_assertions(
    session: AsyncSession, scenario_ids: list[uuid.UUID]
) -> list[Row]:
    """Every assertion of every scenario in the run, in one statement.

    ``run_assertions`` has no ``sort_order`` -- the frontend renders assertions in
    array order and has never needed one -- so ``assertion_key`` is the order, with
    ``UNIQUE(run_scenario_id, assertion_key)`` behind it.  Leaving the order to
    PostgreSQL would return the plan's order today and something else after a
    vacuum, a rewrite or a plan change, with nothing on screen to say the list had
    been shuffled.
    """
    statement = (
        select(
            RunAssertion.id,
            RunAssertion.run_scenario_id,
            RunAssertion.run_step_id,
            RunAssertion.assertion_key,
            RunAssertion.assertion_type,
            RunAssertion.target,
            RunAssertion.expected_value,
            RunAssertion.actual_value,
            RunAssertion.description,
            RunAssertion.status,
        )
        .where(RunAssertion.run_scenario_id.in_(scenario_ids))
        .order_by(RunAssertion.run_scenario_id, RunAssertion.assertion_key)
    )

    return list((await session.execute(statement)).all())


async def _fetch_run_evidence(
    session: AsyncSession, run_id: uuid.UUID, step_ids: list[uuid.UUID]
) -> list[Row]:
    """The evidence attached to the run's steps, in one statement.

    Both conditions are necessary and neither is redundant.  ``run_step_id`` is
    ``NOT NULL`` here because the contract has no other place for evidence:
    ``RunEvidence`` is rendered inside a ``RunStep``, so a row whose step link has
    been nulled is not reachable over the API at all (see the model).  ``run_id``
    is what keeps evidence belonging to another run out of this run's steps -- the
    two columns are independent foreign keys and nothing in the schema ties them
    to each other.

    ``(created_at, id)`` is the order: evidence is appended as it is observed, so
    the timestamp is the sequence, and the primary key is what makes it total for
    two rows written inside one transaction.
    """
    statement = (
        select(
            RunEvidence.run_step_id,
            RunEvidence.label,
            RunEvidence.value,
        )
        .where(
            RunEvidence.run_id == run_id,
            RunEvidence.run_step_id.in_(step_ids),
        )
        .order_by(RunEvidence.run_step_id, RunEvidence.created_at, RunEvidence.id)
    )

    return list((await session.execute(statement)).all())


async def _fetch_last_seq(session: AsyncSession, run_id: uuid.UUID) -> int:
    """``MAX(run_events.seq)`` for the run, or ``0`` when it has no events.

    The reconnect contract: the client takes this as its high-water mark and drops
    every event at or below it, which is what makes "snapshot, then subscribe"
    equivalent to having been connected throughout.  ``0`` rather than ``None``
    because ``seq`` starts at 1 -- the same ``0`` the store falls back to when it
    has never seen the run (``stores/runs.ts``: ``fromSeq: lastSeq.get(runId) ?? 0``).

    An aggregate over no rows still returns one row, with NULL in it, which is
    what ``scalar_one`` unwraps.  The ``max`` is served by the
    ``UNIQUE(run_id, seq)`` constraint, so it is an index lookup and not a scan of
    the stream.
    """
    highest = (
        await session.execute(
            select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)
        )
    ).scalar_one()

    return int(highest or 0)


def _step_duration_ms(row: Row) -> int | None:
    """``RunStep.durationMs``, from the column the step owns.

    A run has no duration column and derives its own from two timestamps; a step
    has one, so that is the value to report.  The fallback covers the state
    nothing could tell apart from a finished step whose duration went unrecorded
    -- timestamps written, duration not -- and it applies the same two guards as
    the run-level derivation, so half a lifecycle is ``None`` and a negative
    duration is never reported as a small one.
    """
    if row.duration_ms is not None:
        return row.duration_ms

    return _duration_ms_of(row.started_at, row.finished_at)


def _evidence_response(row: Row) -> RunEvidenceResponse:
    """One evidence row.  ``evidence_type`` and ``content`` stay where they are.

    Neither is in ``AgentEvidence``, so neither is copied here: an unconsumed field
    on the wire is a field nobody notices going stale.
    """
    return RunEvidenceResponse(label=_localized(row.label), value=row.value)


def _step_response(
    row: Row, *, scenario_key: str, evidence: list[RunEvidenceResponse]
) -> RunStepResponse:
    return RunStepResponse(
        id=row.step_key,
        scenario_id=scenario_key,
        index=row.sort_order,
        kind=row.step_type,
        description=_localized(row.description),
        endpoint_id=row.endpoint_public_id,
        method=row.method,
        path=row.path,
        status=row.status,
        duration_ms=_step_duration_ms(row),
        failure=_failure_of(row.error_code, row.error_message),
        evidence=evidence,
    )


def _assertion_response(
    row: Row, *, scenario_key: str, step_key_by_id: dict[uuid.UUID, str]
) -> RunAssertionResponse:
    """One assertion row.

    ``step_id`` is resolved through ``step_key_by_id`` for the same reason
    ``RunAssertionResponse.id`` is ``assertion_key``: the row's own UUID is
    internal, and the parent link the client joins on is the plan-side key.  The
    lookup misses only for a row whose step belongs to another scenario, which the
    insert path cannot produce -- and a link that resolves to nothing is reported
    as "no step" rather than as an id the client cannot match to anything.
    """
    step_id = row.run_step_id

    return RunAssertionResponse(
        id=row.assertion_key,
        scenario_id=scenario_key,
        step_id=step_key_by_id.get(step_id) if step_id is not None else None,
        kind=row.assertion_type,
        target=row.target,
        expected=_as_text(row.expected_value),
        actual=None if row.actual_value is None else _as_text(row.actual_value),
        status=row.status,
        description=_localized(row.description),
    )


async def get_run_detail(session: AsyncSession, *, run_id: str) -> RunDetailResponse:
    """A run, its whole execution tree, and the point in the stream it was read at.

    Seven statements for any tree -- the run row, its scenarios, steps,
    assertions, evidence, the seven counts and the event high-water mark -- and
    never a statement per row.  Nothing walks a relationship:
    ``TestRun.run_scenarios`` and its siblings are ``lazy="raise"`` and stay that
    way, so a lazy load here would raise rather than quietly issuing N queries.  A
    run with no scenarios is three of those statements, because there is no tree
    to read and its summary is structurally seven zeroes.

    The order the rows come back in is the database's, not PostgreSQL's.  A tree
    the client re-reads has to be the same tree: scenarios and steps sort on
    ``sort_order`` with their stable key as a tiebreaker, and assertions -- which
    have no ``sort_order`` column -- sort on ``assertion_key``, because the frontend
    updates rows by id equality with no positional fallback.  A swapped pair is a
    page that updates the wrong row, silently.

    A run that does not exist is a 404 in the frontend's own vocabulary, never a
    200 with a null body: ``RunDetailView`` keys its "not found" empty state off the
    absence of a detail, and a null is indistinguishable from a run that has not
    loaded yet.

    ``summary`` comes from the same aggregate the list uses rather than from the
    tree in hand.  That costs a statement and buys the thing worth having: the
    list page and the detail page cannot disagree about the shape of a run,
    because "what counts as a passed step" has one implementation.
    """
    run_uuid = _run_uuid(run_id)

    if run_uuid is None:
        raise _run_not_found(run_id)

    row = await _fetch_run_row(session, run_uuid)

    if row is None:
        raise _run_not_found(run_id)

    scenario_rows = await _fetch_run_scenarios(session, run_uuid)

    if not scenario_rows:
        # No scenarios means no steps and no assertions to count, so the summary
        # is seven zeroes -- the same reason ``list_runs`` skips its aggregation
        # for an empty page.  The events are still read: a run that failed before
        # materialising anything is exactly the run whose stream matters.
        return RunDetailResponse(
            run=RunResponse(**_run_fields(row, counts=_RunCounts())),
            scenarios=[],
            last_seq=await _fetch_last_seq(session, run_uuid),
        )

    scenario_ids = [scenario.id for scenario in scenario_rows]
    step_rows = await _fetch_run_steps(session, scenario_ids)
    assertion_rows = await _fetch_run_assertions(session, scenario_ids)

    # Keyed by the rows' own UUIDs -- the one place they are needed, and the one
    # place they never leave.  A dict preserves insertion order, which is the
    # order the statements above returned, so the tree is assembled in the order
    # the database put it in.
    steps_by_scenario: dict[uuid.UUID, list[Row]] = {}
    step_key_by_id: dict[uuid.UUID, str] = {}

    for step in step_rows:
        steps_by_scenario.setdefault(step.run_scenario_id, []).append(step)
        step_key_by_id[step.id] = step.step_key

    assertions_by_scenario: dict[uuid.UUID, list[Row]] = {}

    for assertion in assertion_rows:
        assertions_by_scenario.setdefault(assertion.run_scenario_id, []).append(assertion)

    evidence_by_step: dict[uuid.UUID, list[RunEvidenceResponse]] = {}

    if step_rows:
        # Skipped when the run has no steps: evidence is rendered inside a step
        # and nowhere else, so with no steps there is nothing to attach it to.
        for evidence in await _fetch_run_evidence(
            session, run_uuid, [step.id for step in step_rows]
        ):
            evidence_by_step.setdefault(evidence.run_step_id, []).append(
                _evidence_response(evidence)
            )

    counts = (await _fetch_run_counts(session, [run_uuid])).get(run_uuid, _RunCounts())

    scenarios = [
        RunScenarioResponse(
            id=scenario.scenario_key,
            index=scenario.sort_order,
            name=_localized(scenario.name),
            risk_level=scenario.risk_level,
            status=scenario.status,
            steps=[
                _step_response(
                    step,
                    scenario_key=scenario.scenario_key,
                    evidence=evidence_by_step.get(step.id, []),
                )
                for step in steps_by_scenario.get(scenario.id, [])
            ],
            assertions=[
                _assertion_response(
                    assertion,
                    scenario_key=scenario.scenario_key,
                    step_key_by_id=step_key_by_id,
                )
                for assertion in assertions_by_scenario.get(scenario.id, [])
            ],
        )
        for scenario in scenario_rows
    ]

    return RunDetailResponse(
        run=RunResponse(**_run_fields(row, counts=counts)),
        scenarios=scenarios,
        last_seq=await _fetch_last_seq(session, run_uuid),
    )


# --------------------------------------------------------------------------- #
# Cancelling
# --------------------------------------------------------------------------- #


def _cancel_failed(status_code: int, **details: Any) -> AppError:
    """Cancel's own failure, in the envelope the frontend already renders.

    Deliberately not ``_create_failed``.  That helper's sentence is "The run could
    not be created." -- the wrong thing to say to a request that never tried to
    create anything -- and the two paths fail on different constraints, so a
    shared translator would file a cancel under a create's vocabulary.

    ``code`` is ``cancel-failed`` and ``messageKey`` is
    ``console.runs.errors.cancelFailed`` ("The run could not be cancelled."):
    both already exist in the frontend's closed unions, so nothing new is
    invented here, and ``details`` carries the diagnosis that is logged and never
    rendered.
    """
    return AppError(
        status_code,
        code="cancel-failed",
        message_key=_CANCEL_FAILED,
        details=details or None,
    )


def _translate_cancel_integrity_error(exc: IntegrityError) -> AppError:
    """Turn a failed statement on the cancel path into an ``AppError``.

    Called *after* the rollback, like its create-path counterpart and for the
    same reason: a failed statement leaves the transaction aborted, and every
    statement after it -- including one building the error response -- fails
    with ``25P02`` until the rollback lands.

    The one constraint this can realistically be is
    ``uq_run_events_run_seq``: a second writer allocated the same ``seq`` for the
    same run.  Two *cancels* cannot produce it -- the second one matches no row
    in the conditional UPDATE and writes no event -- so it would mean a second
    writer exists, which today means the executor this service does not have.
    That is why it is a 500 and not a 409: nothing the caller sent can cause it
    or avoid it.  The name and SQLSTATE come from :func:`constraint_of`, never
    from the message text, which this PostgreSQL instance emits in Chinese.
    """
    name, sqlstate = constraint_of(exc)

    return _cancel_failed(500, constraint=name, sqlstate=sqlstate)


async def _transition_to_cancelled(session: AsyncSession, run_id: uuid.UUID) -> Row | None:
    """Cancel the run if it is still cancellable, and say whether it was.

    One statement rather than a read followed by a write, and that is the whole
    of the concurrency story: the decision and the change are the same
    operation, so there is no window between them for a second request to slip
    through.  Under READ COMMITTED the second UPDATE blocks on the first one's
    row lock, re-evaluates its ``WHERE`` against the committed row, matches
    nothing, and returns no row -- which the caller reads as "somebody else got
    there first" rather than as an error.

    ``error_code`` / ``error_message`` are cleared, which is what makes the
    contract's ``failure: null`` unconditional rather than a statement about
    today's data.  ``run.cancelled`` carries no failure, so a run whose snapshot
    still reported one would be a run whose stored failure and whose stream
    disagree.

    ``finished_at`` is ``now()`` -- PostgreSQL's transaction timestamp, the same
    clock the event row's ``created_at`` default uses, so "when the run was
    cancelled" is one instant rather than two that are close.  ``started_at`` is
    left exactly as found: a run that never started must not be made to look
    like one that did.

    The returned row carries the *new* values (RETURNING reads the updated row),
    which is what lets the caller derive the cancelled duration with the same
    function the response body uses.
    """
    statement = (
        update(TestRun)
        .where(TestRun.id == run_id, TestRun.status.in_(_CANCELLABLE_STATUSES))
        .values(
            status="cancelled",
            finished_at=func.now(),
            error_code=None,
            error_message=None,
        )
        .returning(TestRun.status, TestRun.started_at, TestRun.finished_at)
    )

    return (await session.execute(statement)).one_or_none()


async def append_run_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Append one event to a run's stream, and say which ``seq`` it took.

    **The single writer for ``run_events``.**  Two producers exist -- the cancel
    route and the run executor -- and two seq allocators would be two chances to
    allocate the same number: under READ COMMITTED both would read the same
    ``MAX(seq)``, both would compute the next value, and the loser would collide
    on ``uq_run_events_run_seq``.

    So the allocation is serialised on the run row: ``SELECT ... FOR UPDATE`` on
    ``test_runs`` -- the lock the cancel path already holds, because its
    conditional UPDATE writes that row -- and only then the INSERT whose ``seq``
    is ``COALESCE(MAX(seq), 0) + 1``, computed by the statement rather than read
    first.  Both mechanisms are kept: the subquery removes the window inside this
    call, and the row lock removes it between callers.  Whoever commits first
    wins; the next producer waits and numbers itself after.

    No sequence table, no advisory lock, no broker: one row that every producer
    of this run's stream has to touch anyway.

    ``payload`` carries the event's *own* fields and nothing else -- ``runId``,
    ``seq`` and ``at`` are columns on the row this writes, so repeating them
    would be two sources for one fact.  Callers commit; the lock lives until
    they do, which is the point.
    """
    await session.execute(select(TestRun.id).where(TestRun.id == run_id).with_for_update())

    next_seq = (
        select(func.coalesce(func.max(RunEvent.seq), 0) + 1)
        .where(RunEvent.run_id == run_id)
        .scalar_subquery()
    )

    seq = (
        await session.execute(
            insert(RunEvent)
            .values(run_id=run_id, seq=next_seq, event_type=event_type, payload=payload)
            .returning(RunEvent.seq)
        )
    ).scalar_one()

    return int(seq)


def run_failure_dict(error_code: str, error_message: str | None = None) -> dict[str, Any]:
    """``RunFailure`` as the *stream* carries it, from the same mapping the API uses.

    ``RunResponse.failure`` and a ``step.failed`` event have to say the same thing
    about the same row -- one is the snapshot, the other is the tail of the same
    stream -- so both go through ``_RUN_FAILURE_MESSAGES``.  An unmapped code is a
    literal, not a dropped field, exactly as on the read path.
    """
    message = _RUN_FAILURE_MESSAGES.get(error_code)

    return {
        "message": (
            message.model_dump() if message is not None else LiteralMessage(text=error_code).model_dump()
        ),
        "detail": error_message,
    }


async def _insert_cancelled_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    finished_at: datetime,
    duration_ms: int | None,
) -> None:
    """Append the run's ``run.cancelled`` event.

    Thin on purpose: the seq allocation, the locking and the payload rule live in
    :func:`append_run_event`, which the executor uses too.  ``durationMs`` is passed
    in rather than recomputed, so the number in the payload and the number in the
    response body are the same value by construction, not by agreement.
    """
    await append_run_event(
        session,
        run_id=run_id,
        event_type=RUN_CANCELLED_EVENT,
        payload={
            "finishedAt": finished_at.isoformat(),
            "durationMs": duration_ms,
        },
    )


async def cancel_run(session: AsyncSession, *, run_id: str) -> RunCancelResponse:
    """Stop a run that has not stopped, and return it as it stands either way.

    The order is the contract's: make the transition conditional, ask whether it
    happened, write the event if it did, read the run back, and commit once.  A
    run that is already ``passed``, ``failed`` or ``cancelled`` matches nothing,
    writes nothing, and is returned as it is -- cancelling something that has
    finished is not an error, and a 409 would turn a harmless race into a
    sentence the user has to read about a run that is already stopped.

    The response is built *before* the commit.  ``_run_fields`` can refuse -- a run
    whose environment row is gone is the state the module docstring records --
    and refusing after the commit would leave a cancelled run behind a 500, with
    the caller unable to tell whether their cancellation happened.  Building
    first makes the request all-or-nothing, the rule ``create_run`` already
    follows.

    Three states arrive here and only two of them change anything:

    * ``queued`` -> ``cancelled``, ``started_at`` still NULL, ``durationMs`` 0;
    * ``running`` -> ``cancelled``, ``started_at`` kept, ``durationMs`` measured
      from it to the cancellation;
    * anything else -- ``passed``, ``failed``, ``cancelled`` -- unchanged, 200.

    A run that does not exist is a 404, and an id that cannot be a UUID is a 404
    as well rather than PostgreSQL's ``22P02`` surfacing as a 500.  Everything in
    the body comes from the shared run builder, so nothing on this path reads a
    variable, an environment or a credential.
    """
    run_uuid = _run_uuid(run_id)

    if run_uuid is None:
        raise _run_not_found(run_id)

    try:
        transition = await _transition_to_cancelled(session, run_uuid)

        if transition is not None:
            await _insert_cancelled_event(
                session,
                run_uuid,
                finished_at=transition.finished_at,
                duration_ms=_run_duration_ms(transition),
            )

        row = await _fetch_run_row(session, run_uuid)

        if row is None:
            # Nothing matched *and* there is nothing to read: the run does not
            # exist.  A run that exists but is already terminal is not this case
            # -- it has a row, it simply did not transition.
            raise _run_not_found(run_id)

        counts = (await _fetch_run_counts(session, [run_uuid])).get(
            run_uuid, _RunCounts()
        )
        response = RunCancelResponse(**_run_fields(row, counts=counts))

        await session.commit()
    except IntegrityError as exc:
        # Rollback first, always: see `_translate_cancel_integrity_error`.
        await session.rollback()
        raise _translate_cancel_integrity_error(exc) from exc

    return response


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


async def _run_exists(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Whether the run is there, without reading anything else about it.

    A column select rather than an entity load: replay needs no plan, no spec and
    no environment, so the question is exactly "is this id a run" and nothing
    more.  The answer is what separates the two outcomes this endpoint must never
    merge -- a run that does not exist (404) and a run that has not said anything
    yet (200 and an empty list).
    """
    found = (
        await session.execute(select(TestRun.id).where(TestRun.id == run_id))
    ).scalar_one_or_none()

    return found is not None


async def _fetch_run_events(
    session: AsyncSession, run_id: uuid.UUID, *, from_seq: int
) -> list[Row]:
    """The run's events at or after ``from_seq``, in ``seq`` order.

    ``seq >= :from_seq`` -- inclusive, so ``fromSeq=3`` replays 3 onwards and a
    client resuming from the mark it was handed does not lose the event that
    produced it.

    The order is ``seq`` and only ``seq``: not ``created_at`` (which two events
    written inside one transaction share, to the microsecond) and not whatever
    order the heap happens to return.  ``UNIQUE(run_id, seq)`` makes that order
    total, which is the property a high-water mark depends on.

    Both the filter and the cut are the database's.  Reading the stream and
    dropping the early rows in Python would turn a bounded read into a walk over
    the whole history of precisely the runs that grew long enough for replay to
    matter.
    """
    statement = (
        select(
            RunEvent.run_id,
            RunEvent.seq,
            RunEvent.created_at,
            RunEvent.event_type,
            RunEvent.payload,
        )
        .where(RunEvent.run_id == run_id, RunEvent.seq >= from_seq)
        .order_by(RunEvent.seq)
    )

    return list((await session.execute(statement)).all())


def _event_response(row: Row) -> RunEventResponse:
    """One stored event, as the replay record.

    The payload is passed through untouched -- not re-encoded, not re-shaped, not
    merged into the surrounding object.  Whatever a writer stored is what a
    reader gets; the only things this function does are rename two columns and
    drop the row's own id.
    """
    return RunEventResponse(
        run_id=str(row.run_id),
        seq=row.seq,
        at=row.created_at,
        event_type=row.event_type,
        payload=row.payload,
    )


async def get_run_events(
    session: AsyncSession, *, run_id: str, from_seq: int
) -> list[RunEventResponse]:
    """Replay a run's persisted events from ``from_seq`` onwards.

    Two statements whatever the run holds: the existence check that turns an
    unknown id into the same 404 the detail and cancel routes answer with, and
    the events themselves.  Nothing here walks a relationship, joins another
    table, or writes -- the payload goes back exactly as it was stored, so this
    endpoint cannot disagree with the writer about what an event says.

    A run with no events is not a missing run: the collection exists and is
    empty, which is what a client that has just created a run expects to see
    before anything has happened to it.
    """
    run_uuid = _run_uuid(run_id)

    if run_uuid is None:
        raise _run_not_found(run_id)

    if not await _run_exists(session, run_uuid):
        raise _run_not_found(run_id)

    rows = await _fetch_run_events(session, run_uuid, from_seq=from_seq)

    return [_event_response(row) for row in rows]


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #


async def resolve_run_for_stream(session: AsyncSession, *, run_id: str) -> uuid.UUID:
    """Resolve the run a stream is about to follow, or refuse before it starts.

    The two answers this owes are the ones every other run route gives -- a 404
    for an id that cannot be a run -- and it owes them *now*, while the response is
    still a status line and a JSON body.  Once a stream has started, the status
    line has already been sent and there is nowhere left to put a 404.
    """
    run_uuid = _run_uuid(run_id)

    if run_uuid is None:
        raise _run_not_found(run_id)

    if not await _run_exists(session, run_uuid):
        raise _run_not_found(run_id)

    return run_uuid


def _sse_timestamp(value: datetime) -> str:
    """A timestamp as the response models render it: UTC as ``Z``.

    The stream and the replay record carry the same instant, and a client that
    compares them should not have to know that one was rendered by Pydantic and
    the other by hand -- so this reproduces the model's rendering (``Z`` for UTC,
    a plain offset for anything else) instead of calling ``isoformat`` and letting
    ``+00:00`` through.
    """
    rendered = value.isoformat()

    return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered


_FRAME_FIELDS = ("runId", "seq", "at", "type")
"""The fields a frame owns, in the spelling the frontend reads them under."""


def stream_event(row: Row) -> dict[str, Any]:
    """One stored event as the object an SSE frame carries.

    The shape is the frontend's ``RunEvent``, not the replay record: ``eventType``
    becomes ``type`` and the payload's fields are lifted to the top level, because
    that is the object ``applyRunEvent`` switches on.  Replay deliberately keeps the
    row's shape (see ``RunEventResponse``); the stream hands the client something it
    can fold.

    Two rules keep this from inventing anything:

    * **The columns win.**  The four base fields are written last, so a payload
      that happens to carry ``seq`` -- the key a resume depends on -- cannot
      overwrite it.  A collision is logged, and the payload keeps every key the
      base fields do not claim.
    * **A payload that is not an object is not dropped.**  The union has nowhere to
      put a list or a scalar, so it travels whole under ``payload``, the name the
      store and the replay record already use for it.  Nothing is discarded to make
      a shape fit.
    """
    data: dict[str, Any] = {}

    if isinstance(row.payload, dict):
        shadowed = sorted(set(_FRAME_FIELDS) & set(row.payload))
        if shadowed:
            # Names only: a payload is event data and is never written to a log.
            logger.warning(
                "run %s seq %s: payload shadows the frame's own fields %s",
                row.run_id,
                row.seq,
                shadowed,
            )

        data.update(row.payload)
    else:
        data["payload"] = row.payload

    # Written one key at a time, in the spelling the frontend reads: this is a
    # plain dict on its way into JSON, so nothing here goes through the models'
    # alias generator and ``run_id`` would arrive as itself.
    data["runId"] = str(row.run_id)
    data["seq"] = row.seq
    data["at"] = _sse_timestamp(row.created_at)
    data["type"] = row.event_type

    return data


def _sse_frame(event: dict[str, Any]) -> str:
    """One SSE frame: ``id`` is the ``seq``, ``event`` the type, ``data`` the object.

    ``id`` is the run's own sequence, because that is what comes back as
    ``Last-Event-ID`` and the only key that means anything to a resume.

    ``event`` repeats the type so a client can subscribe by name.  A name carrying
    a line break would end the field and start another one, so the break is
    replaced on that line -- the object still carries the name exactly as stored,
    which is what a client actually reads.
    """
    name = str(event["type"]).replace("\r", " ").replace("\n", " ")
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

    return f"id: {event['seq']}\nevent: {name}\ndata: {payload}\n\n"


async def read_stream_batch(
    session: AsyncSession, *, run_id: uuid.UUID, from_seq: int
) -> tuple[str | None, list[dict[str, Any]]]:
    """The run's status and its unsent events, in one statement.

    A stream has to answer two questions each time it wakes up -- "is this run
    still going" and "has anything happened" -- and asking them separately doubles
    what an idle connection costs.  One outer join answers both: no rows means the
    run is gone, a single row of NULLs means it exists and has said nothing since
    ``from_seq``, and one row per event means there is something to send.
    ``status`` repeats across those rows and is read from the first.

    The filter is the database's and the order is ``seq``, so the read is served by
    ``UNIQUE(run_id, seq)`` and never by a walk the client's backlog makes longer.
    """
    statement = (
        select(
            TestRun.status.label("run_status"),
            RunEvent.run_id,
            RunEvent.seq,
            RunEvent.created_at,
            RunEvent.event_type,
            RunEvent.payload,
        )
        .select_from(TestRun)
        .outerjoin(
            RunEvent,
            (RunEvent.run_id == TestRun.id) & (RunEvent.seq >= from_seq),
        )
        .where(TestRun.id == run_id)
        .order_by(RunEvent.seq)
    )

    rows = list((await session.execute(statement)).all())

    if not rows:
        return None, []

    return rows[0].run_status, [stream_event(row) for row in rows if row.seq is not None]


async def stream_run_events(
    *,
    run_id: uuid.UUID,
    from_seq: int,
    disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Follow a run's events: everything it has said, then everything it says.

    The loop is the simplest thing that is correct:

    * read once for the run's status and anything new -- one statement, filtered
      on ``seq`` by the database, so the index does the work;
    * send what came back in ``seq`` order and read again *without* sleeping, because
      a run that has just produced one event usually has another behind it;
    * when nothing came back: stop if the run is finished, say ``: ping`` if the
      connection has been quiet long enough, otherwise sleep one interval.

    Nothing is buffered between passes.  The database is the only place an event
    lives, which is what lets a reconnecting client resume from a ``seq`` and see
    the same stream the first connection saw.

    ``disconnected`` is the caller's answer to "has the client gone", passed in
    rather than imported, so this module keeps knowing nothing about HTTP.  It is
    asked every pass: a client that walked away stops the queries instead of
    leaving a loop running until the run happens to finish.

    A read that fails ends the stream -- the traceback goes to the log, and the
    client gets a closed connection rather than a database error inside a frame.
    """
    poll = SSE_POLL_INTERVAL_SECONDS
    heartbeat = SSE_HEARTBEAT_SECONDS
    next_seq = from_seq
    last_frame_at = time.monotonic()

    logger.info("run %s: stream opened at seq %d", run_id, from_seq)

    while True:
        if await disconnected():
            logger.info(
                "run %s: stream closed, the client disconnected at seq %d", run_id, next_seq
            )
            return

        try:
            async with AsyncSessionLocal() as session:
                status, events = await read_stream_batch(
                    session, run_id=run_id, from_seq=next_seq
                )
        except Exception:
            logger.exception("run %s: stream closed after a failed read", run_id)
            return

        if status is None:
            logger.info("run %s: stream closed, the run is gone at seq %d", run_id, next_seq)
            return

        if events:
            for event in events:
                yield _sse_frame(event)
                next_seq = int(event["seq"]) + 1

            last_frame_at = time.monotonic()
            continue

        if status in _TERMINAL_STATUSES:
            logger.info(
                "run %s: stream closed at the end of a finished run, seq %d",
                run_id,
                next_seq - 1,
            )
            return

        if time.monotonic() - last_frame_at >= heartbeat:
            yield _SSE_KEEPALIVE
            last_frame_at = time.monotonic()

        await asyncio.sleep(poll)



