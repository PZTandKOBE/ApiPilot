"""Project, environment and project-spec reads and writes.

Everything is scoped to the verified guest: list by the owner column rather than
filtering later, create with the identity the server verified, and update only
after the route dependency has proved project access.

**A project starts with one environment.**  A run needs an environment id, so
project creation also creates a default environment with the base URL the caller
supplied (or a loopback default), and returns it in the listing.  Additional
environments can be created later; they are never default, start with no
variables, and do not share rows with the existing ones.  Environment edits are
limited to name, kind and base URL; variables and auth rows stay separate.

**The spec read is a summary.**  The overview only needs the latest document's
name, type, endpoint count and timestamps.  The document content and parsed tree
remain out of this surface.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.project import ApiEndpoint, ApiSpec, Environment, Project
from backend.db.models.user import GuestSession
from backend.schemas.project import (
    ProjectEnvironmentResponse,
    ProjectResponse,
    ProjectSpecResponse,
)
from backend.services.spec_identity import slugify, spec_id_for

__all__ = [
    "create_environment",
    "create_for_guest",
    "delete_project",
    "latest_spec",
    "list_for_guest",
    "update_environment",
    "update_name",
]

PROJECT_NOT_FOUND_CODE = "project-not-found"
ENVIRONMENT_NOT_FOUND_CODE = "environment-not-found"
ENVIRONMENT_CONFLICT_CODE = "environment-name-conflict"
_UPDATE_FAILED_KEY = "console.overview.saveFailed"
_NOT_FOUND_KEY = "console.runs.errors.notFound"

logger = logging.getLogger(__name__)

PROJECT_PREFIX = "prj"
ENVIRONMENT_PREFIX = "env"
DEFAULT_ENVIRONMENT_NAME = "Development"
DEFAULT_ENVIRONMENT_KIND = "development"
DEFAULT_ENVIRONMENT_BASE_URL = "http://127.0.0.1:8000"
"""Where a run would go before the caller says otherwise.

Loopback, because that is where `uv run backend` puts the service this project
tests in development, and because a placeholder that points at somebody's
production is a worse default than one that points at nothing.
"""

_NAME_LIMIT = 200
"""The projects.name column's width."""

_SUFFIX_LENGTH = 8
_ENVIRONMENT_SLUG_LIMIT = 40


def project_public_id(name: str) -> str:
    """A stable-looking, unique public id: prj_<slug>_<random suffix>.

    The slug makes it readable in a log line and keeps the console's existing
    shape (prj_orders), and the suffix is what makes it unique without a
    round trip -- two guests may legitimately name their project the same thing.
    """
    slug = slugify(name)[: _NAME_LIMIT - len(PROJECT_PREFIX) - _SUFFIX_LENGTH - 2] or "project"

    return f"{PROJECT_PREFIX}_{slug}_{uuid.uuid4().hex[:_SUFFIX_LENGTH]}"


