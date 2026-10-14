"""Run endpoints.

Six routes.  Four of them have their paths fixed by a contract that already
exists in the frontend (``frontend/docs/phase-6.2-backend-rest-contract.md``):

* ``POST /api/projects/{project_id}/runs``
* ``GET  /api/projects/{project_id}/runs``
* ``GET  /api/runs/{run_id}``
* ``POST /api/runs/{run_id}/cancel``

The last two are the pair the phase-6.2 document deliberately left open.  It
fixes the *event* payloads but defers the transport, so they were specified as
two different things rather than one endpoint wearing both hats:

* ``GET /api/runs/{run_id}/events`` (7.2-D) is a **read**: ``fromSeq`` in,
  persisted rows out, connection closed.  See ``RunEventResponse``.
* ``GET /api/runs/{run_id}/events/stream`` (7.2-E) is a **subscription**: the
  same rows, then every row that appears while the client is listening, as
  Server-Sent Events.  It is also the only route in this module that answers with
  something other than JSON.

Neither is a wrapper around the other.  Replay hands back what was stored; the
stream hands the client a frame it can fold into the run it is holding.

Two URL prefixes in one router because they are one resource: a run is listed
under its project and addressed on its own.  Splitting them across modules would
split one service across two call sites.

**Phase 7.2 progress.**  Create (7.2-B), list (7.2-C.1), detail (7.2-C.2),
cancel (7.2-C.3) and event replay (7.2-D) are implemented and call into
``backend.services.runs``.  There is no placeholder left in this module, and that
matters for more than tidiness -- a 501 on a path whose sibling answers 200 is a
contradiction the client cannot interpret.

What the cancel route does *not* do is stop anything.  There is no executor and
no stream yet, so cancelling is a state transition plus the event that records
it; stopping the work is a later phase's problem, and the service is written so
that the transition is correct whether or not anything is executing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request, status
from fastapi.responses import StreamingResponse

from backend.api.deps import CurrentGuestSessionDep, SessionDep
from backend.api.errors import ERROR_RESPONSES, AppError
from backend.schemas.common import ErrorResponse
from backend.schemas.run import (
    RunCancelResponse,
    RunCreateRequest,
    RunDetailResponse,
    RunEventResponse,
    RunListItem,
    RunResponse,
)
from backend.services import guest_access, runs

__all__ = ["DEFAULT_FROM_SEQ", "DEFAULT_RUN_LIMIT", "SSE_HEADERS", "router"]

SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
"""The headers an event stream needs in order to still be a stream by the time it
reaches the browser.

The content type comes from the response itself; these three are about everything
between here and there.  A cache that stores an event stream serves a run's
history to the next viewer as if it were live, and a proxy that buffers one holds
every frame until the connection closes -- which, for a stream that closes when
the run finishes, means the client sees nothing at all until there is nothing
left to see.  None of the three is needed by uvicorn on its own; all three are
needed by the deployment this service will sit behind.
"""

_STREAM_FAILED = "console.runs.errors.loadFailed"
"""The sentence a rejected resume gets.

A stream that cannot start is a run that could not be *loaded*, which is what
this key says, and it is already in the frontend's dictionary -- inventing a
message key is how a user ends up reading a dotted identifier instead of a
sentence."""

DEFAULT_FROM_SEQ = 1
"""The ``seq`` a caller that names none starts from, which is the whole stream.

``seq`` starts at 1 and is dense within a run, so 1 is the first event that can
exist -- an inclusive default here and an exclusive one would differ only for a
run with no events at all, which is exactly the case where the difference would
be invisible and then wrong.  ``fromSeq`` is *inclusive*: ``?fromSeq=3`` returns
the event numbered 3 and everything after it, so a client resuming from the
``lastSeq`` its snapshot carried receives the event that mark was taken at
rather than skipping it.
"""

DEFAULT_RUN_LIMIT = 200
"""How many runs a caller that asks for no particular number gets.

