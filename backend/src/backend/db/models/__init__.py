"""Every model, imported for its registration side effect.

Importing a model module is what puts its table on ``Base.metadata``, and
nothing else does that.  ``alembic/env.py`` imports this package so that
autogenerate has something to compare against the database -- without it the
first migration comes out empty rather than failing, which is why this file
exists at all.

Cross-module references are annotations only.  Each module imports the classes
it names in a relationship under ``if TYPE_CHECKING`` and passes the target to
``relationship()`` as a string, so the four modules have no import cycle at
runtime and their order here is free.

Batch 1 covers 17 tables and batch 2 adds the five ``run_*`` ones, for 22.
``test_workflows`` remains deferred: the frontend has no type for it (the
"workflow" on screen is the agent pipeline, not a plan node graph) and nothing
consumes ``nodes`` / ``edges``, so its structure has to be defined before the
table is.  Nothing in the 22 refers to it.

The Run-ID contract they must honour
------------------------------------

Settled now, while the tables do not exist, because getting it wrong is silent.

    ``run_scenarios`` / ``run_steps`` / ``run_assertions`` each own an
    independent UUID primary key, and each also carries a ``source_*_id``
    pointing at the definition it came from, plus the stable key.

A ``test_step`` is executed many times -- once per run -- so ``test_steps.id``
cannot be the primary key of ``run_steps``.

The internal UUID is never exposed over the API.  When a run is serialised, the
``id`` of a run scenario / step / assertion is the **source id echoed back**,
not the execution row's UUID.  The frontend matches run events to run steps by
id equality and has no positional fallback: rename it and the run detail page
renders a shell whose rows never update, without raising anything.

The same rule binds ``run_events.payload``: the ``scenarioId`` / ``stepId`` /
``assertionId`` written into it are the plan-side stable keys, never the UUIDs
of the run rows.  Nothing in the schema can enforce that one -- it is silent
when broken -- so it lives here, where the tables were designed.
"""

from backend.db.models.agent import (
    AgentTask,
    TestAssertion,
    TestPlan,
    TestScenario,
    TestStep,
)
from backend.db.models.project import (
    ApiEndpoint,
    ApiSpec,
    Environment,
    EnvironmentAuth,
    EnvironmentVariable,
    Project,
    RequestCollection,
    SavedRequest,
)
from backend.db.models.result import (
    ApiRequestHistory,
    RunAssertion,
    RunEvent,
    RunEvidence,
    RunScenario,
    RunStep,
    TestRun,
)
from backend.db.models.user import GuestSession, User

__all__ = [
    "AgentTask",
    "ApiEndpoint",
    "ApiRequestHistory",
    "ApiSpec",
    "Environment",
    "EnvironmentAuth",
    "EnvironmentVariable",
    "GuestSession",
    "Project",
    "RequestCollection",
    "RunAssertion",
    "RunEvent",
    "RunEvidence",
    "RunScenario",
    "RunStep",
    "SavedRequest",
    "TestAssertion",
    "TestPlan",
    "TestRun",
    "TestScenario",
    "TestStep",
    "User",
]
