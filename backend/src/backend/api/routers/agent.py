"""Agent task endpoints.

Two routes, and their paths are not a style choice -- they follow the rule the
run routes already established (`frontend/docs/phase-6.2-backend-rest-contract.md`
section 5): **a collection lives under its project, an item is addressed by its
own id.**

* `POST /api/projects/{project_id}/agent/tasks` -- ask the agent for a plan.
* `GET  /api/agent/tasks/{task_id}`          -- read the task and its plan.

The alternative the brief floated, `POST /api/agent/tasks` with the project only
in the body, would have been a second addressing convention for one resource --
and the project already appears in the body either way, because the frozen
`AgentTaskInput` carries it.

There is deliberately no `POST /api/agent/tasks/{task_id}/run`.  A sub-resource
would exist to start something that outlives the request, and this pipeline does
not: parse, analyze, generate, validate and persist are pure computation over a
document the server already holds, with no HTTP and no queue in the path.  The
create call runs the whole lifecycle and answers with the finished task, which is
also what makes the lifecycle observable -- one request, three committed states.

Neither route can start a run: the agent's output is a `draft` plan, and only a
human approving it (and the run endpoint's own gate) can go further.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from backend.api.deps import CurrentGuestSessionDep, SessionDep
from backend.api.errors import ERROR_RESPONSES
from backend.schemas.agent import AgentTaskCreateRequest, AgentTaskResponse
from backend.schemas.agent_audit import AgentTaskAuditResponse
from backend.services import agent, guest_access

__all__ = ["router"]

router = APIRouter(prefix="/api", tags=["agent"])

ProjectId = Annotated[
    str,
    Path(
        description="The project's `public_id`, e.g. `prj_orders`. Not a UUID.",
        examples=["prj_orders"],
    ),
]

TaskId = Annotated[
    str,
    Path(
        description=(
            "The agent task's id. A UUID, like `test_runs.id`: `agent_tasks` has no "
            "`public_id` column, so the row key is the external one."
        ),
        examples=["6f1c1f4e-4a4e-4e2a-9f0e-3a1d2b3c4d5e"],
    ),
]


@router.post(
    "/projects/{project_id}/agent/tasks",
    response_model=AgentTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ask the agent for a test plan",
    responses=ERROR_RESPONSES,
)
async def create_agent_task(
    project_id: ProjectId,
    payload: AgentTaskCreateRequest,
    session: SessionDep,
    guest: CurrentGuestSessionDep,
) -> AgentTaskResponse:
    """Run the agent pipeline for one document and one prompt.

    The service owns both transactions: the task row is committed before the
    pipeline runs, so a refusal is recorded as a failed task rather than lost,
    and the plan tree is committed only after validation has accepted it.

    A plan id that already exists is refused with `409` and **no task row**: a
    second prompt against the same document names the same plan, and this version
    has no versioning to put the second answer somewhere honest.

    The agent cannot reach a run: nothing here writes `test_runs`, the `run_*`
    snapshot tables or `run_events`, and the plan it produces is a draft.
    """
    # Authorization before anything is written.  The pipeline commits a task row
    # first, so a guest who does not own this project has to be turned away here --
    # before that commit, and before a spec, a plan or an audit row can exist.
    project = await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    if payload.environment_id is not None:
        # An environment id from another project is not a parameter: the lookup is
        # scoped to the project the path named, and not finding it ends the request.
        await guest_access.require_environment_in_project(
            session, project=project, environment_public_id=payload.environment_id
        )

    return await agent.start_task(session, project_id=project_id, payload=payload)


@router.get(
    "/agent/tasks/{task_id}",
    response_model=AgentTaskResponse,
    summary="Read an agent task and its plan",
    responses=ERROR_RESPONSES,
)
async def get_agent_task(
    task_id: TaskId, session: SessionDep, guest: CurrentGuestSessionDep
) -> AgentTaskResponse:
    """The task, its status, and a summary of the plan it produced.

    A failed task answers `200` with `status: failed` and no failure reason:
    `agent_tasks` has no error column, and the reason was reported on the
    response that caused it.

    **No variables, ever.**  The response has no field for a value and the query
    reads no column that holds one.
    """
    # task -> project -> owner, along the real foreign key, before the task or its
    # plan tree is read.  A task id from another guest's project is a 404 with
    # exactly the shape of a task that does not exist.
    await guest_access.require_guest_task_project(session, task_id=task_id, guest=guest)

    return await agent.get_task(session, task_id=task_id)


@router.get(
    "/agent/tasks/{task_id}/audit",
    response_model=AgentTaskAuditResponse,
    summary="Read what the agent decided, and what it cost",
    responses=ERROR_RESPONSES,
)
async def get_agent_task_audit(
    task_id: TaskId, session: SessionDep, guest: CurrentGuestSessionDep
) -> AgentTaskAuditResponse:
    """The task's decisions: who ran each stage, what they produced, what it cost.

    One record per task, written as the pipeline runs.  It answers what the task
    response cannot: which model analysed the document and with which prompt, what
    the analysis understood, what the planner designed before the runtime
    completed it, how many tokens each call reported -- and, when a task failed,
    the stage, the code and a bounded sentence saying why.

    **No secrets, by construction.**  The audit stores no document, no prompt
    text, no request or response body, no header and no credential; a run-time
    value the task declared is removed before anything is written.  Reading it
    back therefore cannot return one.
    """
    # The same chain as the task route -- audit -> task -> project -> owner --
    # which is what makes the two routes agree about who may read what.
    await guest_access.require_guest_task_project(session, task_id=task_id, guest=guest)

    return await agent.get_task_audit(session, task_id=task_id)
