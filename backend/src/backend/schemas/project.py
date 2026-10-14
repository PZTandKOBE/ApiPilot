"""Project wire schemas.

Phase 8.5 Step 3.  The console's `Project` type, for the two endpoints that
now serve it for real: list and create.

**Ownership has no field here.**  `ProjectCreateRequest` accepts a name and an
optional base URL, and its model config forbids unknown fields -- so a body that
tries to declare `guestSessionId` or `userId` is a validation error rather
than a request whose owner fields are quietly ignored.  The owner is the identity
the server verified (identity contract, sections 6.3 and 12).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.schemas.base import Schema

__all__ = [
    "EnvironmentVariableResponse",
    "ProjectCreateRequest",
    "ProjectEnvironmentResponse",
    "ProjectResponse",
]


class EnvironmentVariableResponse(Schema):
    """A variable's name and whether it is secret.  Never a secret's value."""

    key: str
    value: str
    secret: bool


class ProjectEnvironmentResponse(Schema):
    id: str
    name: str
    kind: str
    base_url: str
    variables: list[EnvironmentVariableResponse] = Field(default_factory=list)


class ProjectResponse(Schema):
    """One project, as the console reads it."""

    id: str = Field(description="The project's public id, e.g. prj_orders_1a2b3c4d.")
    name: str
    description: str
    spec_name: str | None = Field(
        default=None, description="The document last parsed for this project, if any."
    )
    environments: list[ProjectEnvironmentResponse] = Field(default_factory=list)
    updated_at: datetime


class ProjectCreateRequest(Schema):
    """What a caller may say about a project it is creating.

    Only a name, and optionally where the project's API lives.  A body carrying
    any other field -- an owner, an id, a timestamp -- fails validation, because
    those are the server's to decide.
    """

    name: str = Field(min_length=1, max_length=200, description="A display name.")
    base_url: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "Base URL for the project's default environment. Defaults to the "
            "local service, which is where development points anyway."
        ),
    )
