"""Who a guest may reach: the project ownership check, in one place.

Phase 8.5 Step 2.  The contract (`docs/identity-access-contract.md`, sections
6.3 and 6.4) fixes the rule this module implements:

    verified Guest Session -> resource -> ...foreign keys... -> Project -> owner

**Why a function and not a WHERE clause in every query.**  Every resource the
product stores reaches a project through its own chain -- a task directly, an
audit through its task, a run step through its run -- so the *rule* is the same
while the *paths* differ.  Putting the rule here means a router that forgets it is
a router that never called this, rather than a router that wrote the join
slightly wrong.

**Not wired to the business routes yet.**  Phase 8.5 Step 2 builds the ability;
Step 3 applies it to the nine existing operations together with the frontend's
credential work, because enforcing it on the backend alone would lock every
browser out (contract section 8).  Until then this module is exercised by its own
tests, and the access review's measurements still describe unguarded routes.

**One answer for "not yours" and "not there".**  A project that does not exist, a
project owned by a registered user, and a project owned by another guest all
raise the same 404: a caller with a valid identity cannot use this endpoint to
learn that somebody else's project exists.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.agent import AgentTask
from backend.db.models.project import Environment, Project
from backend.db.models.result import TestRun
from backend.db.models.user import GuestSession

__all__ = [
    "CREATE_FAILED_CODE",
    "PROJECT_NOT_FOUND_CODE",
    "RUN_NOT_FOUND_CODE",
    "TASK_NOT_FOUND_CODE",
    "find_guest_project",
    "require_environment_in_project",
    "require_guest_project_access",
    "require_guest_run_project",
    "require_guest_task_project",
]

PROJECT_NOT_FOUND_CODE = "project-not-found"

# --------------------------------------------------------------------------- #
# Resources that reach a project through their own chain
#
# Every one of these answers the same question -- "is this row inside a project
# this guest owns" -- and each asks it along the foreign keys the schema actually
# has: a task and a run carry a project_id of their own, a plan or an environment
# is looked up *within* a project rather than by id alone.  Keeping them here is
# what stops nine routes from growing nine slightly different joins.
# --------------------------------------------------------------------------- #

TASK_NOT_FOUND_CODE = "task-not-found"
RUN_NOT_FOUND_CODE = "run-not-found"
CREATE_FAILED_CODE = "create-failed"

_CREATE_FAILED_MESSAGE_KEY = "console.runs.errors.createFailed"


def _not_found(code: str, message_key: str, **details: Any) -> AppError:
    return AppError(404, code=code, message_key=message_key, details=details or None)


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _project_owned_by(project: Project, guest: GuestSession) -> bool:
    """The one ownership rule for both deployment modes.

    A normal browser guest has no user_id and owns guest_session_id rows. An
    account's server-side guest has user_id and owns user_id rows; the account
    is resolved from the HttpOnly cookie before this check, never from a
    client-supplied guest token.
    """
    if guest.user_id is not None:
        return project.user_id == guest.user_id
    return project.guest_session_id == guest.id


async def require_guest_task_project(
    session: AsyncSession, *, task_id: str, guest: GuestSession
) -> tuple[AgentTask, Project]:
    """The task and its project, if this guest owns it; otherwise one 404.

    The chain is the real one -- agent_tasks.project_id -- not a check that the
    task merely exists: a task id is a UUID, and a UUID is not a permission.
    """
    parsed = _as_uuid(task_id)

    if parsed is None:
        raise _not_found(TASK_NOT_FOUND_CODE, _NOT_FOUND_MESSAGE_KEY, taskId=task_id)

    found = await session.execute(
        select(AgentTask, Project)
        .join(Project, Project.id == AgentTask.project_id)
        .where(AgentTask.id == parsed)
    )
    row = found.one_or_none()

    if row is None or not _project_owned_by(row[1], guest):
        raise _not_found(TASK_NOT_FOUND_CODE, _NOT_FOUND_MESSAGE_KEY, taskId=task_id)

    return row[0], row[1]


async def require_guest_run_project(
    session: AsyncSession, *, run_id: str, guest: GuestSession
) -> tuple[TestRun, Project]:
    """The run and its project, if this guest owns it; otherwise one 404.

    test_runs has no public id: the path id *is* the row key, which is exactly
    why the ownership check has to be made rather than assumed.
    """
    parsed = _as_uuid(run_id)

    if parsed is None:
        raise _not_found(RUN_NOT_FOUND_CODE, _NOT_FOUND_MESSAGE_KEY, runId=run_id)

    found = await session.execute(
        select(TestRun, Project)
        .join(Project, Project.id == TestRun.project_id)
        .where(TestRun.id == parsed)
    )
    row = found.one_or_none()

    if row is None or not _project_owned_by(row[1], guest):
        raise _not_found(RUN_NOT_FOUND_CODE, _NOT_FOUND_MESSAGE_KEY, runId=run_id)

    return row[0], row[1]


async def require_environment_in_project(
    session: AsyncSession, *, project: Project, environment_public_id: str
) -> Environment:
    """The environment, if it belongs to *this* project.

    The lookup is scoped by project rather than by id followed by a comparison, so
    a cross-project environment id can never be selected in the first place.
    """
    found = await session.execute(
        select(Environment).where(
            Environment.public_id == environment_public_id,
            Environment.project_id == project.id,
        )
    )
    environment = found.scalar_one_or_none()

    if environment is None:
        raise _not_found(
            CREATE_FAILED_CODE,
            _CREATE_FAILED_MESSAGE_KEY,
            environmentId=environment_public_id,
        )

    return environment


_NOT_FOUND_MESSAGE_KEY = "console.runs.errors.notFound"
"""The sentence the console already renders for a resource it cannot read.

The contract fixes the semantics (404, indistinguishable from absence) and the
message key; the *code* above is this check's own, so Step 3 can map it to
whatever a given route already answers without changing the status or the
sentence.
"""


async def find_guest_project(
    session: AsyncSession, *, project_public_id: str, guest: GuestSession
) -> Project | None:
    """The project that public id names, if this guest owns it.  Otherwise nothing.

    Ownership is read from the row, never from the request: a project owned by a
    registered user has a NULL `guest_session_id` and is therefore not this
    guest's, and a UUID that happens to be well formed never passes on its own.
    """
    if project_public_id.strip() == "":
        return None

    owner_filter = (
        Project.user_id == guest.user_id
        if guest.user_id is not None
        else Project.guest_session_id == guest.id
    )
    found = await session.execute(
        select(Project).where(
            Project.public_id == project_public_id,
            owner_filter,
        )
    )
    return found.scalar_one_or_none()


async def require_guest_project_access(
    session: AsyncSession, *, project_public_id: str, guest: GuestSession
) -> Project:
    """The project, or the one 404 that covers every reason it is not available."""
    project = await find_guest_project(
        session, project_public_id=project_public_id, guest=guest
    )

    if project is None:
        raise AppError(
            404,
            code=PROJECT_NOT_FOUND_CODE,
            message_key=_NOT_FOUND_MESSAGE_KEY,
            details={"projectId": project_public_id},
        )

    return project