Equal to the ceiling, which is deliberate rather than lazy.  The frontend reads
the list as a bare array and has no paging UI, so a smaller default would not
page anything -- it would silently hide the tail of a long list behind an
affordance that does not exist.  A bounded default and a complete one are the
same number here; when the frontend grows a ``listRuns`` that pages, this is the
constant to lower.
"""

router = APIRouter(prefix="/api", tags=["runs"])

ProjectId = Annotated[
    str,
    Path(
        description="The project's `public_id`, e.g. `prj_orders`. Not a UUID.",
        examples=["prj_orders"],
    ),
]
RunId = Annotated[
    str,
    Path(
        description="`test_runs.id`. A UUID string -- `test_runs` has no `public_id`, "
        "so this is the one row key that travels as-is.",
        examples=["3f1c8a52-9b0e-4d71-8c2a-5e6f7a8b9c0d"],
    ),
]
RunLimit = Annotated[
    int,
    Query(
        ge=1,
        le=200,
        description="Maximum runs to return. Bounded, because an unbounded list is a "
        "query whose cost the caller chooses.",
    ),
]
RunOffset = Annotated[
    int,
    Query(
        ge=0,
        description="Runs to skip, after the `createdAt` descending sort. The page "
        "carries no total, so a caller that needs to know whether more exist "
        "compares the row count it got against its `limit`.",
    ),
]
RunStreamFromSeq = Annotated[
    int | None,
    Query(
        ge=1,
        # Same name on the wire as the replay route's, and the same inclusive
        # meaning -- but optional here, because a client that is *reconnecting*
        # says where it got to with Last-Event-ID rather than repeating the query
        # it first sent.  A default of 1 would shadow that header: the two cases
        # are indistinguishable once the value is an int.
        alias="fromSeq",
        description="Start the stream at this seq, inclusive (default: whatever "
        "Last-Event-ID implies, or 1).",
    ),
]
LastEventId = Annotated[
    str | None,
    Header(
        alias="Last-Event-ID",
        description="The last seq the client received, as Server-Sent Events define "
        "it. The stream resumes at one past it -- this header is a receipt, not a "
        "resume point -- and fromSeq wins when both are present.",
    ),
]
RunFromSeq = Annotated[
    int,
    Query(
        ge=1,
        # The one multi-word query parameter in this router, and so the one that
        # needs an explicit name: an alias generator turns a *model's* fields into
        # camelCase, and a query parameter declared here is not a model field.  It
        # would answer to ``from_seq`` while every caller sends ``fromSeq`` -- and an
        # unknown query parameter is not an error, so FastAPI would ignore it, the
        # default would apply, and the endpoint would silently replay the whole
        # stream instead of the tail that was asked for.
        alias="fromSeq",
        description="Replay from this `seq` onwards, **inclusive**. Defaults to 1, which "
        "is the whole stream: `seq` starts at 1 and is dense within a run. Bounded "
        "below rather than above -- a `fromSeq` past the end is a run with nothing "
        "left to replay, which is an empty list and not an error.",
    ),
]


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a run",
    responses=ERROR_RESPONSES,
)
async def create_run(
    project_id: ProjectId,
    payload: RunCreateRequest,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> RunResponse:
    """Create a run from a plan, its specification document, and a base URL.

    The service owns the transaction: it re-checks ``plan.status`` against the
    same rule the client applies, materialises the spec and plan rows the four
    NOT NULL foreign keys require, fans the plan out into ``run_*`` rows, and
    commits once -- all before this returns 201.  A failure at any point leaves
    nothing behind.

    **The approval check is not an authority.**  ``plan.status`` arrives in the
    body, so this refuses a request the browser would have refused; it does not
    establish that anyone reviewed anything.  There is no Plan Approval API.
    """
    # The path's project first, then the one reference the body carries.  The plan
    # is *defined* in the body, not referenced by it -- the service materialises the
    # plan row inside the project authorised here, so there is no plan id that could
    # point at somebody else's project.  The environment id is a real reference, and
    # it is looked up *inside* this project: an id from another project is
    # indistinguishable from one that does not exist, and nothing is created until
    # both answers are yes.
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )
    await guest_access.require_environment_in_project(
        session, project=project, environment_public_id=payload.environment_id
    )

    return await runs.create_run(session, project_id=project_id, payload=payload)


@router.get(
    "/projects/{project_id}/runs",
    response_model=list[RunListItem],
    summary="List a project's runs",
    responses=ERROR_RESPONSES,
)
async def list_runs(
    project_id: ProjectId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
    limit: RunLimit = DEFAULT_RUN_LIMIT,
    offset: RunOffset = 0,
) -> list[RunListItem]:
    """Return the project's runs, newest first.

    A bare array, because that is what the frontend reads: ``RunsView`` iterates
    the response directly and the contract fixes the body as ``TestRun[]``.  That
    is also why ``limit`` / ``offset`` are query parameters with no envelope
    around them -- paging changes how many rows come back, never the shape.

    Each row's ``summary`` is aggregated per request rather than stored, and the
    whole page is three queries regardless of size.  A project with no runs is
    ``200`` with ``[]``; a project that does not exist is ``404``.

    **The default ``limit`` is a ceiling, not a promise of completeness.**  The
    frontend has no paging UI and no ``listRuns`` action yet, so today it cannot
    ask for page two -- a project with more than ``limit`` runs would render as
    if it had ``limit``.
    """
    # Ownership first: the listing is a query about one project, and it only runs
    # once that project is known to be this guest's.
    await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    return await runs.list_runs(
        session, project_id=project_id, limit=limit, offset=offset
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Read a run, with its scenarios",
    responses=ERROR_RESPONSES,
)
async def get_run(
    run_id: RunId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> RunDetailResponse:
    """Return a run together with the scenario, step and assertion rows it produced.

    ``{ run, scenarios, lastSeq }`` -- ``RunDetail`` in
    ``frontend/src/types/run.ts``, which is the refresh path: the snapshot fixes
    a point in the stream, ``lastSeq`` is the mark to subscribe from, and the
    two together rebuild a run the browser kept nothing about.

    The service reads the tree as sets -- one statement per level, never one per
    row -- and orders every level explicitly, because the frontend matches rows
    by id equality with no positional fallback.

    A run that does not exist is a real 404, which the frontend needs in order to
    distinguish "not found" from "not loaded yet": its detail view keys the empty
    state off exactly that.  The id is a UUID string in the path and is not
    range-checked here -- an id that cannot be a UUID is a run that does not
    exist, not a failed request, so it is a 404 as well.
    """
    # run -> project -> owner, before the run, its tree or its events are read.  The
    # path id is the row key (test_runs has no public id), which is precisely why
    # ownership has to be checked rather than assumed.
    await guest_access.require_guest_run_project(session, run_id=run_id, guest=guest)

    return await runs.get_run_detail(session, run_id=run_id)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunCancelResponse,
    summary="Cancel a run",
    responses=ERROR_RESPONSES,
)
async def cancel_run(
    run_id: RunId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> RunCancelResponse:
    """Ask a run to stop, and return it as it stands.

    ``200`` with the run in whatever state it is in now -- including the state it
    was already in.  Cancelling something that has finished (``passed``,
    ``failed``, ``cancelled``) is not an error and not a second transition: the
    caller gets the same run back and no new ``run.cancelled`` event is written.
    That is what the frontend's ``cancelRun()`` promises ("Returns the run as it
    stands"), and a 409 here would turn a race the page cannot lose -- its button
    is disabled for terminal runs -- into a sentence about a run that is already
    stopped.

    The transition itself is conditional, so two requests that arrive together
    produce one cancellation rather than one cancellation and one failure.  A run
    that does not exist is a 404, and an id that cannot be a UUID is a 404 as
    well rather than a 500 from PostgreSQL's type parser.
    """
    # Somebody else's run cannot be cancelled by guessing its id: the state change
    # is only reached through a run this guest owns.
    await guest_access.require_guest_run_project(session, run_id=run_id, guest=guest)

    return await runs.cancel_run(session, run_id=run_id)


@router.get(
    "/runs/{run_id}/events",
    response_model=list[RunEventResponse],
    summary="Replay a run's events",
    responses=ERROR_RESPONSES,
)
async def get_run_events(
    run_id: RunId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
    from_seq: RunFromSeq = DEFAULT_FROM_SEQ,
) -> list[RunEventResponse]:
    """Return the run's persisted events from ``fromSeq`` onwards, in ``seq`` order.

    A bare array, like the run list and for the same reason: the contract fixes
    the body as a list of records, and an envelope would be a second shape the
    client has to unwrap before it can fold the events into the run it already
    holds.

    **This is replay, not streaming.**  The response is everything the run has
    said from ``fromSeq`` up to now and the connection closes; nothing here is
    long-lived, nothing is pushed, and no frame format is implied.  That is what
    makes the endpoint usable *before* the stream exists: a client can take the
    snapshot from ``GET /api/runs/{run_id}``, replay the tail from here, and
    arrive at the state a subscriber would have had -- which is the property the
    high-water mark exists for.

    A run that does not exist is a 404, exactly as on the detail and cancel
    routes, and an id that cannot be a UUID is one as well rather than a 500 from
    PostgreSQL's type parser.  A run that exists and has said nothing yet is
    ``200`` with an empty list: the collection is there, it is simply empty, and
    answering 404 would tell a client its run had vanished.

    ``fromSeq`` is inclusive and must be at least 1; anything else is rejected by
    the shared validation handler, in the envelope every other route uses.  There
    is no `limit`: paging a stream is a design of its own, and this phase settles
    only the resume point.
    """
    # Checked before the replay, so fromSeq cannot be used to walk into another
    # project's events: the sequence number selects within a run, never across one.
    await guest_access.require_guest_run_project(session, run_id=run_id, guest=guest)

    return await runs.get_run_events(session, run_id=run_id, from_seq=from_seq)


def _stream_from_seq(*, from_seq: int | None, last_event_id: str | None) -> int:
    """Where a stream starts: fromSeq, else one past Last-Event-ID, else 1.

    The two inputs answer different questions and the precedence is not a
    preference: `fromSeq` is a client saying where it wants to start, and
    `Last-Event-ID` is the browser saying where it *got to* after a drop.  An
    explicit request wins over an automatic one.

    `Last-Event-ID` is a receipt, so the stream resumes at one past it -- resuming
    *at* it would re-send an event the client already folded in.  A value that is
    not a whole number of events is refused rather than ignored: the client
    believes it has a resume point, and quietly starting from the beginning would
    replay history it has already read with nothing to say so.
    """
    if from_seq is not None:
        return from_seq

    if last_event_id is None:
        return DEFAULT_FROM_SEQ

    try:
        received = int(last_event_id)
    except ValueError:
        received = -1

    if received < 0:
        raise AppError(
            400,
            code="invalid-request",
            message_key=_STREAM_FAILED,
            details=[
                {
                    "field": "Last-Event-ID",
                    "reason": "must be a non-negative integer seq",
                    "received": last_event_id,
                }
            ],
        )

    return received + 1


@router.get(
    "/runs/{run_id}/events/stream",
    response_class=StreamingResponse,
    summary="Follow a run's events",
    responses={
        **ERROR_RESPONSES,
        400: {
            "model": ErrorResponse,
            "description": "The Last-Event-ID header is not a sequence number.",
        },
    },
)
async def stream_run_events(
    run_id: RunId,
    request: Request,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
    from_seq: RunStreamFromSeq = None,
    last_event_id: LastEventId = None,
) -> StreamingResponse:
    """Stream the run's events, from where the client left off, as they are written.

    ``text/event-stream``, one frame per event: the SSE id is the event's ``seq``,
    the SSE event name is its type, and the data object is the frontend's
    ``RunEvent`` -- its ``type`` plus the payload's own fields.  Nothing is buffered
    and nothing is pushed from anywhere but ``run_events``, so a client that
    reconnects with ``Last-Event-ID`` sees the same stream it would have seen had
    it never dropped.

    **Where it starts.**  ``fromSeq`` if the client sent one, otherwise one past
    ``Last-Event-ID` -- the header is the receipt for an event that was already
    delivered, so resuming *at* it would repeat it -- otherwise the beginning.  A
    header that is not a sequence number is a 400 rather than a silent fallback:
    the client asked to resume somewhere specific, and starting over without
    saying so is how a stream quietly replays a run the user has already read.

    **When it ends.**  When the run has finished and every event it produced has
    been sent, or when the client goes away -- not while the run is still going.
    The server closes the connection in both cases; there is no final frame,
    because the end of a stream is the end of the response.

    The 404 for an unknown run is raised *before* the response starts, which is
    why the run is looked up here rather than inside the generator: once the first
    byte is on the wire the status line has been sent, and the only honest thing
    left to do with a run that does not exist is close.
    """
    # Authorization, like the run's existence, is settled *before* the response
    # starts: the status line is the point of no return, and a guest who does not
    # own this run gets an ordinary 404 rather than an open stream.  No frame can
    # have been written at this point -- there is no response object yet.
    await guest_access.require_guest_run_project(session, run_id=run_id, guest=guest)

    start = _stream_from_seq(from_seq=from_seq, last_event_id=last_event_id)
    run_uuid = await runs.resolve_run_for_stream(session, run_id=run_id)

    # The session has answered the only question this request needs answered
    # before the stream starts.  Holding it open would pin a pooled connection for
    # as long as somebody watches a run, and the stream reads through short-lived
    # sessions of its own instead.
    await session.close()

    return StreamingResponse(
        runs.stream_run_events(
            run_id=run_uuid,
            from_seq=start,
            disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
