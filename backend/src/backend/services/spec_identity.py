"""Reproducing the frontend's spec identity, byte for byte.

``api_specs`` has no ``public_id`` column.  Its external identity is
``spec_`` + ``slug``, composed on the way out (``db/models/project.py``).  The
slug is content-derived::

    slug = f"{slugify(title or filename)}_{hashString(content)}"

from ``frontend/src/services/mock/agent/parse.ts``.  So a ``specId`` that
arrives on a request cannot be looked up in any column -- it has to be
*recomputed* from the document the request also carries, and then checked
against the id the client sent.

That is only possible because ``hashString`` is fully specified rather than
implementation-defined.  It is a 32-bit rolling hash with an explicit overflow
coercion::

    hash = (hash * 31 + value.charCodeAt(index)) | 0

``| 0`` is ECMAScript ``ToInt32``, and ``charCodeAt`` reads **UTF-16 code
units**.  Python strings are sequences of code points, so the two agree on the
BMP and diverge on anything above it -- iterating ``str`` directly gets emoji
wrong.  :func:`hash_string` therefore encodes to UTF-16-LE and walks it two
bytes at a time, which is the whole of the compatibility work.

Nothing here parses YAML.  ``parse.ts`` reaches js-yaml only for documents that
are not JSON, and the title a slug is built from lives inside the parsed
document.  For a YAML document without a JSON-compatible head this module
cannot recover the title, and says so through ``SpecIdentity.verified`` rather
than guessing -- see :func:`derive_spec_identity`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

__all__ = [
    "DocumentFacts",
    "SpecIdentity",
    "derive_spec_identity",
    "hash_string",
    "probe_document",
    "slugify",
    "spec_id_for",
]

_SPEC_ID_PREFIX = "spec_"

_BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


# --------------------------------------------------------------------------- #
# The JS primitives
# --------------------------------------------------------------------------- #


def _to_int32(value: int) -> int:
    """ECMAScript ``ToInt32``: wrap to 32 bits, then reinterpret as signed."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _to_base36(value: int) -> str:
    """``Number.prototype.toString(36)`` for a non-negative integer."""
    if value == 0:
        return "0"
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits))


def hash_string(value: str) -> str:
    """Port of ``hashString`` from ``parse.ts``.

    ``surrogatepass`` is not decoration: ``charCodeAt`` happily returns a lone
    surrogate's code unit, and a document containing an unpaired one -- which
    JSON permits as ``\\udXXX`` -- would raise on a strict encode here while
    the browser hashed it without complaint.

    The `.lower()`-free part matters too: nothing in this function lowercases,
    so ``hash_string`` is byte-exact on the raw content.
    """
    raw = value.encode("utf-16-le", "surrogatepass")

    digest = 0
    for index in range(0, len(raw), 2):
        code_unit = raw[index] | (raw[index + 1] << 8)
        digest = _to_int32(digest * 31 + code_unit)

    return _to_base36(abs(digest))


def slugify(value: str) -> str:
    """Port of ``slugify`` from ``parse.ts``.

    ``str.lower()`` is not ``String.prototype.toLowerCase()`` for a handful of
    characters (Turkish dotted I, Cherokee), and those characters do not
    survive the ``[^a-z0-9]`` filter that follows anyway -- both produce a
    non-ASCII run and both replace it with ``_``.  The equivalence holds for
    the outputs, which is what the slug is.
    """
    collapsed = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return collapsed.strip("_")


def spec_id_for(slug: str) -> str:
    """The external id, composed exactly as ``db/models/project.py`` describes."""
    return f"{_SPEC_ID_PREFIX}{slug}"


def strip_spec_prefix(spec_id: str) -> str:
    """``spec_orders_api_pkqkbr`` -> ``orders_api_pkqkbr``.

    Used only on the fallback path, where the slug could not be recomputed and
    the client's id is the only statement of identity available.
    """
    if spec_id.startswith(_SPEC_ID_PREFIX):
        return spec_id[len(_SPEC_ID_PREFIX) :]
    return spec_id


