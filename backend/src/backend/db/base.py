"""Declarative base and the column mixins every model shares.

This module is deliberately free of any engine, session or environment
handling: importing a model module must not open a connection, read ``.env``
or build an :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.  ``database.py``
imports ``Base`` from here, not the other way round.

The metadata naming convention is the reason this file exists now rather than
later.  PostgreSQL invents names for unnamed constraints (``projects_user_id_fkey``)
and those names differ between a fresh database and one built by an earlier
migration, so any future ``op.drop_constraint`` would have to guess.  Adding the
convention after 17 tables exist would require a large renaming migration;
adding it before the first one is free.

Note the ``ck`` token: it contains ``%(constraint_name)s``, which makes
SQLAlchemy raise ``InvalidRequestError`` for any ``CheckConstraint`` that does
not carry an explicit ``name=``.  That is intentional -- every check constraint
in this project is named by hand.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "CreatedAtMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every model in this project."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key generated in Python.

    ``default=uuid.uuid4`` rather than a server default: the application has the
    id before the flush, which is what lets a response body and the rows it
    refers to be assembled in one pass.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class CreatedAtMixin:
    """Adds a single, never-updated creation timestamp.

    For append-only records: request history, run results.
    """

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` for records that are edited."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
