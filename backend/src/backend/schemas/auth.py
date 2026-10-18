"""Public auth response shapes. Never include provider tokens or secrets."""

from __future__ import annotations

from typing import Literal

from backend.schemas.base import Schema

__all__ = ["AuthConfigResponse", "AuthProviderStatus", "CurrentUserResponse"]


class AuthProviderStatus(Schema):
    id: Literal["github", "google"]
    configured: bool


class AuthConfigResponse(Schema):
    deployment_mode: Literal["self_hosted", "official_cloud"]
    login_required: bool
    guest_enabled: bool
    providers: list[AuthProviderStatus]


class CurrentUserResponse(Schema):
    id: str
    name: str
    email: str | None
    avatar_url: str | None
    provider: str