# --------------------------------------------------------------------------- #
# Document facts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DocumentFacts:
    """What can be learned about a specification document without a parser.

    ``spec_type`` is ``'unknown'`` rather than ``None`` because the column is
    ``NOT NULL`` and a defensive value that reads as "we stored it, we could
    not classify it" is better than a wrong one.  ``title`` is ``''`` when the
    document has none -- the same sentinel ``parse.ts`` uses, so the slug
    derivation downstream can branch on it identically.

    ``info.version`` is deliberately **not** carried here, and ``api_specs.version``
    is left ``NULL``: the decision for this phase is that the three optional
    metadata columns stay empty, and a value that is present for a JSON
    document and absent for a YAML one is a column with two meanings.  It is
    recoverable from the same parse whenever it is wanted.
    """

    content_format: str
    spec_type: str
    title: str


# A best-effort textual probe for YAML documents, **not** a parser.  It matches
# the two keys `detectFormat` keys off, at the start of a line, and only when
# the value begins with the right major version.  A YAML document that quotes
# its version differently, or that spells `openapi` inside a nested mapping,
# falls through to 'unknown' -- which is the honest answer for a module that
# has not actually parsed anything.
_YAML_OPENAPI = re.compile(r"^openapi:\s*[\"']?(3\.)", re.MULTILINE)
_YAML_SWAGGER = re.compile(r"^swagger:\s*[\"']?(2\.)", re.MULTILINE)


def _detect_spec_type(document: dict[str, object]) -> str:
    """Port of ``detectFormat`` from ``parse.ts``.

    ``asString`` there returns ``null`` for anything that is not a string, so
    a numeric ``openapi: 3`` is *not* a match and must not become one here.
    """
    openapi = document.get("openapi")
    if isinstance(openapi, str) and openapi.startswith("3."):
        return "openapi-3"

    swagger = document.get("swagger")
    if isinstance(swagger, str) and swagger.startswith("2."):
        return "swagger-2"

    return "unknown"


def _text_field(mapping: object, key: str) -> str:
    """``asString(...)?.trim() ?? ''`` -- empty for a non-string or a blank."""
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()


def probe_document(content: str) -> DocumentFacts:
    """Classify a document, JSON first and a textual probe second.

    The order mirrors ``decodeDocument``: a JSON document is valid YAML, so
    trying JSON first is unambiguous.  What differs is the fallback -- there is
    no YAML parser here, so a non-JSON document is *labelled* ``yaml`` and
    only the two format keys are sniffed.
    """
    try:
        parsed = json.loads(content)
    except (ValueError, RecursionError):
        parsed = None

    if isinstance(parsed, dict):
        return DocumentFacts(
            content_format="json",
            spec_type=_detect_spec_type(parsed),
            title=_text_field(parsed.get("info"), "title"),
        )

    if _YAML_OPENAPI.search(content):
        spec_type = "openapi-3"
    elif _YAML_SWAGGER.search(content):
        spec_type = "swagger-2"
    else:
        spec_type = "unknown"

    # No title: recovering one would mean parsing YAML, which this module
    # deliberately does not do.  `derive_spec_identity` handles the empty case.
    return DocumentFacts(content_format="yaml", spec_type=spec_type, title="")


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SpecIdentity:
    """The slug to store, and whether it was derived or merely accepted.

    ``verified`` is ``True`` only when the slug was recomputed from the
    document, which is the only case in which the caller can check the client's
    ``specId`` against it.  When it is ``False`` the slug was taken from the
    client's own id and there is nothing to compare -- the caller must not
    treat that as a pass.
    """

    slug: str
    verified: bool
    reason: str


def derive_spec_identity(*, spec_document: str, spec_id: str, facts: DocumentFacts) -> SpecIdentity:
    """Compute the slug, or fall back to the client's id when it cannot be.

    ``parse.ts`` builds the slug from ``title === '' ? meta.filename : title``.
    There is no title here when the document is YAML or has no ``info.title``,
    and **the filename is not in the request body at all** -- ``CreateRunInput``
    carries ``specDocument`` and nothing else about the file.  So for an
    untitled document the derivation is not reproducible from the request, and
    the honest response is to say so rather than invent a slug that would
    disagree with the one the browser computed and file the same document twice.

    The fallback is not silent: ``verified=False`` reaches the caller, which
    records it and skips the consistency check it cannot perform.
    """
    if facts.title:
        return SpecIdentity(
            slug=f"{slugify(facts.title)}_{hash_string(spec_document)}",
            verified=True,
            reason="derived from the document's info.title",
        )

    return SpecIdentity(
        slug=strip_spec_prefix(spec_id),
        verified=False,
        reason=(
            "the document has no info.title, and the slug's fallback source "
            "(the uploaded filename) is not part of the request body"
        ),
    )
