"""Project endpoints: the project, its environments and its current spec.

All routes are authenticated:

* `GET /api/projects` -- the projects this guest owns.
* `POST /api/projects` -- create one, owned by the identity the server verified.
* `PATCH /api/projects/{project_id}` -- rename a project.
* `POST /api/projects/{project_id}/environments` -- create another environment
  in the project.
* `PATCH /api/projects/{project_id}/environments/{environment_id}` -- update an
  environment's name, kind and base URL.
* `GET /api/projects/{project_id}/spec` -- read the latest persisted spec.
* `DELETE /api/projects/{project_id}` -- permanently delete the project and its
  project-owned data; identity rows survive.
* `POST /api/projects/{project_id}/proxy` -- send one manual API request to the
  API the user is testing, on behalf of the project's owner.

**Why the auth is shared.**  A project is the unit of ownership every other
resource hangs from. Listing and every project-scoped route read the owner from
the verified identity; request bodies cannot name an owner, because the schemas
forbid unknown fields.  Environment writes are scoped by project id first, so
an environment id from another project is a 404 rather than a writable row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status

from backend.api.deps import CurrentGuestSessionDep, SessionDep
from backend.api.errors import ERROR_RESPONSES
from backend.db.models.user import GuestSession
from backend.schemas.project import (
    EnvironmentCreateRequest,
    EnvironmentUpdateRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSpecResponse,
    ProjectUpdateRequest,
)
from backend.schemas.proxy import ProxyRequest, ProxyResponse
from backend.services import api_proxy_route, guest_limits, projects
from backend.services.guest_access import require_guest_project_access

__all__ = ["router"]

router = APIRouter(prefix="/api", tags=["projects"])

ProjectId = Annotated[
    str,
    Path(
        description=(
            "The project's public id.  Its owner is the verified guest session, "
            "never anything in the request body."
        )
    ),
]
"""The {`project_id`} path parameter, documented where it is declared.