async def _spec_name(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The document this project most recently had parsed, if any."""
    found = await session.execute(
        select(ApiSpec.filename, ApiSpec.name)
        .where(ApiSpec.project_id == project_id)
        .order_by(ApiSpec.created_at.desc())
        .limit(1)
    )
    row = found.one_or_none()

    if row is None:
        return None

    return row[0] or row[1]


def _project_not_found(project_id: str) -> AppError:
    return AppError(
        404,
        code=PROJECT_NOT_FOUND_CODE,
        message_key=_NOT_FOUND_KEY,
        details={"projectId": project_id},
    )


async def _lookup_project(session: AsyncSession, public_id: str) -> Project:
    project = (
        await session.execute(select(Project).where(Project.public_id == public_id))
    ).scalar_one_or_none()

    if project is None:
        raise _project_not_found(public_id)

    return project


async def _environments(
    session: AsyncSession, project_id: uuid.UUID
) -> list[ProjectEnvironmentResponse]:
    found = await session.execute(
        select(Environment)
        .where(Environment.project_id == project_id)
        .order_by(Environment.created_at)
    )

    return [
        ProjectEnvironmentResponse(
            id=environment.public_id,
            name=environment.name,
            kind=environment.kind,
            base_url=environment.base_url,
            # Variables are not read here on purpose: this response is about the
            # project, and the console has no screen that shows a value.
            variables=[],
        )
        for environment in found.scalars().all()
    ]


async def _response(session: AsyncSession, project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.public_id,
        name=project.name,
        description=project.description or "",
        spec_name=await _spec_name(session, project.id),
        environments=await _environments(session, project.id),
        updated_at=project.updated_at,
    )


async def list_for_guest(session: AsyncSession, *, guest: GuestSession) -> list[ProjectResponse]:
    """Every project this guest owns, and nothing else.

    The WHERE clause is the authorization: there is no path here that reads a
    project owned by another guest or by a registered user, so no response can
    leak one.
    """
    owner_filter = (
        Project.user_id == guest.user_id
        if guest.user_id is not None
        else Project.guest_session_id == guest.id
    )
    found = await session.execute(
        select(Project)
        .where(owner_filter)
        .order_by(Project.created_at)
    )

    return [await _response(session, project) for project in found.scalars().all()]


async def delete_project(session: AsyncSession, *, project_id: str) -> None:
    """Permanently delete one project and everything that belongs to it.

    The database schema already owns the deletion graph: every project-scoped
    table has an ON DELETE CASCADE / SET NULL relationship to projects, and the
    few NO ACTION references are deferred to the end of the statement so the
    cascading rows disappear together.  Reports are stored as bytes in
    run_reports, so the cascade removes the PDF payload and metadata with the
    project; there is no filesystem path to clean up.

    The owner row (User / GuestSession) is deliberately outside that graph: it
    is identity, not project data.
    """
    project = await _lookup_project(session, project_id)

    await session.delete(project)
    await session.flush()

    logger.info("deleted project %s", project.public_id)


async def update_name(
    session: AsyncSession, *, project_id: str, name: str
) -> ProjectResponse:
    """Rename one project and return the fresh aggregate.

    Authorization is the route dependency's job; this function is deliberately
    only the data change. The timestamp is assigned explicitly instead of
    relying on onupdate so the response can be built from the same row in the
    request's transaction.
    """
    project = await _lookup_project(session, project_id)
    project.name = name.strip()
    project.updated_at = datetime.now(timezone.utc)

    await session.flush()

    return await _response(session, project)


def environment_public_id(name: str) -> str:
    """A readable, project-scoped public id for a new environment.

    The project-scoping unique constraint is what makes the id unique; the
    suffix keeps two environments with the same name from colliding during the
    window before the name pre-check would reject the second one.
    """
    slug = slugify(name)[:_ENVIRONMENT_SLUG_LIMIT] or "environment"

    return f"{ENVIRONMENT_PREFIX}_{slug}_{uuid.uuid4().hex[:_SUFFIX_LENGTH]}"


async def create_environment(
    session: AsyncSession,
    *,
    project_id: str,
    name: str,
    kind: str,
    base_url: str,
) -> ProjectResponse:
    """Create one additional environment under an existing project.

    The new row is never the default: projects created by this service already
    have their default environment, and this operation must not move that
    pointer or change which environment an existing API request uses.  It also
    starts with no variables; nothing is copied from a sibling environment.
    """
    project = await _lookup_project(session, project_id)
    cleaned_name = name.strip()

    duplicate = (
        await session.execute(
            select(Environment.id).where(
                Environment.project_id == project.id,
                Environment.name == cleaned_name,
            )
        )
    ).scalar_one_or_none()

    if duplicate is not None:
        raise AppError(
            409,
            code=ENVIRONMENT_CONFLICT_CODE,
            message_key=_UPDATE_FAILED_KEY,
            details={"name": cleaned_name},
        )

    environment = Environment(
        project_id=project.id,
        public_id=environment_public_id(cleaned_name),
        name=cleaned_name,
        kind=kind,
        base_url=base_url.strip(),
        is_default=False,
    )
    session.add(environment)
    project.updated_at = datetime.now(timezone.utc)

    await session.flush()

    logger.info(
        "created environment %s for project %s",
        environment.public_id,
        project.public_id,
    )

    return await _response(session, project)


async def update_environment(
    session: AsyncSession,
    *,
    project_id: str,
    environment_id: str,
    name: str,
    kind: str,
    base_url: str,
) -> ProjectResponse:
    """Update the editable fields of one environment in one project.

    The lookup is scoped by project id first, so an environment public id from a
    different project is a 404 rather than a row that can be updated. Variables,
    auth rows and the default flag are not touched.
    """
    project = await _lookup_project(session, project_id)

    environment = (
        await session.execute(
            select(Environment).where(
                Environment.project_id == project.id,
                Environment.public_id == environment_id,
            )
        )
    ).scalar_one_or_none()

    if environment is None:
        raise AppError(
            404,
            code=ENVIRONMENT_NOT_FOUND_CODE,
            message_key=_NOT_FOUND_KEY,
            details={"environmentId": environment_id},
        )

    duplicate = (
        await session.execute(
            select(Environment.id).where(
                Environment.project_id == project.id,
                Environment.name == name.strip(),
                Environment.id != environment.id,
            )
        )
    ).scalar_one_or_none()

    if duplicate is not None:
        raise AppError(
            409,
            code=ENVIRONMENT_CONFLICT_CODE,
            message_key=_UPDATE_FAILED_KEY,
            details={"environmentId": environment_id},
        )

    environment.name = name.strip()
    environment.kind = kind
    environment.base_url = base_url.strip()
    project.updated_at = datetime.now(timezone.utc)

    await session.flush()

    return await _response(session, project)


async def latest_spec(
    session: AsyncSession, *, project_id: str
) -> ProjectSpecResponse | None:
    """The project's most recently persisted spec, or None when it has none.

    api_specs is the source of truth here; projects has no spec name column of
    its own. The endpoint count is a real COUNT over the document's parsed
    endpoints, not a client-side guess.
    """
    project = await _lookup_project(session, project_id)

    spec = (
        await session.execute(
            select(ApiSpec)
            .where(ApiSpec.project_id == project.id)
            .order_by(ApiSpec.created_at.desc(), ApiSpec.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if spec is None:
        return None

    endpoint_count = (
        await session.scalar(
            select(func.count()).select_from(ApiEndpoint).where(ApiEndpoint.spec_id == spec.id)
        )
    ) or 0

    return ProjectSpecResponse(
        id=spec_id_for(spec.slug),
        name=spec.name,
        filename=spec.filename,
        spec_type=spec.spec_type,
        content_format=spec.content_format,
        version=spec.version,
        source=spec.source,
        endpoint_count=endpoint_count,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )


async def create_for_guest(
    session: AsyncSession,
    *,
    guest: GuestSession,
    name: str,
    base_url: str | None = None,
) -> ProjectResponse:
    """Create a project owned by the verified guest, with one environment.

    Ownership is not a parameter: it is the identity the request arrived with, so
    a body that claims somebody else's session cannot be honoured even if a caller
    works out the field name.
    """
    project = Project(
        public_id=project_public_id(name),
        name=name.strip()[:_NAME_LIMIT],
        description=None,
        guest_session_id=None if guest.user_id is not None else guest.id,
        user_id=guest.user_id,
    )
    session.add(project)
    await session.flush()

    environment = Environment(
        project_id=project.id,
        public_id=f"{ENVIRONMENT_PREFIX}_{project.public_id}",
        name=DEFAULT_ENVIRONMENT_NAME,
        kind=DEFAULT_ENVIRONMENT_KIND,
        base_url=(base_url or DEFAULT_ENVIRONMENT_BASE_URL).strip(),
        is_default=True,
    )
    session.add(environment)
    await session.flush()

    logger.info("created project %s for guest %s", project.public_id, guest.id)

    return await _response(session, project)
