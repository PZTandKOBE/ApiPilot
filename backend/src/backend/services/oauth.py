"""OAuth/OIDC provider integration.

Authlib owns the authorization URL, token exchange and OIDC ID-token
signature/issuer/audience/expiry/nonce validation. This module owns only the
ApiPilot decisions: state is also recorded in PostgreSQL as one-time, GitHub
profile fetching gets no repo/gist scope, and provider tokens are discarded
after the identity claims are read.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import auth as auth_service
from backend.services.auth import AuthError, OAuthIdentity
from backend.services.auth_config import AuthSettings

__all__ = ["OAuthService"]

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_SCOPE = "read:user"
GOOGLE_SCOPE = "openid email profile"


class OAuthService:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self.oauth = OAuth()
        if settings.provider_configured("github"):
            self.oauth.register(
                name="github",
                client_id=settings.github_client_id,
                client_secret=settings.github_client_secret,
                authorize_url=GITHUB_AUTHORIZE_URL,
                access_token_url=GITHUB_TOKEN_URL,
                api_base_url="https://api.github.com/",
                client_kwargs={
                    "scope": GITHUB_SCOPE,
                    "code_challenge_method": "S256",
                },
            )
        if settings.provider_configured("google"):
            self.oauth.register(
                name="google",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                server_metadata_url=settings.google_oidc_discovery_url,
                client_kwargs={"scope": GOOGLE_SCOPE},
            )

    def configured(self, provider: str) -> bool:
        return self.settings.provider_configured(provider)

    def _app(self, provider: str):
        if not self.configured(provider):
            raise AuthError("provider-unavailable")
        return self.oauth.create_client(provider)

    async def start(
        self,
        request: Request,
        session: AsyncSession,
        *,
        provider: str,
        redirect_after: str | None,
    ) -> RedirectResponse:
        app = self._app(provider)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        nonce = secrets.token_urlsafe(24) if provider == "google" else None
        redirect_uri = self.settings.callback_uri(provider)

        await auth_service.create_transaction(
            session,
            state=state,
            provider=provider,
            nonce=nonce,
            redirect_after=redirect_after,
            settings=self.settings,
        )
        await session.commit()

        # Authlib stores the one-time state, PKCE verifier and nonce in its
        # short-lived signed session cookie. The DB row is the replay check.
        return await app.authorize_redirect(
            request,
            redirect_uri,
            state=state,
            code_verifier=verifier,
            nonce=nonce,
        )

    async def complete(
        self,
        request: Request,
        session: AsyncSession,
        *,
        provider: str,
    ) -> tuple[OAuthIdentity, str | None]:
        provider_error = request.query_params.get("error")
        state = request.query_params.get("state")
        if not state:
            raise AuthError("state-invalid")

        try:
            transaction = await auth_service.consume_transaction(
                session, state=state, provider=provider
            )
        except AuthError:
            raise

        if provider_error:
            code = (
                "oauth-cancelled"
                if provider_error in ("access_denied", "access-denied")
                else "oauth-failed"
            )
            raise AuthError(code)

        app = self._app(provider)
        try:
            token = await app.authorize_access_token(request)
        except OAuthError:
            raise AuthError("oauth-failed") from None
        except Exception:
            logger.warning("OAuth token exchange failed for %s", provider)
            raise AuthError("oauth-failed") from None

        claims = await self._claims(provider, app, token, transaction.nonce)
        identity = self._identity(provider, claims)
        return identity, transaction.redirect_after

    async def _claims(
        self, provider: str, app: Any, token: Any, nonce: str | None
    ) -> dict[str, Any]:
        if provider == "google":
            userinfo = token.get("userinfo") if isinstance(token, Mapping) else None
            if userinfo is None:
                try:
                    userinfo = await app.parse_id_token(token, nonce=nonce)
                except Exception:
                    raise AuthError("oidc-invalid") from None
            if not isinstance(userinfo, dict):
                raise AuthError("oidc-invalid")
            return userinfo

        access_token = token.get("access_token") if isinstance(token, Mapping) else None
        if not isinstance(access_token, str) or access_token == "":
            raise AuthError("provider-profile-failed")

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(
                    GITHUB_USER_URL,
                    headers={
                        "Authorization": "Bearer " + access_token,
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
        except httpx.HTTPError:
            raise AuthError("provider-profile-failed") from None

        if response.status_code != 200:
            raise AuthError("provider-profile-failed")
        body = response.json()
        if not isinstance(body, dict):
            raise AuthError("provider-profile-failed")
        return body

    def _identity(self, provider: str, claims: dict[str, Any]) -> OAuthIdentity:
        if provider == "google":
            subject = claims.get("sub")
            if not isinstance(subject, str) or subject == "":
                raise AuthError("oidc-invalid")
            email = claims.get("email") if isinstance(claims.get("email"), str) else None
            email_verified = claims.get("email_verified") is True
            username = claims.get("name") if isinstance(claims.get("name"), str) else None
            avatar = claims.get("picture") if isinstance(claims.get("picture"), str) else None
            return OAuthIdentity(
                provider="google",
                subject=subject,
                username=username,
                email=email,
                email_verified=email_verified,
                avatar_url=avatar,
            )

        raw_subject = claims.get("id")
        subject = str(raw_subject) if raw_subject is not None else ""
        if subject == "":
            raise AuthError("provider-profile-failed")
        login = claims.get("login") if isinstance(claims.get("login"), str) else None
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        avatar = (
            claims.get("avatar_url")
            if isinstance(claims.get("avatar_url"), str)
            else None
        )
        return OAuthIdentity(
            provider="github",
            subject=subject,
            username=login,
            email=email,
            # GitHub's public profile email is not proof of verification.
            email_verified=False,
            avatar_url=avatar,
        )
