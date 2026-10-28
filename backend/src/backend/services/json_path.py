"""Resolve the limited JSONPath subset ApiPilot writes for Extract sources.

The contract deliberately accepts only deterministic, bounded paths:

    $                     the whole response body
    $.id                  an object property
    $[0].id               the first item's property
    $.data.id             a nested object property
    $.data[0].id          an object property containing an array

There is no wildcard, filter, recursive descent, script expression or eval.
The implementation is small on purpose: a plan source path must be auditable
and must fail closed when it cannot be resolved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "PathResolution",
    "PathSyntaxError",
    "parse_path",
    "resolve_path",
]


class PathSyntaxError(ValueError):
    """The configured source path is not in the supported grammar."""


@dataclass(frozen=True)
class PathResolution:
    """One resolution attempt, keeping absence distinct from a JSON null."""

    found: bool
    value: Any = None
    reason: str = ""


_KEY = "key"
_INDEX = "index"
_MAX_PATH_LENGTH = 512
_MAX_SEGMENTS = 64


def parse_path(path: str) -> tuple[tuple[str, str | int], ...]:
    """Parse the supported subset into (kind, value) segments.

    The syntax is validated without touching a response.  A malformed path is a
    plan/configuration error, not a missing-response field.
    """
    if not isinstance(path, str):
        raise PathSyntaxError("source path must be a string")

    raw = path.strip()
    if raw == "":
        raise PathSyntaxError("source path is empty")
    if len(raw) > _MAX_PATH_LENGTH:
        raise PathSyntaxError("source path is too long")
    if not raw.startswith("$"):
        raise PathSyntaxError("source path must start with '$'")

    segments: list[tuple[str, str | int]] = []
    index = 1

    while index < len(raw):
        char = raw[index]

        if char == ".":
            index += 1
            start = index
            while index < len(raw) and raw[index] not in ".[]":
                index += 1
            name = raw[start:index]
            if name == "":
                raise PathSyntaxError("source path has an empty property name")
            if any(part.isspace() for part in name):
                raise PathSyntaxError("source path property names cannot contain whitespace")
            segments.append((_KEY, name))
        elif char == "[":
            close = raw.find("]", index + 1)
            if close < 0:
                raise PathSyntaxError("source path has an unterminated array index")
            number = raw[index + 1 : close]
            if number == "" or not number.isdigit():
                raise PathSyntaxError("source path array index must be a non-negative integer")
            segments.append((_INDEX, int(number)))
            index = close + 1
        else:
            raise PathSyntaxError("source path has an unexpected character")

        if len(segments) > _MAX_SEGMENTS:
            raise PathSyntaxError("source path has too many segments")

    return tuple(segments)


def resolve_path(document: Any, path: str) -> PathResolution:
    """Resolve path against a parsed JSON document.

    A missing property, a non-container in the walk and an out-of-range index
    all return found=False with a human-readable reason.  A property whose value
    is JSON null is found and returns value=None.
    """
    try:
        segments = parse_path(path)
    except PathSyntaxError as exc:
        return PathResolution(found=False, reason=str(exc))

    current: Any = document

    for kind, value in segments:
        if kind == _KEY:
            if not isinstance(current, Mapping):
                return PathResolution(
                    found=False,
                    reason="expected an object at the property " + repr(value),
                )
            if value not in current:
                return PathResolution(
                    found=False,
                    reason="property " + repr(value) + " is missing",
                )
            current = current[value]
            continue

        if isinstance(current, (str, bytes)) or not isinstance(current, Sequence):
            return PathResolution(
                found=False,
                reason="expected an array at index " + str(value),
            )
        if value >= len(current) or value < 0:
            return PathResolution(
                found=False,
                reason="array index " + str(value) + " is out of range",
            )
        current = current[value]

    return PathResolution(found=True, value=current)