A named alias rather than a bare `str` so the route and the ownership dependency
below describe the same parameter once.
"""


async def _require_project_access(
    project_id: ProjectId,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> GuestSession:
    """Prove the guest owns the project before the route body runs.

    A dependency rather than a line inside the handler, because this is the one
    check that must happen *before any network work at all*: FastAPI resolves
    dependencies before it calls the route function, so a caller who owns nothing
    cannot reach the forwarder even if a later edit reorders the body.
    """
    # The return value is the *guest*, not the project: the handler and the
    # service below authorize with the verified identity, and a project passed
    # where a session is expected compares its own id against the row's owner --
    # which is a 404 for every caller.  (It was, until this line was fixed.)
    await require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    return guest


ProjectOwnerDep = Annotated[GuestSession, Depends(_require_project_access)]

EnvironmentId = Annotated[
    str,
    Path(description="The environment's project-scoped public id, e.g. env_orders_staging."),
]


@router.get(
    "/projects",
    response_model=list[ProjectResponse],
    summary="List the current guest's projects",
    responses=ERROR_RESPONSES,
)
async def list_projects(
    session: SessionDep, guest: CurrentGuestSessionDep
) -> list[ProjectResponse]:
    """Every project this guest owns, oldest first.

    The filter is the authorization: the query selects on `guest_session_id`, so
    another guest's project -- or a registered user's -- is never read, never
    serialised and never returned for a client to filter out.  A guest with no
    projects gets `200` with `[]`, which is how the console knows to create
    its first one.
    """
    return await projects.list_for_guest(session, guest=guest)


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project for the current guest",
    responses=ERROR_RESPONSES,
)
async def create_project(
    request: Request,
    payload: ProjectCreateRequest,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> ProjectResponse:
    """Create a project, and the one environment a run needs to have somewhere to go.

    The owner is `guest.id`, read from the verified session -- never from the
    body, which has no field for it.  The public id is generated server-side
    (`prj_<slug>_<suffix>`), so two guests naming a project the same thing get two
    projects and no collision.

    `201` with the project as the console reads it, including the default
    environment's id, because a client that had to guess it would have no way to
    start a run.
    """
    await guest_limits.enforce_project_limit(
        session, guest=guest, settings=request.app.state.auth.settings
    )
    created = await projects.create_for_guest(
        session, guest=guest, name=payload.name, base_url=payload.base_url
    )
    await session.commit()

    return created


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Rename a project",
    responses=ERROR_RESPONSES,
)
async def update_project(
    project_id: ProjectId,
    payload: ProjectUpdateRequest,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> ProjectResponse:  # noqa: ARG001 - the dependency is the authorization
    """Change the project's display name.

    The project id in the path is authorized by ProjectOwnerDep before this
    body runs.  Only the name is writable here; ownership, timestamps and
    derived fields stay server-owned.
    """
    updated = await projects.update_name(session, project_id=project_id, name=payload.name)
    await session.commit()

    return updated


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and its project-owned data",
    responses=ERROR_RESPONSES,
)
async def delete_project(
    project_id: ProjectId,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> Response:  # noqa: ARG001 - the dependency is the authorization
    """Permanently delete this project and every row scoped to it.

    The ownership dependency has already proved the caller may touch the
    project. The database cascade removes environments, variables, specs,
    endpoint rows, agent tasks and audits, plans/versions, runs and their
    snapshots, and the PDF report bytes and metadata. The owner identity row is
    not part of that graph and survives.
    """
    await projects.delete_project(session, project_id=project_id)
    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/environments",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an environment in a project",
    responses=ERROR_RESPONSES,
)
async def create_project_environment(
    project_id: ProjectId,
    payload: EnvironmentCreateRequest,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> ProjectResponse:  # noqa: ARG001 - the dependency is the authorization
    """Create another environment under this project.

    The returned aggregate includes the new environment; the existing default
    environment and every sibling row stay untouched.  New environments start
    with no variables and are never marked as default, so creating one cannot
    change the environment an existing API request uses.
    """
    updated = await projects.create_environment(
        session,
        project_id=project_id,
        name=payload.name,
        kind=payload.kind,
        base_url=payload.base_url,
    )
    await session.commit()

    return updated


@router.patch(
    "/projects/{project_id}/environments/{environment_id}",
    response_model=ProjectResponse,
    summary="Update an environment's basic fields",
    responses=ERROR_RESPONSES,
)
async def update_project_environment(
    project_id: ProjectId,
    environment_id: EnvironmentId,
    payload: EnvironmentUpdateRequest,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> ProjectResponse:  # noqa: ARG001 - the dependency is the authorization
    """Update the name, kind and base URL of an environment in this project.

    The lookup is scoped by the project id in the path as well as the
    environment id, so an environment id from another project is a 404.  The
    route does not accept variables, auth rules or the default flag; those
    remain untouched.
    """
    updated = await projects.update_environment(
        session,
        project_id=project_id,
        environment_id=environment_id,
        name=payload.name,
        kind=payload.kind,
        base_url=payload.base_url,
    )
    await session.commit()

    return updated


@router.get(
    "/projects/{project_id}/spec",
    response_model=ProjectSpecResponse | None,
    summary="Read the project's current API specification",
    responses=ERROR_RESPONSES,
)
async def get_project_spec(
    project_id: ProjectId,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> ProjectSpecResponse | None:  # noqa: ARG001 - the dependency is the authorization
    """The latest persisted spec for this project, or null when it has none.

    Null is a successful answer, not a 404: the overview needs to distinguish
    "this project has no spec yet" from "the request failed".  The response
    deliberately excludes the document content and the parsed endpoint tree.
    """
    return await projects.latest_spec(session, project_id=project_id)


@router.post(
    "/projects/{project_id}/proxy",
    response_model=ProxyResponse,
    summary="Send one manual API request to the API under test",
    responses=ERROR_RESPONSES,
)
async def proxy_request(
    project_id: ProjectId,
    payload: ProxyRequest,
    session: SessionDep,
    owner: ProjectOwnerDep,
) -> ProxyResponse:  # noqa: ARG001 - the dependency is the authorization
    """Forward one request the user composed, and return the target's answer.

    `owner` is the authorization: the dependency above runs the project ownership
    check *before* this body is entered, so a caller who does not own `project_id`
    is refused before any name is resolved or any socket is opened.  That ordering
    is the whole reason it is a dependency rather than a line here.

    What travels upstream is what the user configured for the target.  This
    service's own credential does not: `X-Guest-Session` is dropped by name
    (see `services/api_proxy`), so the identity that reached *this* backend can
    never be presented to somebody else's API.

    The target's status is returned as-is, including 4xx and 5xx -- those are
    answers about the user's request, not failures of this proxy.  Only a refused
    target, a timeout or a transport failure becomes an error envelope.
    """
    return await api_proxy_route.proxy_for_guest(
        session, guest=owner, project_id=project_id, payload=payload
    )
