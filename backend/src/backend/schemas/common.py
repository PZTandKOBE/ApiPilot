"""The ``LocalizedText`` union and the error envelope.

``LocalizedText`` mirrors ``frontend/src/types/agent.ts``:

    type LocalizedText = LocalizedMessage | LiteralMessage

The point of the union is a distinction the app cares about: strings the app
*authors* are i18n keys resolved from the dictionary at render time, and strings
that come *out of a document or a model* are literals shown exactly as received.
The frontend tells them apart with ``'key' in value``, so the two shapes have to
stay mutually exclusive on the wire --- hence ``extra="forbid"`` on both halves,
which is what makes ``{"key": ..., "text": ...}`` a validation error rather than
an ambiguous object that Python and TypeScript read differently.
"""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

from backend.schemas.base import Schema

__all__ = [
    "ErrorResponse",
    "LiteralMessage",
    "LocalizedMessage",
    "LocalizedText",
]


class LocalizedMessage(Schema):
    """A string the app authored; resolved from the dictionary at render time.

    ``params`` is a ``dict`` with a ``default_factory`` rather than ``None``.
    That is a type-system guarantee, not a style choice: the frontend's
    ``interpolate()`` calls ``Object.prototype.hasOwnProperty.call(params, ...)``,
    which throws ``TypeError`` on ``null`` whenever the dictionary string
    contains a ``{placeholder}``.  With ``default_factory=dict`` an empty
    ``params`` is ``{}``, which is safe, and ``null`` is unrepresentable --- so
    no future caller can reintroduce that crash by forgetting a serialiser flag.
    """

    key: str
    params: dict[str, str | int] = Field(default_factory=dict)


class LiteralMessage(Schema):
    """A string that came from a document or a model; shown exactly as received."""

    text: str


LocalizedText = Annotated[
    Union[LocalizedMessage, LiteralMessage],
    Field(union_mode="left_to_right"),
]
"""Authored-or-literal text.

``left_to_right`` rather than Pydantic's default smart union, so the resolution
order is a property of this declaration and not of a scoring heuristic that
could change under a library upgrade.  With both halves blocking extras the two
are disjoint, so the order is also unambiguous.
"""


class ErrorResponse(Schema):
    """The envelope every non-2xx response carries.

    **Documentation only.**  Handlers in ``backend.api.errors`` build this shape
    as a plain ``dict`` so that ``params`` can be *omitted* when it is empty
    rather than serialised as ``{}``.  Do not route real responses through
    ``model_dump()``: the frontend's ``RunError`` type expects the key to be
    absent, and an empty object would still be a value.
    """

    code: str
    message_key: str
    params: dict[str, str | int] = Field(
        default_factory=dict,
        description="Interpolation values for `messageKey`. Omitted entirely when empty.",
    )
    details: object | None = Field(
        default=None,
        description="Diagnostic payload for logs and bug reports. Never rendered.",
    )
