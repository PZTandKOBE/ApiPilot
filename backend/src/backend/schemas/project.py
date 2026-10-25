"""Project wire schemas.

The console's project model, served for real by the project routes.

**Ownership has no field here.**  Requests that write a project accept only the
fields the user owns -- the owner is the identity the server verified.  The
environment update is deliberately a partial contract over the environment's
editable fields, not a way to replace variables or authentication rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from backend.schemas.base import Schema

__all__ = [
    "EnvironmentCreateRequest",
    "EnvironmentUpdateRequest",
    "EnvironmentVariableResponse",
    "ProjectCreateRequest",
    "ProjectEnvironmentResponse",
    "ProjectResponse",
    "ProjectSpecResponse",
    "ProjectUpdateRequest",
]

EnvironmentKind = Literal["development", "testing", "staging", "production"]

_NAME_LIMIT = 200
_ENVIRONMENT_NAME_LIMIT = 100
_BASE_URL_LIMIT = 1000


def _stripped_non_empty(value: str, *, label: str) -> str:
    stripped = value.strip()
    if stripped == "":
        raise ValueError(f"{label} must not be blank")
    return stripped


def _http_url(value: str) -> str:
    """An absolute http(s) URL, with surrounding whitespace removed.

    This is the same rule the environment dialog uses: a scheme and a host are
    required, because a base URL with neither cannot be the origin of a request.
    """
    stripped = value.strip()
    parsed = urlsplit(stripped)

    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        raise ValueError("baseUrl must be an absolute http(s) URL")

    return stripped


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


class ProjectSpecResponse(Schema):
    """The project's most recently persisted API specification, without its content."""

    id: str = Field(description="The spec's external id, spec_<slug>.")
    name: str
    filename: str | None = None
    spec_type: str
    content_format: str
    version: str | None = None
    source: str
    endpoint_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class ProjectCreateRequest(Schema):
    """What a caller may say about a project it is creating.

    Only a name, and optionally where the project's API lives.  A body carrying
    any other field -- an owner, an id, a timestamp -- fails validation, because
    those are the server's to decide.
    """

    name: str = Field(min_length=1, max_length=_NAME_LIMIT, description="A display name.")
    base_url: str | None = Field(
        default=None,
        max_length=_BASE_URL_LIMIT,
        description=(
            "Base URL for the project's default environment. Defaults to the "
            "local service, which is where development points anyway."
        ),
    )


class ProjectUpdateRequest(Schema):
    """The one project field this version lets a user rename."""

    name: str = Field(min_length=1, max_length=_NAME_LIMIT)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _stripped_non_empty(value, label="name")


class EnvironmentUpdateRequest(Schema):
    """The editable fields of an existing environment.

    Variables, auth rules and the default flag are deliberately absent: this
    route updates the environment's identity, not its secrets or execution data.
    """

    name: str = Field(min_length=1, max_length=_ENVIRONMENT_NAME_LIMIT)
    kind: EnvironmentKind
    base_url: str = Field(min_length=1, max_length=_BASE_URL_LIMIT)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _stripped_non_empty(value, label="name")

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        return _http_url(value)


class EnvironmentCreateRequest(EnvironmentUpdateRequest):
    """A new environment's editable fields.

    Same fields and validation as an update, but a distinct name for the
    request contract: creating a row and editing one are different operations.
    Variables, auth rules and the default flag are not accepted here; a new
    environment starts with no variables and is never the default.
    """
