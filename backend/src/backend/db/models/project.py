"""Project system: the eight tables hanging off ``projects``.

Two conventions hold across this file:

``LocalizedText`` columns are JSONB.
    Several of these columns mirror a frontend field typed
    ``{ key: string, params? } | { text: string }`` -- authored copy is an i18n
    key, generated copy is a literal.  A ``VARCHAR`` cannot hold that union, so
    the columns that carry one are JSONB and the ones that carry an ordinary
    string stay ``String(n)``.

``ApiSpec`` is never eagerly joined.
    It owns the document ``content``; auto-joining it onto an endpoint or a
    task would drag the whole OpenAPI file into unrelated queries.

Deletion is the database's job.
    Every foreign key here carries an explicit ``ondelete`` and the matching
    relationship carries ``passive_deletes=True``, so SQLAlchemy emits one
    ``DELETE`` for the row asked about and lets PostgreSQL cascade.  No ORM-level
    ``cascade=`` is configured -- ``cascade="all"`` would smuggle in
    ``delete-orphan``, which cannot be declared on both parents of a child that
    has two of them (``test_assertions`` under a scenario *and* a step).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.db.models.agent import AgentTask, TestPlan, TestStep
    from backend.db.models.result import ApiRequestHistory, RunStep, TestRun
    from backend.db.models.user import GuestSession, User

__all__ = [
    "ApiEndpoint",
    "ApiSpec",
    "Environment",
    "EnvironmentAuth",
    "EnvironmentVariable",
    "Project",
    "RequestCollection",
    "SavedRequest",
]


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The container everything else in this schema hangs off.

    Ownership is exclusive: a project belongs to a registered user *or* to a
    guest session, never both and never neither.  ``owner_xor`` is a database
    constraint rather than a service-layer rule, so a bug in one call site
    cannot produce an unowned project.

    The guest-to-user handover stays a single ``UPDATE`` that sets both columns
    together -- PostgreSQL evaluates a CHECK against the row as it will be after
    the statement, so no intermediate ``(NULL, NULL)`` state is ever observed.
    Splitting it across two statements (or two flushes) would violate the
    constraint, which is why the constraint is not deferrable: PostgreSQL
    only allows ``DEFERRABLE`` on foreign keys, unique and exclusion
    constraints.

    ``public_id`` is the project's external identity (``prj_orders``) and is
    globally unique -- a project has no parent to scope it to, so it is the one
    ``public_id`` in this schema that is not project-scoped.
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND guest_session_id IS NULL) "
            "OR (user_id IS NULL AND guest_session_id IS NOT NULL)",
            name="owner_xor",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # NO ACTION rather than CASCADE: letting a guest session expire must
        # not silently destroy the projects under it.
        ForeignKey("guest_sessions.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    public_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_user: Mapped[User | None] = relationship(
        "User", back_populates="projects", lazy="joined"
    )
    guest_session: Mapped[GuestSession | None] = relationship(
        "GuestSession", back_populates="projects", lazy="joined"
    )

    api_specs: Mapped[list[ApiSpec]] = relationship(
        "ApiSpec",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    environments: Mapped[list[Environment]] = relationship(
        "Environment",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    request_collections: Mapped[list[RequestCollection]] = relationship(
        "RequestCollection",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    saved_requests: Mapped[list[SavedRequest]] = relationship(
        "SavedRequest",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    agent_tasks: Mapped[list[AgentTask]] = relationship(
        "AgentTask",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    test_plans: Mapped[list[TestPlan]] = relationship(
        "TestPlan",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    test_runs: Mapped[list[TestRun]] = relationship(
        "TestRun",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )
    api_request_history: Mapped[list[ApiRequestHistory]] = relationship(
        "ApiRequestHistory",
        back_populates="project",
        lazy="raise",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id!r} name={self.name!r}>"


class ApiSpec(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An uploaded OpenAPI / Swagger document.

    ``spec_type`` and ``content_format`` are two orthogonal facts and are kept
    in two columns: the dialect (``openapi-3`` / ``swagger-2``) and the
    serialization (``json`` / ``yaml``).  Folding them into one field makes
    ``openapi-3 + yaml`` unrepresentable.

    ``slug`` is the content-derived identity -- ``<title or filename>_<hash>``
    -- so the same document re-uploaded to the same project keeps the same
    identity.  It is scoped ``UNIQUE(project_id, slug)`` rather than globally:
    two projects uploading the same file are two specs, and nothing about the
    slug's derivation is project-aware.

    There is deliberately **no** ``public_id`` here.  The external id is
    ``spec_`` + ``slug``, so storing both would put two columns behind one
    external identifier.  The API composes it on the way out instead.

    The unique constraint is named explicitly.  The metadata naming convention
    builds a unique constraint name from ``%(table_name)s`` and the *first*
    column only, which would give the misleading ``uq_api_specs_project_id``.
    """

    __tablename__ = "api_specs"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_api_specs_project_slug"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    spec_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content_format: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="upload", server_default=text("'upload'")
    )
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    server_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[Project] = relationship("Project", back_populates="api_specs", lazy="raise")
    endpoints: Mapped[list[ApiEndpoint]] = relationship(
        "ApiEndpoint",
        back_populates="spec",
        lazy="raise",
        passive_deletes=True,
    )
    agent_tasks: Mapped[list[AgentTask]] = relationship(
        "AgentTask", back_populates="spec", lazy="raise", passive_deletes=True
    )
    test_plans: Mapped[list[TestPlan]] = relationship(
        "TestPlan", back_populates="spec", lazy="raise", passive_deletes=True
    )
    test_runs: Mapped[list[TestRun]] = relationship(
        "TestRun", back_populates="spec", lazy="raise", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<ApiSpec id={self.id!r} slug={self.slug!r}>"


class ApiEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One operation parsed out of a spec.

    ``updated_at`` is present because the parsed shape is regenerated whenever
    the document is re-analysed.

    ``public_id`` is the frontend's ``ApiEndpoint.id`` -- ``ep_`` plus the
    method and a slug of the path -- and is scoped ``UNIQUE(spec_id,
    public_id)`` rather than to the project: an endpoint has no ``project_id``
    of its own, and the rule it encodes ("one operation per method + path") is
    an OpenAPI invariant of the document, not of the project.
    """

    __tablename__ = "api_endpoints"
    __table_args__ = (
        UniqueConstraint("spec_id", "public_id", name="uq_api_endpoints_spec_public_id"),
    )

    spec_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_specs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_id: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    request_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    spec: Mapped[ApiSpec] = relationship("ApiSpec", back_populates="endpoints", lazy="raise")
    test_steps: Mapped[list[TestStep]] = relationship(
        "TestStep", back_populates="endpoint", lazy="raise", passive_deletes=True
    )
    run_steps: Mapped[list[RunStep]] = relationship(
        "RunStep", back_populates="endpoint", lazy="raise", passive_deletes=True
    )


class Environment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named target (development / staging / production) with a base URL.

    ``public_id`` (``env_orders_staging``) is scoped to the project: the
    frontend's id happens to embed the project name, but nothing guarantees it,
    and two projects naming an environment ``staging`` is the normal case.

    ``uq_environments_one_default`` is a partial unique index, not a plain one:
    it constrains only the rows where ``is_default`` is true, so a project may
    have any number of environments while still having at most one default.
    """

    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_environments_project_name"),
        UniqueConstraint("project_id", "public_id", name="uq_environments_project_public_id"),
        Index(
            "uq_environments_one_default",
            "project_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    public_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="development", server_default=text("'development'")
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    project: Mapped[Project] = relationship("Project", back_populates="environments", lazy="raise")
    variables: Mapped[list[EnvironmentVariable]] = relationship(
        "EnvironmentVariable",
        back_populates="environment",
        lazy="raise",
        passive_deletes=True,
    )
    auths: Mapped[list[EnvironmentAuth]] = relationship(
        "EnvironmentAuth",
        back_populates="environment",
        lazy="raise",
        passive_deletes=True,
    )
    saved_requests: Mapped[list[SavedRequest]] = relationship(
        "SavedRequest", back_populates="environment", lazy="raise", passive_deletes=True
    )
    agent_tasks: Mapped[list[AgentTask]] = relationship(
        "AgentTask", back_populates="environment", lazy="raise", passive_deletes=True
    )
    test_runs: Mapped[list[TestRun]] = relationship(
        "TestRun", back_populates="environment", lazy="raise", passive_deletes=True
    )
    api_request_history: Mapped[list[ApiRequestHistory]] = relationship(
        "ApiRequestHistory",
        back_populates="environment",
        lazy="raise",
        passive_deletes=True,
    )


class EnvironmentVariable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A ``{{name}}`` substitution the user configured for an environment.

    ``value_encrypted`` is a ``TEXT`` column and nothing more: encryption is the
    application layer's job.  There is deliberately no ``TypeDecorator``, no
    ``@validates`` hook and no hybrid property here -- a model that transparently
    decrypts couples key management into the ORM and hides, from the caller,
    which of the two things it is holding.

    Variables extracted during a run are not written back here; they belong to
    the run's own context.
    """

    __tablename__ = "environment_variables"
    __table_args__ = (UniqueConstraint("environment_id", "key"),)

    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    environment: Mapped[Environment] = relationship(
        "Environment", back_populates="variables", lazy="joined"
    )


class EnvironmentAuth(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An API authentication rule for an environment -- not a runtime token.

    ``config`` holds the shape for the chosen ``auth_type``
    (``bearer`` / ``api_key`` / ``cookie`` / ``basic``); its inner values may
    reference ``{{variables}}`` and must be encrypted by the application before
    they are persisted.

    This is a *rule*, distinct from a value produced while testing: an
    ``access_token`` returned by ``POST /login`` is a runtime variable, not an
    auth rule, and does not belong in this row.
    """

    __tablename__ = "environment_auths"
    __table_args__ = (
        Index(
            "uq_environment_auths_one_default",
            "environment_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    environment: Mapped[Environment] = relationship(
        "Environment", back_populates="auths", lazy="joined"
    )


class RequestCollection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A folder in the API client's request tree.

    ``parent_id`` is nullable and self-referential.  The frontend only supports
    two levels (collection, folder) and rejects an unbounded tree, so this
    recursive shape is a superset: the service layer owns the "same project,
    at most two levels deep, no cycles" invariants.  PostgreSQL cannot express
    acyclicity in a CHECK constraint, and the foreign key cannot stop a
    ``parent_id`` from pointing into a different project.

    Both sides of the self-reference use ``lazy="raise"``: a joined load here
    would recurse along the ancestor chain.
    """

    __tablename__ = "request_collections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("request_collections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    project: Mapped[Project] = relationship(
        "Project", back_populates="request_collections", lazy="raise"
    )
    parent: Mapped[RequestCollection | None] = relationship(
        "RequestCollection",
        back_populates="children",
        remote_side="RequestCollection.id",
        lazy="raise",
    )
    children: Mapped[list[RequestCollection]] = relationship(
        "RequestCollection",
        back_populates="parent",
        lazy="raise",
        passive_deletes=True,
    )
    saved_requests: Mapped[list[SavedRequest]] = relationship(
        "SavedRequest", back_populates="collection", lazy="raise", passive_deletes=True
    )


class SavedRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A request the user configured by hand and kept.

    ``params`` / ``headers`` / ``auth`` / ``body`` stay JSONB because they mirror
    the editor's own shapes, which are not fixed: header rows carry their own
    id and an enabled flag, and the auth object is stored flat so switching
    type does not discard what was typed under another one.
    """

    __tablename__ = "saved_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # SET NULL: deleting a folder must not silently destroy saved requests,
        # they are promoted to the project root instead.
        ForeignKey("request_collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    headers: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    auth: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="saved_requests", lazy="raise")
    collection: Mapped[RequestCollection | None] = relationship(
        "RequestCollection", back_populates="saved_requests", lazy="joined"
    )
    environment: Mapped[Environment | None] = relationship(
        "Environment", back_populates="saved_requests", lazy="joined"
    )
    history_entries: Mapped[list[ApiRequestHistory]] = relationship(
        "ApiRequestHistory",
        back_populates="saved_request",
        lazy="raise",
        passive_deletes=True,
    )
