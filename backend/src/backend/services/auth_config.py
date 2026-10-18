"""Auth configuration, read from the process environment.

The default is deliberately self-hosted: an existing open-source deployment
must keep working with its guest sessions and its own model key. OAuth is opt-in
by setting DEPLOYMENT_MODE=official_cloud and provider credentials.

No secret is ever returned by this module's public status helpers. The provider
configured booleans are safe to expose to the browser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

__all__ = [
    "AuthConfigurationError",
    "AuthSettings",
    "load_auth_settings",
    "safe_next_path",
]

DEPLOYMENT_MODE_ENV = "DEPLOYMENT_MODE"
PUBLIC_BASE_URL_ENV = "AUTH_PUBLIC_BASE_URL"
FRONTEND_BASE_URL_ENV = "AUTH_FRONTEND_BASE_URL"
SESSION_SECRET_ENV = "AUTH_SESSION_SECRET"
COOKIE_SECURE_ENV = "AUTH_COOKIE_SECURE"
SESSION_TTL_ENV = "AUTH_SESSION_TTL_SECONDS"
STATE_TTL_ENV = "AUTH_STATE_TTL_SECONDS"
CORS_ENV = "CORS_ALLOW_ORIGINS"

OFFICIAL_GUEST_ENABLED_ENV = "AUTH_OFFICIAL_GUEST_ENABLED"
OFFICIAL_GUEST_MAX_PROJECTS_ENV = "AUTH_OFFICIAL_GUEST_MAX_PROJECTS"
OFFICIAL_GUEST_MAX_RUNS_ENV = "AUTH_OFFICIAL_GUEST_MAX_RUNS"
OFFICIAL_GUEST_MAX_AGENT_TASKS_ENV = "AUTH_OFFICIAL_GUEST_MAX_AGENT_TASKS"
OFFICIAL_GUEST_DAILY_AGENT_TASKS_ENV = "AUTH_OFFICIAL_GUEST_DAILY_AGENT_TASKS"

DEFAULT_PUBLIC_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_BASE_URL = "http://127.0.0.1:5173"
DEFAULT_SESSION_TTL_SECONDS = 14 * 24 * 60 * 60
DEFAULT_STATE_TTL_SECONDS = 10 * 60
DEFAULT_CORS_ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
DEFAULT_OFFICIAL_GUEST_ENABLED = False
DEFAULT_OFFICIAL_GUEST_MAX_PROJECTS = 3
DEFAULT_OFFICIAL_GUEST_MAX_RUNS = 10
DEFAULT_OFFICIAL_GUEST_MAX_AGENT_TASKS = 1
DEFAULT_OFFICIAL_GUEST_DAILY_AGENT_TASKS = 10

AUTH_COOKIE_NAME = "api_session"
OAUTH_STATE_COOKIE_NAME = "api_oauth_state"

SELF_HOSTED = "self_hosted"
OFFICIAL_CLOUD = "official_cloud"

PROVIDERS = ("github", "google")
SAFE_PROVIDER_NAMES = frozenset(PROVIDERS)


class AuthConfigurationError(ValueError):
    """The deployment mode or a required URL is invalid."""


def _normalise_mode(raw: str) -> str:
    value = raw.strip().lower().replace("-", "_")
    if value in (SELF_HOSTED, OFFICIAL_CLOUD):
        return value
    raise AuthConfigurationError(
        "DEPLOYMENT_MODE must be self_hosted or official_cloud"
    )


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _as_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return parsed.scheme + "://" + parsed.netloc


def safe_next_path(value: str | None, default: str = "/console") -> str:
    """Allow only a same-site absolute path.

    A target such as https://evil.example, //evil.example or a backslash
    variant is rejected. The caller remains on the configured frontend origin.
    """
    if value is None:
        return default

    candidate = value.strip()
    if candidate == "" or not candidate.startswith("/"):
        return default
    if candidate.startswith("//") or "\\" in candidate:
        return default
    if len(candidate) > 500:
        return default
    return candidate


@dataclass(frozen=True)
class AuthSettings:
    deployment_mode: str
    public_base_url: str
    frontend_base_url: str
    session_cookie_secure: bool
    session_ttl_seconds: int
    state_ttl_seconds: int
    state_secret: str
    github_client_id: str
    github_client_secret: str
    github_redirect_uri: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_oidc_discovery_url: str
    cors_origins: tuple[str, ...]
    allow_official_guests: bool
    official_guest_max_projects: int
    official_guest_max_runs: int
    official_guest_max_agent_tasks: int
    official_guest_daily_agent_tasks: int

    @property
    def official_cloud(self) -> bool:
        return self.deployment_mode == OFFICIAL_CLOUD

    @property
    def official_guest_enabled(self) -> bool:
        return self.official_cloud and self.allow_official_guests

    @property
    def guest_experience_enabled(self) -> bool:
        """Guest sessions are the native identity in self-hosted deployments."""
        return not self.official_cloud or self.official_guest_enabled

    @property
    def login_required(self) -> bool:
        return self.official_cloud and not self.official_guest_enabled

    def provider_configured(self, provider: str) -> bool:
        if not self.official_cloud or self.state_secret == "":
            return False
        if provider == "github":
            return bool(self.github_client_id and self.github_client_secret)
        if provider == "google":
            return bool(
                self.google_client_id
                and self.google_client_secret
                and self.google_oidc_discovery_url
            )
        return False

    def callback_uri(self, provider: str) -> str:
        if provider == "github":
            return self.github_redirect_uri
        if provider == "google":
            return self.google_redirect_uri
        raise KeyError(provider)

    def allowed_origins(self) -> tuple[str, ...]:
        values = list(self.cors_origins)
        for value in (self.public_base_url, self.frontend_base_url):
            origin = _origin(value)
            if origin != "":
                values.append(origin)
        return tuple(dict.fromkeys(values))

    def redirect_after_login(self, path: str | None) -> str:
        return self.frontend_base_url.rstrip("/") + safe_next_path(path)


def load_auth_settings() -> AuthSettings:
    mode = _normalise_mode(os.getenv(DEPLOYMENT_MODE_ENV, SELF_HOSTED))

    public_base = (os.getenv(PUBLIC_BASE_URL_ENV, DEFAULT_PUBLIC_BASE_URL)).rstrip("/")
    frontend_base = (os.getenv(FRONTEND_BASE_URL_ENV, DEFAULT_FRONTEND_BASE_URL)).rstrip("/")
    if not public_base.startswith(("http://", "https://")):
        raise AuthConfigurationError("AUTH_PUBLIC_BASE_URL must be an http(s) URL")
    if not frontend_base.startswith(("http://", "https://")):
        raise AuthConfigurationError("AUTH_FRONTEND_BASE_URL must be an http(s) URL")

    secure_default = mode == OFFICIAL_CLOUD
    cors_raw = os.getenv(CORS_ENV, DEFAULT_CORS_ALLOW_ORIGINS)
    cors_origins = tuple(
        origin for origin in (_origin(part) for part in cors_raw.split(",")) if origin
    )

    github_redirect = os.getenv(
        "GITHUB_REDIRECT_URI", public_base + "/api/auth/callback/github"
    ).strip()
    google_redirect = os.getenv(
        "GOOGLE_REDIRECT_URI", public_base + "/api/auth/callback/google"
    ).strip()

    return AuthSettings(
        deployment_mode=mode,
        public_base_url=public_base,
        frontend_base_url=frontend_base,
        session_cookie_secure=_parse_bool(
            os.getenv(COOKIE_SECURE_ENV), secure_default
        ),
        session_ttl_seconds=_as_int(
            os.getenv(SESSION_TTL_ENV), DEFAULT_SESSION_TTL_SECONDS
        ),
        state_ttl_seconds=_as_int(os.getenv(STATE_TTL_ENV), DEFAULT_STATE_TTL_SECONDS),
        state_secret=os.getenv(SESSION_SECRET_ENV, "").strip(),
        github_client_id=os.getenv("GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("GITHUB_CLIENT_SECRET", "").strip(),
        github_redirect_uri=github_redirect,
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=google_redirect,
        google_oidc_discovery_url=os.getenv(
            "GOOGLE_OIDC_DISCOVERY_URL",
            "https://accounts.google.com/.well-known/openid-configuration",
        ).strip(),
        cors_origins=cors_origins,
        allow_official_guests=_parse_bool(
            os.getenv(OFFICIAL_GUEST_ENABLED_ENV),
            DEFAULT_OFFICIAL_GUEST_ENABLED,
        ),
        official_guest_max_projects=_as_int(
            os.getenv(OFFICIAL_GUEST_MAX_PROJECTS_ENV),
            DEFAULT_OFFICIAL_GUEST_MAX_PROJECTS,
        ),
        official_guest_max_runs=_as_int(
            os.getenv(OFFICIAL_GUEST_MAX_RUNS_ENV),
            DEFAULT_OFFICIAL_GUEST_MAX_RUNS,
        ),
        official_guest_max_agent_tasks=_as_int(
            os.getenv(OFFICIAL_GUEST_MAX_AGENT_TASKS_ENV),
            DEFAULT_OFFICIAL_GUEST_MAX_AGENT_TASKS,
        ),
        official_guest_daily_agent_tasks=_as_int(
            os.getenv(OFFICIAL_GUEST_DAILY_AGENT_TASKS_ENV),
            DEFAULT_OFFICIAL_GUEST_DAILY_AGENT_TASKS,
        ),
    )
