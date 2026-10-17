"""Result system: what actually happened.

``api_request_history`` and ``test_runs`` are deliberately separate tables even
though both record an HTTP outcome.  One is a request the *user* sent by hand
from the API client; the other is an automated execution of a plan.  Merging
them would make "show me what I sent" and "show me what the agent ran" the same
query with a discriminator, and would tie the manual path to a plan it does not
have.

Below ``test_runs`` sits the run detail tree -- ``run_scenarios``,
``run_steps``, ``run_assertions``, ``run_evidence`` and ``run_events``.  It is
a *snapshot* tree: every row is a copy of what the plan said at the moment it
executed, so a plan edited or regenerated afterwards cannot rewrite a finished
run.  That is why ``run_steps`` carries its own ``description`` / ``method`` /
``path`` instead of reaching back through ``source_step_id``, and why the
``source_*`` columns are nullable with ``SET NULL`` rather than ``NOT NULL``:
history must survive the deletion of what it came from.

Two rules hold across all five tables.

**An execution row owns its own primary key.**  A ``test_step`` runs once per
run, so ``test_steps.id`` cannot be the key of a ``run_steps`` row.  Each run
row has its own UUID *and* a ``source_*_id`` plus a stable key copied from the
plan.

**The internal UUID never leaves the process.**  When a run is serialised, the
``id`` of a run scenario / step / assertion is the stable key (``scenario_key``,
``step_key``, ``assertion_key``) echoed back byte-for-byte from the plan the
client sent -- and ``run_events.payload`` must name plan-side keys for
``scenarioId`` / ``stepId`` / ``assertionId`` too, never these UUIDs.  The
frontend reducer matches events to rows by id equality with no positional
fallback: emit the UUID and the run detail page renders a shell whose rows never
update, raising nothing.

Neither ``api_request_history`` nor the run tables define ``__repr__`` on the
fields that carry credentials: request history holds real ``Authorization``
headers and bodies.  SQLAlchemy's default repr prints no column values, so the
only way to leak them is to write one -- so none is written.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.db.models.agent import (
        TestAssertion,
        TestPlan,
        TestScenario,
        TestStep,
    )
    from backend.db.models.project import (
        ApiEndpoint,
        ApiSpec,
        Environment,
        Project,
        SavedRequest,
    )

__all__ = [
    "ApiRequestHistory",
    "RunAssertion",
    "RunEvent",
    "RunEvidence",
    "RunReport",
    "RunScenario",
    "RunStep",
    "TestRun",
]


class ApiRequestHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One request the user sent from the API client.

    The row is self-contained: ``method``, the URL and the request blobs are
    copied in, so the entry still reads correctly after the saved request it
    came from is edited or deleted (``saved_request_id`` is ``SET NULL``).

    ``request_url`` is the **unresolved template**, not the URL that went on the
    wire: ``/api/orders/{{order_id}}``.  Restoring a history entry has to bring
    the placeholders back, or the restored request is pinned to one order id and
    the variables it was written against are lost.  The resolved form is
    deliberately not stored -- nothing in the client reads it back, and the
    entry is a record of what the user assembled, not a transcript of a single
    send.

    ``request_auth`` holds the request-level ``ApiAuth`` as composed, because
    ``request_headers`` alone cannot reconstruct it: the editor stores auth flat
    (``type`` plus every field for every scheme) so that switching scheme does
    not discard what was typed under another one, and a resolved header list has
    already lost that.

    A history entry can hold real credentials -- in ``request_auth``,
    ``request_headers`` and ``request_body``.  Masking or encrypting them before
    insert is the application's responsibility and this model does none of it.
    """

    __tablename__ = "api_request_history"
    __table_args__ = (Index("ix_api_request_history_created_at", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saved_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    request_params: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    request_headers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    request_auth: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(
        "Project", back_populates="api_request_history", lazy="raise"
    )
    saved_request: Mapped[SavedRequest | None] = relationship(
        "SavedRequest", back_populates="history_entries", lazy="joined"
    )
    environment: Mapped[Environment | None] = relationship(
        "Environment", back_populates="api_request_history", lazy="joined"
    )


class TestRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One execution of a plan.

    The plan says how to test; this row says what this execution actually did.
    It is a historical record, so everything a reader needs later is frozen
    onto it rather than reached through a join that a later edit could change:

    * ``plan_name`` -- a renamed or regenerated plan must not rewrite the name
      on runs that already happened.
    * ``base_url`` -- recorded, not derived.  Reading it back from whichever
      environment is selected now would relabel a staging run as production the
      moment the user switches, with nothing on screen to say it changed.
    * ``variable_keys`` -- names only, never values.  An environment can carry
      secrets and run history is not the place to accumulate copies of them.

    ``plan_id`` is ``NO ACTION``, paired with the soft delete on ``test_plans``:
    a plan can be retired without taking its run history with it, and a run
    cannot be orphaned by a hard delete.  ``environment_id`` is nullable and
    ``SET NULL`` for the same reason -- deleting an environment must not delete
    the runs that were made against it, and ``base_url`` still explains them.

    ``started_at`` / ``finished_at`` cover the lifecycle, so there is no
    ``updated_at`` here.
    """

    __tablename__ = "test_runs"
    __table_args__ = (Index("ix_test_runs_created_at", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_plans.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_specs.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_name: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default=text("'queued'")
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    variable_keys: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="test_runs", lazy="raise")
    plan: Mapped[TestPlan] = relationship("TestPlan", back_populates="test_runs", lazy="joined")
    spec: Mapped[ApiSpec] = relationship("ApiSpec", back_populates="test_runs", lazy="raise")
    environment: Mapped[Environment | None] = relationship(
        "Environment", back_populates="test_runs", lazy="joined"
    )
    run_scenarios: Mapped[list[RunScenario]] = relationship(
        "RunScenario", back_populates="run", lazy="raise", passive_deletes=True
    )
    run_evidence: Mapped[list[RunEvidence]] = relationship(
        "RunEvidence", back_populates="run", lazy="raise", passive_deletes=True
    )
    run_events: Mapped[list[RunEvent]] = relationship(
        "RunEvent", back_populates="run", lazy="raise", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<TestRun id={self.id!r} status={self.status!r}>"


class RunReport(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable PDF report generated from one finished run.

    The bytes live in the row rather than on a filesystem path.  That makes the
    metadata and the file one atomic database write: a successful row cannot
    name a missing file, and a failed insert cannot leave an orphan PDF.  It
    also removes path traversal from the download route entirely -- the only
    addressable value is the report UUID.
    """

    __tablename__ = "run_reports"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_run_reports_byte_size_positive"),
        Index("ix_run_reports_project_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/pdf", server_default="application/pdf"
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    def __repr__(self) -> str:
        return f"<RunReport id={self.id!r} run_id={self.run_id!r} bytes={self.byte_size!r}>"


class RunScenario(UUIDPrimaryKeyMixin, Base):
    """One scenario as it came out in one run.

    ``UNIQUE(run_id, scenario_key)`` rather than a bare index on ``run_id``.
    The two do the same amount of work -- the constraint's prefix covers the
    foreign key -- but the constraint also states the invariant the frontend
    depends on: the reducer finds a scenario by key within its run
    (``scenario.id === scenarioId``), so two rows sharing a key would both be
    updated by one event and the page would disagree with the database.

    ``test_scenarios`` already enforces ``UNIQUE(plan_id, scenario_key)``, so a
    faithful snapshot cannot collide here; the constraint catches an engine
    that emits duplicates, not a plan that contains them.  A run that executes
    the same scenario twice is not something the frontend model can express.

    No ``created_at``.  ``started_at`` / ``finished_at`` cover the lifecycle as
    they do on ``test_runs``; this row is created as part of creating the run,
    so ``test_runs.created_at`` is the timestamp it would have carried.

    ``name`` / ``risk_level`` / ``sort_order`` are snapshots, not lookups.
    ``sort_order`` is not decoration: the frontend's ``RunScenario.index`` is
    required and means "in run order", which ``started_at`` cannot supply --
    it is nullable and ties within a run.
    """

    __tablename__ = "run_scenarios"
    __table_args__ = (
        UniqueConstraint("run_id", "scenario_key", name="uq_run_scenarios_run_scenario_key"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL, not CASCADE: the run is evidence and outlives the plan it
        # came from.  scenario_key and name are enough to read this row alone.
        ForeignKey("test_scenarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default=text("'pending'")
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    run: Mapped[TestRun] = relationship(
        "TestRun", back_populates="run_scenarios", lazy="raise"
    )
    source_scenario: Mapped[TestScenario | None] = relationship(
        "TestScenario", back_populates="run_scenarios", lazy="raise"
    )
    steps: Mapped[list[RunStep]] = relationship(
        "RunStep", back_populates="run_scenario", lazy="raise", passive_deletes=True
    )
    assertions: Mapped[list[RunAssertion]] = relationship(
        "RunAssertion", back_populates="run_scenario", lazy="raise", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<RunScenario key={self.scenario_key!r} status={self.status!r}>"


class RunStep(UUIDPrimaryKeyMixin, Base):
    """One step as it came out in one run.

    ``method`` / ``path`` are snapshots rather than a lookup through
    ``source_step_id``.  Reading them back from the plan would break the
    promise the whole run tree exists to keep: editing a step would rewrite
    what an earlier run reported.  ``description`` and ``step_type`` are
    copies for the same reason.

    ``endpoint_id`` is the one link kept as a reference instead of a copy --
    and it is the one the frontend barely uses.  ``RunStep.endpointId`` wants
    the endpoint's *public* id (``ep_post_api_orders``), which this column
    cannot supply once re-analysing a document has replaced the endpoint row.
    Nothing in the client reads it today, so it stays a plain ``SET NULL``
    reference; add a ``public_id`` snapshot column if that changes.

    ``error_code`` / ``error_message`` follow ``test_runs``: a machine code and
    a plain-text message.  The frontend's ``RunFailure.message`` is a
    ``LocalizedText`` and so does not fit either column -- that whole family is
    settled once, in the REST error contract, rather than twice with two
    representations here.
    """

    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_scenario_id", "step_key", name="uq_run_steps_run_scenario_step_key"
        ),
    )

    run_scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL: see RunScenario.source_scenario_id.
        ForeignKey("test_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL: re-analysing a document replaces its endpoints, and losing
        # an endpoint must not delete the record of steps that ran against it.
        ForeignKey("api_endpoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default=text("'pending'")
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run_scenario: Mapped[RunScenario] = relationship(
        "RunScenario", back_populates="steps", lazy="raise"
    )
    source_step: Mapped[TestStep | None] = relationship(
        "TestStep", back_populates="run_steps", lazy="raise"
    )
    endpoint: Mapped[ApiEndpoint | None] = relationship(
        "ApiEndpoint", back_populates="run_steps", lazy="raise"
    )
    assertions: Mapped[list[RunAssertion]] = relationship(
        "RunAssertion", back_populates="run_step", lazy="raise", passive_deletes=True
    )
    evidence: Mapped[list[RunEvidence]] = relationship(
        "RunEvidence", back_populates="run_step", lazy="raise", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<RunStep key={self.step_key!r} status={self.status!r}>"


class RunAssertion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One assertion as it came out in one run.

    ``run_scenario_id`` is ``NOT NULL`` and ``run_step_id`` is nullable: a
    scenario-level assertion has no step to hang off, and the frontend models
    exactly that (``RunAssertion.stepId: string | null``, and
    ``assertionStepId`` on the event, "set when the assertion belongs to no
    particular step").  Holding the step column NOT NULL would make those rows
    impossible to insert.  The shape mirrors ``test_assertions``.

    ``run_step_id`` is ``SET NULL`` rather than ``CASCADE``, which is the
    opposite of the call made for ``test_assertions.step_id``.  The reasoning
    does not carry over: there, nulling the column silently demotes a step
    assertion into a scenario one and changes what the *plan* means.  Here the
    row is a historical record, ``run_scenario_id`` keeps it anchored and
    readable, and the reducer still finds it by assertion key -- losing the
    result outright would be the worse outcome.  In practice the null is
    unreachable: a run step is only ever deleted by deleting its run, which
    takes the assertions with it.

    ``UNIQUE(run_scenario_id, assertion_key)`` matches test_assertions and, as
    there, is scoped to the whole scenario rather than the step: a generator
    must namespace its keys (``{step_key}.{name}``) or the second ``status_200``
    in a scenario collides.  Scoping it to ``run_step_id`` instead would
    enforce nothing for scenario-level assertions, since PostgreSQL treats
    NULLs as distinct.

    No ``sort_order``.  The frontend renders ``assertions`` in array order and
    has never needed an explicit one; a stable ``(created_at, id)`` ordering is
    enough if that becomes load-bearing.
    """

    __tablename__ = "run_assertions"
    __table_args__ = (
        UniqueConstraint(
            "run_scenario_id",
            "assertion_key",
            name="uq_run_assertions_run_scenario_assertion_key",
        ),
    )

    run_scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_assertion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_assertions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assertion_key: Mapped[str] = mapped_column(String(100), nullable=False)
    assertion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    actual_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run_scenario: Mapped[RunScenario] = relationship(
        "RunScenario", back_populates="assertions", lazy="raise"
    )
    run_step: Mapped[RunStep | None] = relationship(
        "RunStep", back_populates="assertions", lazy="raise"
    )
    source_assertion: Mapped[TestAssertion | None] = relationship(
        "TestAssertion", back_populates="run_assertions", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<RunAssertion key={self.assertion_key!r} status={self.status!r}>"


class RunEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Why a step passed, or why it failed -- the artifact that shows it.

    ``label`` is JSONB and not ``VARCHAR`` for a reason that has nothing to do
    with taste: what the client sends is an i18n key
    (``console.runs.evidence.endpoint`` / ``.extracted`` / ``.checked``) and
    the server cannot resolve it to text in either locale.  Storing a string
    would mean inventing the English sentence here.

    ``value`` is the displayable half -- a status code, a header, an extracted
    field name -- and is shown verbatim in a monospace cell.

    ``content`` is an extension point for the structured payload (a whole
    request / response transcript).  Nothing reads it yet; it is here so
    adding it later is not a migration.

    ``run_step_id`` is nullable so evidence can outlive the step it describes,
    but note that the frontend only ever reads evidence from ``RunStep`` --
    so a row whose step link has been nulled is not reachable over the API.
    As with ``run_assertions``, that only happens if a run step is deleted on
    its own, which nothing does.
    """

    __tablename__ = "run_evidence"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    run: Mapped[TestRun] = relationship(
        "TestRun", back_populates="run_evidence", lazy="raise"
    )
    run_step: Mapped[RunStep | None] = relationship(
        "RunStep", back_populates="evidence", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<RunEvidence type={self.evidence_type!r}>"


class RunEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One entry in a run's event stream, persisted.

    The stream is what a live view subscribes to; this table is what makes a
    reconnect work.  ``RunDetail.lastSeq`` is ``MAX(seq)`` for the run, the
    client sets its high-water mark from it and asks for everything after, so
    the events it already applied are not replayed and the ones it missed are
    not skipped.

    ``UNIQUE(run_id, seq)`` is therefore not just hygiene -- it is the replay
    key, and it doubles as the index the ``fromSeq`` read needs.  Named by hand
    because the naming convention would call it ``uq_run_events_run_id``, which
    reads as "run_id is unique" and is the opposite of the truth.

    ``seq`` is BIGINT and is written as ``BigInteger`` explicitly: the type
    annotation map resolves a bare ``int`` to ``INTEGER``, and a column the
    whole reconnect protocol orders on should not be the narrow type by
    accident.

    ``created_at`` is when the *server* observed the event, not when a browser
    received it -- a run that took four seconds is not a run that took four
    seconds plus a reconnect.

    ``event_type`` holds exactly the eight names the frontend declares in
    ``RUN_EVENT_NAMES``, which its own comment marks as closed:

        run.started      step.started     step.completed
        assertion.completed               step.failed
        run.completed    run.failed       run.cancelled

    No ``run.created`` -- creation is a plain REST call and emits nothing -- and
    no ``run.finished``, which is ``run.completed``.  There is no CHECK on the
    column, per the project-wide rule that these value sets live in the
    application layer and change without a migration.

    ``payload`` carries the event's own fields, and its ``scenarioId`` /
    ``stepId`` / ``assertionId`` must be the *plan-side* stable keys, never the
    UUIDs of the rows above.  Nothing in the schema can enforce that, and the
    failure mode is silent -- the frontend matches by id equality with no
    positional fallback, so a UUID there leaves the detail page frozen with no
    error raised.

    ``seq`` starts at 1 and is dense within a run; uniqueness is enforced here,
    density is the writer's job.
    """

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    run: Mapped[TestRun] = relationship(
        "TestRun", back_populates="run_events", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<RunEvent seq={self.seq!r} type={self.event_type!r}>"
