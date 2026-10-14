"""Shared configuration for every schema in this package.

The wire format is camelCase --- that is what the frontend reads and writes, and
``frontend/src/types/*.ts`` is the authority on the names.  Python side stays
snake_case, so the boundary lives here rather than in ninety hand-written
aliases.

``populate_by_name=True`` matters as much as the generator: it lets internal
code build a model with ``RunResponse(plan_name=...)`` while the JSON still
carries ``planName``.  Without it, every construction site would have to spell
out the alias, and one typo would surface as a validation error at runtime
instead of a ``TypeError`` at import.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

__all__ = ["Schema"]


class Schema(BaseModel):
    """Base for every request and response model.

    ``extra="forbid"`` is deliberate on requests: if the frontend grows a field
    this service has not implemented yet, the request fails loudly instead of
    being silently dropped.  A payload that validates but means something
    slightly different is the expensive failure.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )
