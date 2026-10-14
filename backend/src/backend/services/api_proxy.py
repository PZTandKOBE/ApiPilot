"""One proxied request, from the user's composed call to the target's answer.

This is the Manual API Client's missing half: the browser cannot call an
arbitrary API itself (CORS, and credentials the browser will not let a page set),
so the call is made here, on behalf of a verified guest, against a target the
user named.

**What makes this a proxy and not an open relay.**  Everything in this module
exists to answer three questions in order, and to refuse if any answer is bad:

1. *Is the caller allowed to reach this project?*  Answered by the router, before
   this module is entered: a DNS lookup must not be reachable by a caller who owns
   nothing.
2. *Where would this request actually go?*  Answered by resolving the name and
   classifying **every** address in the answer.  One blocked address fails the
   call -- a name that returns a public and a private address is a name that is
   trying something.
3. *Is the socket dialled to that address and no other?*  Answered by
   `services/proxy_transport`, which is handed the validated IP as an IP literal.
   Nothing re-resolves.

**What this module deliberately does not do.**

* It does not follow redirects.  A 3xx is a response, and it is returned as one:
  following it would mean a second URL, a second DNS answer and a second policy
  decision, and doing that correctly is a feature, not a shortcut.
* It does not pass the platform's own identity upstream.  `X-Guest-Session` is
  dropped by name, `Cookie` with it (it is ambient browser state, not a choice
  about this request), and the protocol headers that decide framing are dropped
  because the client would be writing them wrong.  A target `Authorization` is
  forwarded, because configuring the API under test is the point.
* It does not invent a status text when the target sent none.
* It does not put a token, a cookie or a header value in a log line.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpcore

from backend.schemas.proxy import (
    ProxyCookie,
    ProxyHeaderPair,
    ProxyRequest,
    ProxyResponse,
)

__all__ = [
    "BODY_TOO_LARGE_CODE",
    "BLOCKED_TARGET_CODE",
    "INVALID_REQUEST_CODE",
    "TARGET_UNREACHABLE_CODE",
    "TIMEOUT_CODE",
    "UPSTREAM_FAILED_CODE",
    "BoundedNetworkBackend",
    "ProxyError",
    "classify_address",
    "filter_request_headers",
    "forward",
    "open_pool",
    "resolve_target",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Failure vocabulary
# --------------------------------------------------------------------------- #

INVALID_REQUEST_CODE = "proxy-invalid-request"
"""The request itself is not something this proxy will send (bad scheme, bad
method, a header that would break framing)."""

BLOCKED_TARGET_CODE = "proxy-target-blocked"
"""The target resolves somewhere this service refuses to connect to.

One code for every refusal on purpose: loopback, a private range, a metadata
address and a mixed answer are all "no", and telling a caller *which* private
network it nearly reached turns the refusal into a scanning oracle.
"""

TIMEOUT_CODE = "proxy-timeout"
TARGET_UNREACHABLE_CODE = "proxy-target-unreachable"
BODY_TOO_LARGE_CODE = "proxy-response-too-large"
UPSTREAM_FAILED_CODE = "proxy-upstream-failed"

MESSAGE_KEYS = {
    INVALID_REQUEST_CODE: "console.apiClient.error.transport",
    BLOCKED_TARGET_CODE: "console.apiClient.error.network",
    TIMEOUT_CODE: "console.apiClient.error.timeout",
    TARGET_UNREACHABLE_CODE: "console.apiClient.error.network",
    BODY_TOO_LARGE_CODE: "console.apiClient.error.transport",
    UPSTREAM_FAILED_CODE: "console.apiClient.error.network",
}
"""The i18n key each failure reports.  They are the keys the API Client already
renders for a transport failure, so the client needs no new vocabulary to show
one of these."""


class ProxyError(Exception):
    """A refusal or a failure with a code the caller can branch on."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #

DEFAULT_TIMEOUT_MS = 15_000
MAX_TIMEOUT_MS = 60_000
REQUEST_TIMEOUT_MS = 10_000
"""Connect and read.  A per-operation bound, so a target that accepts and then
says nothing cannot hold a worker open until the overall deadline."""

CONNECT_TIMEOUT_MS = 5_000
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 2_097_152
MAX_RESPONSE_HEADERS = 100
MAX_RESPONSE_HEADER_BYTES = 32_768
MAX_REDIRECT_STATUS = 399
"""Not a limit so much as a marker: a status at or above 300 is reported, never
followed.  See the module docstring."""

DEFAULT_PORTS = {b"http": 80, b"https": 443}
ALLOWED_SCHEMES = frozenset(DEFAULT_PORTS)

# Both sets hold **bytes**, because that is what header names become before they
# are compared.  They held `str` at first, and `b"host" in {"host"}` is False for
# every name -- so the filter forwarded everything, including a client-supplied
# "Transfer-Encoding: chunked" beside a fabricated "Content-Length".  The tests
# caught it only once they also asserted that the target had been *reached*: the
# negative assertions were passing on an empty header list.  A deny list must be
# in the same type as the thing it denies.
HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"proxy-connection",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
"""RFC 9110's hop-by-hop set.  They describe *this* hop, so forwarding them
describes the wrong one."""

FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        b"host",
        b"content-length",
        b"cookie",
        b"cookie2",
        b"x-guest-session",
    }
)
"""Headers the client may not set, and why each one.

`host` and `content-length` are derived from the URL and the body -- a client that
sets them is either wrong or probing for a request-smuggling shape.  The platform's
own session header is dropped by name so it can never reach a target.  `cookie`
is ambient browser state attached to *this* service's origin, which is not a
decision the user made about the target; a target cookie can be set explicitly as
a header the user types, and that path is not this one.
"""



# --------------------------------------------------------------------------- #
# The dial
# --------------------------------------------------------------------------- #


class _BoundedStream:
    """A stream whose every read and write carries an explicit deadline.

    httpcore reads `timeout` out of the request extensions for the *connect*, but
    leaves reads and writes to whatever the caller passed down.  A target that
    completes its handshake and then dribbles one byte a minute would otherwise
    hold a worker until the overall deadline, so each operation gets its own
    bound here.
    """

    def __init__(self, stream: Any, read_timeout: float) -> None:
        self._stream = stream
        self._read_timeout = read_timeout

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(
            max_bytes, timeout=min(timeout or self._read_timeout, self._read_timeout)
        )

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return await self._stream.write(
            buffer, timeout=min(timeout or self._read_timeout, self._read_timeout)
        )

    async def aclose(self) -> None:
        return await self._stream.aclose()

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class BoundedNetworkBackend(httpcore.AsyncNetworkBackend):
    """The socket layer, with this service's timeouts applied.

    Wrapping the backend rather than the pool is what makes the bounds *explicit
    limits* rather than inherited library defaults: `connect_tcp` is where the
    destination is actually dialled, so that is where the connect timeout has to
    be set, and the stream it returns is where the read and write bounds live.
    """

    def __init__(self, connect_timeout: float, io_timeout: float) -> None:
        self._connect_timeout = connect_timeout
        self._io_timeout = io_timeout
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        stream = await self._inner.connect_tcp(
            host,
            port,
            timeout=min(timeout or self._connect_timeout, self._connect_timeout),
            local_address=local_address,
            socket_options=socket_options,
        )
        return _BoundedStream(stream, self._io_timeout)

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Any = None
    ) -> Any:
        # Not a transport this proxy offers; refused rather than proxied.
        raise httpcore.ConnectError("unix sockets are not proxied")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def open_pool(
    *,
    ip: bytes,
    port: int,
    hostname: str,
    scheme: bytes,
    connect_timeout: float,
    io_timeout: float,
) -> httpcore.AsyncConnectionPool:
    """A pool that can dial exactly one address: the one that was validated.

    `ip` and `port` decide the socket.  `hostname` is used only as the SNI name
    and the `Host` header -- never as a connection target -- which is what makes
    it safe for that string to be the user's original spelling.

    httpcore resolves nothing: the host in the `httpcore.URL` handed to this pool
    is already the IP literal from `resolve_target`, and that string is what
    reaches `socket.connect`.  Measured rather than assumed -- a network backend
    standing in at the socket layer records it.  A design that validated a name
    and then let the HTTP client resolve it again would leave the whole window
    between the two lookups open to a rebind; this one has no second lookup to
    race.

    The name still travels, so TLS still means something.  httpcore takes the SNI
    name from `request.extensions["sni_hostname"]` (`_async/connection.py:107`),
    falling back to the origin host, so the original name is handed over
    explicitly and the *default* verification context is left in place.  Measured:
    a handshake through this pool presents the real name in SNI, and
    `CERTIFICATE_VERIFY_FAILED` is raised when the name does not match the
    certificate.

    One connection, no keep-alive, and a fresh pool per request -- so a later call
    can never inherit a socket opened for an earlier target, and one proxied call
    can hold at most one socket.
    """
    return httpcore.AsyncConnectionPool(
        network_backend=BoundedNetworkBackend(connect_timeout, io_timeout),
        # ssl_context=None means httpcore's own default_ssl_context():
        # CERT_REQUIRED against the system trust store.  A permissive context here
        # would be the single line that turns this proxy into a credential-leaking
        # man in the middle, so it is left at its default and a test asserts on
        # rejection rather than on configuration.
        max_connections=1,
        max_keepalive_connections=0,
        keepalive_expiry=0.0,
        http1=True,
        http2=False,
        retries=0,
        proxy=None,
        uds=None,
        local_address=None,
    )


# --------------------------------------------------------------------------- #
# URL policy
# --------------------------------------------------------------------------- #


def _fail(code: str, detail: str = "") -> ProxyError:
    return ProxyError(code, detail)


def _header_bytes(name: str, value: str) -> tuple[bytes, bytes]:
    """Reject anything that could not be a header on the wire.

    The check is on the *encoded* form, because that is what gets written: a
    non-ASCII name is not a header name, and CR or LF anywhere in a value is a
    request-splitting attempt regardless of what it decoded to.
    """
    if "\r" in value or "\n" in value or "\x00" in value:
        raise _fail(INVALID_REQUEST_CODE, "header value contains a control character")

    try:
        name_b = name.encode("ascii")
        value_b = value.encode("latin-1")
    except UnicodeError as exc:
        raise _fail(INVALID_REQUEST_CODE, "header is not encodable") from exc

    if name_b == b"" or any(byte <= 0x20 or byte >= 0x7F for byte in name_b):
        raise _fail(INVALID_REQUEST_CODE, "header name is not a token")

    if b":" in name_b:
        raise _fail(INVALID_REQUEST_CODE, "header name contains a colon")

    return name_b, value_b


def filter_request_headers(
    pairs: list[ProxyHeaderPair],
) -> list[tuple[bytes, bytes]]:
    """The headers that will actually be sent, in the order the user wrote them.

    Dropping is silent and by name; anything that is not on a deny list is
    forwarded, including a target `Authorization`, because the user configuring
    the API under test is the whole purpose of the API Client.
    """
    out: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()

    for pair in pairs:
        name_b, value_b = _header_bytes(pair.name, pair.value)
        lowered = name_b.lower()

        if lowered in FORBIDDEN_REQUEST_HEADERS or lowered in HOP_BY_HOP:
            continue
        if lowered in seen:
            # A repeated name is legal HTTP but ambiguous for most targets, and
            # the client already resolves duplicates before sending.  First wins.
            continue

        seen.add(lowered)
        out.append((name_b, value_b))

    return out


def _resolve_port(scheme: str, explicit: int | None) -> int:
    if explicit is None:
        return DEFAULT_PORTS[scheme.encode()]
    if not 1 <= explicit <= 65535:
        raise _fail(INVALID_REQUEST_CODE, "port out of range")
    return explicit


def _check_url(url: str) -> tuple[str, str, int, str]:
    """`(scheme, hostname, port, target)` or a refusal.

    Rejects the shapes that mean something other than "call this URL": a scheme
    that is not http(s), credentials in the authority, a bracketed host that is
    not an IP, and anything a client could use to smuggle a second request.
    """
    if len(url) > 4096:
        raise _fail(INVALID_REQUEST_CODE, "url too long")

    try:
        parts: SplitResult = urlsplit(url)
    except ValueError as exc:
        raise _fail(INVALID_REQUEST_CODE, "url could not be parsed") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise _fail(INVALID_REQUEST_CODE, "only http and https are proxied")

    if parts.username is not None or parts.password is not None:
        raise _fail(INVALID_REQUEST_CODE, "url carries credentials")

    hostname = parts.hostname or ""
    if hostname == "":
        raise _fail(INVALID_REQUEST_CODE, "url carries no host")

    if "\r" in url or "\n" in url or "\x00" in url:
        raise _fail(INVALID_REQUEST_CODE, "url contains a control character")

    try:
        port = parts.port
    except ValueError as exc:  # a non-numeric or out-of-range port
        raise _fail(INVALID_REQUEST_CODE, "url carries an invalid port") from exc

    resolved_port = _resolve_port(scheme, port)

    # No path, query or fragment may be smuggled through the netloc.  Encoding
    # the URL back and re-parsing is what makes that a property rather than a
    # hope: if the two disagree, the original said something else.
    target = urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment))
    netloc = parts.netloc
    expected_netloc = hostname if port is None else f"{hostname}:{resolved_port}"
    if netloc.lower() != expected_netloc.lower():
        raise _fail(INVALID_REQUEST_CODE, "url authority is not canonical")

    return scheme, hostname, resolved_port, target


# --------------------------------------------------------------------------- #
# Address policy
# --------------------------------------------------------------------------- #


def classify_address(address: str) -> str:
    """`"allowed"` for a public unicast address, otherwise the reason it is not.

    The default is *deny*: an address is allowed only when it is global.  The
    named reasons exist for the report and the tests, not for the caller -- the
    endpoint answers one code for all of them.
    """
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return "unparseable"

    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) reaches an IPv4 destination;
    # classify what it actually reaches, not the wrapper.
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped

    # Cloud metadata services answer on link-local (and, on some platforms, on a
    # globally-shaped address that is nevertheless not the user's target).
    if str(parsed) in METADATA_ADDRESSES:
        return "metadata"

    if parsed.is_loopback:
        return "loopback"
    if parsed.is_private:
        return "private"
    if parsed.is_link_local:
        return "link-local"
    if parsed.is_multicast:
        return "multicast"
    if parsed.is_reserved:
        return "reserved"
    if parsed.is_unspecified:
        return "unspecified"
    if not parsed.is_global:
        return "not-global"

    return "allowed"


METADATA_ADDRESSES = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / OpenStack IMDS
        "169.254.170.2",  # ECS task metadata
        "100.100.100.200",  # Alibaba Cloud
        "fd00:ec2::254",  # AWS IMDS over IPv6
    }
)

_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _is_local_name(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    return lowered in _LOCAL_NAMES or lowered.endswith(".localhost")


async def resolve_target(hostname: str, port: int) -> bytes:
    """The one address a checked name may be dialled at, or a refusal.

    **Every** answer is classified, and one blocked address fails the whole call.
    That is the difference between this and a check that takes the first public
    answer it finds: a name that returns `93.184.216.34` and `127.0.0.1` is a name
    whose owner is trying to reach loopback, and accepting it because one answer
    looked fine would be exactly the hole this is here to close.

    Resolution happens once, here.  The address returned is the address dialled.
    """
    if _is_local_name(hostname):
        raise _fail(BLOCKED_TARGET_CODE, "local name")

    loop = asyncio.get_running_loop()

    try:
        infos = await loop.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise _fail(TARGET_UNREACHABLE_CODE, "name did not resolve") from exc

    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addresses.append(str(sockaddr[0]))

    if not addresses:
        raise _fail(TARGET_UNREACHABLE_CODE, "name resolved to nothing")

    for address in addresses:
        reason = classify_address(address)
        if reason != "allowed":
            logger.info(
                "proxy refused target host=%s reason=%s", hostname, reason
            )
            raise _fail(BLOCKED_TARGET_CODE, reason)

    return addresses[0].encode("ascii")


# --------------------------------------------------------------------------- #
# The call itself
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Timing:
    started: float

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def _parse_cookies(headers: list[tuple[bytes, bytes]]) -> list[ProxyCookie]:
    """`Set-Cookie` values, split the way `ApiResponse.cookies` reads them.

    A cookie that will not parse is skipped rather than guessed at: a wrong
    cookie is worse than an absent one.
    """
    out: list[ProxyCookie] = []

    for name, value in headers:
        if name.lower() != b"set-cookie":
            continue

        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(value.decode("latin-1"))
        except Exception:
            continue

        for key, morsel in jar.items():
            out.append(
                ProxyCookie(
                    name=key,
                    value=morsel.value,
                    domain=morsel["domain"] or "",
                    path=morsel["path"] or "",
                    http_only=bool(morsel["httponly"]),
                    secure=bool(morsel["secure"]),
                    expires=morsel["expires"] or "",
                )
            )

    return out


async def _read_capped(response: httpcore.Response, cap: int) -> tuple[bytes, bool]:
    """Read the body, refusing to read past `cap`.

    The cap is enforced while reading, not after: a target that streams a
    gigabyte is stopped at the limit instead of being buffered and then judged.
    """
    chunks: list[bytes] = []
    total = 0

    async for chunk in response.aiter_stream():
        total += len(chunk)
        if total > cap:
            raise _fail(BODY_TOO_LARGE_CODE, "response exceeded the cap")
        chunks.append(chunk)

    return b"".join(chunks), False


async def forward(payload: ProxyRequest) -> ProxyResponse:
    """Send one checked request, and return the target's answer.

    Raises `ProxyError` with a code from this module when the call never became
    an answer.  An upstream 4xx or 5xx is *not* an error here -- it is the
    answer, and it is returned as one.
    """
    timeout_ms = min(payload.timeout_ms or DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS)

    scheme, hostname, port, target = _check_url(payload.url)

    body: bytes | None = None
    if payload.body is not None:
        body = payload.body.encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise _fail(INVALID_REQUEST_CODE, "request body too large")

    headers = filter_request_headers(payload.headers)

    started = _Timing(time.monotonic())

    # Authorization happens in the router.  By the time this line runs, the
    # caller owns the project and the only network work left is the lookup below.
    ip = await resolve_target(hostname, port)

    # Content-Length, and why it is set here rather than left to httpcore.
    #
    # The pool's `handle_async_request` does not encode the request: that happens
    # in `httpcore.request()` -> `Request.create` -> `encode_request`, and none of
    # those are reachable when a pool is driven directly, as this function must in
    # order to pin the address and the SNI name.  Without the header h11 sees a
    # body with no length declared and refuses it ("Too much data for declared
    # Content-Length", measured); with the client's own value it would be framing
    # the body on somebody else's word.  So the length is derived from the body
    # here, which is exactly what `include_request_headers` would have done.
    #
    # `include_request_headers` is a private helper, and it is called rather than
    # reimplemented so that httpcore's own rules -- "no Content-Length for a bodyless
    # request", measured to matter -- cannot drift away from this code.
    url = httpcore.URL(
        scheme=scheme.encode(),
        host=ip,
        port=port,
        target=target.encode("latin-1"),
    )
    headers = httpcore._models.include_request_headers(
        headers=headers, url=url, content=body
    )

    # Host is written here, never taken from the caller, and only *after* the
    # helper above: that helper's own rule is "add a Host derived from the URL when
    # the request has none", and the URL names the validated IP.  Sending
    # `Host: 93.184.216.34` would be asking the target for the wrong vhost -- the
    # very thing pinning the address is meant to make precise.  The client may not
    # set it (see FORBIDDEN_REQUEST_HEADERS) because a Host that disagreed with the
    # address that was checked would let a caller reach a different vhost on that
    # machine than the one this service validated.
    headers = [
        (name, value)
        for name, value in headers
        if name.lower() != b"host"
    ]
    headers.append(
        (
            b"host",
            f"{hostname}:{port}".encode("ascii")
            if port not in (80, 443)
            else hostname.encode("ascii"),
        )
    )

    request = httpcore.Request(
        method=payload.method.encode("ascii"),
        url=url,
        headers=headers,
        content=body,
        extensions={
            # The name TLS must verify against.  Without it httpcore would use the
            # origin host -- the IP -- and every real certificate would fail.
            "sni_hostname": hostname,
            # httpcore reads the connect bound from here; the read and write
            # bounds are applied by BoundedNetworkBackend on the stream itself.
            "timeout": {
                "connect": CONNECT_TIMEOUT_MS / 1000,
                "read": REQUEST_TIMEOUT_MS / 1000,
                "write": REQUEST_TIMEOUT_MS / 1000,
                "pool": REQUEST_TIMEOUT_MS / 1000,
            },
        },
    )

    # Everything that can fail is inside this `try` -- including opening the pool,
    # which is where a permissive context or a bogus network backend would show up.
    # An exception that escaped it would become a 500 with a traceback, and this
    # service does not hand those out.
    pool: httpcore.AsyncConnectionPool | None = None
    try:
        pool = open_pool(
            ip=ip,
            port=port,
            hostname=hostname,
            scheme=scheme.encode(),
            connect_timeout=CONNECT_TIMEOUT_MS / 1000,
            io_timeout=REQUEST_TIMEOUT_MS / 1000,
        )

        async with asyncio.timeout(timeout_ms / 1000):
            response = await pool.handle_async_request(request)
            try:
                raw, _ = await _read_capped(response, MAX_RESPONSE_BYTES)
                status = response.status
                # httpcore keeps the upstream reason phrase in the response
                # extensions, as bytes; HTTP/2 has none, so an empty string is the
                # honest answer there and no phrase is invented.
                phrase = response.extensions.get("reason_phrase") or b""
                reason = phrase.decode("latin-1") if isinstance(phrase, bytes) else str(phrase)
                raw_headers = list(response.headers)
            finally:
                await response.aclose()
    except ProxyError:
        raise
    except TimeoutError as exc:
        # `asyncio.timeout`'s deadline, which is the *builtin* TimeoutError.
        raise _fail(TIMEOUT_CODE, "deadline") from exc
    except httpcore.TimeoutException as exc:
        # httpcore's connect / read / write / pool timeouts.  They derive from
        # httpcore.TimeoutException and NOT from the builtin TimeoutError, so the
        # clause above does not catch them -- measured, after a target that
        # accepted a connection and said nothing came back as an upstream failure
        # instead of a timeout.
        raise _fail(TIMEOUT_CODE, "timeout") from exc
    except httpcore.ConnectError as exc:
        raise _fail(TARGET_UNREACHABLE_CODE, "connect") from exc
    except httpcore.UnsupportedProtocol as exc:
        raise _fail(UPSTREAM_FAILED_CODE, "protocol") from exc
    except httpcore.ProxyError as exc:
        raise _fail(UPSTREAM_FAILED_CODE, "proxied") from exc
    except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
        raise _fail(UPSTREAM_FAILED_CODE, "network") from exc
    except Exception as exc:  # noqa: BLE001 - nothing internal may escape
        # Nothing internal leaks: no traceback, no path, no library detail.  The
        # class name is the most that travels, and it is not returned to the client
        # -- the error envelope carries only the code.
        logger.warning("proxy upstream failure kind=%s", exc.__class__.__name__)
        raise _fail(UPSTREAM_FAILED_CODE, exc.__class__.__name__) from exc
    finally:
        if pool is not None:
            await pool.aclose()

    if len(raw_headers) > MAX_RESPONSE_HEADERS:
        raise _fail(BODY_TOO_LARGE_CODE, "too many response headers")

    header_bytes = sum(len(k) + len(v) for k, v in raw_headers)
    if header_bytes > MAX_RESPONSE_HEADER_BYTES:
        raise _fail(BODY_TOO_LARGE_CODE, "response headers too large")

    content_type = ""
    for name, value in raw_headers:
        if name.lower() == b"content-type":
            content_type = value.decode("latin-1")
            break

    text, body_encoding = _decode_body(raw, content_type)

    logger.info(
        "proxy forwarded scheme=%s host=%s port=%s status=%s bytes=%s ms=%s",
        scheme,
        hostname,
        port,
        status,
        len(raw),
        started.elapsed_ms(),
    )

    return ProxyResponse(
        status=status,
        status_text=reason,
        headers=[
            ProxyHeaderPair(
                name=name.decode("latin-1"), value=value.decode("latin-1")
            )
            for name, value in raw_headers
        ],
        cookies=_parse_cookies(raw_headers),
        body=text,
        content_type=content_type,
        body_encoding=body_encoding,
        time_ms=started.elapsed_ms(),
        size_bytes=len(raw),
    )


_TEXTUAL_HINTS = (
    "json",
    "text/",
    "xml",
    "javascript",
    "x-www-form-urlencoded",
    "yaml",
    "csv",
    "html",
)


def _decode_body(raw: bytes, content_type: str) -> tuple[str, str]:
    """`(text, encoding)` for the body, deciding honestly.

    A body is text when its content type says so and it decodes as UTF-8.  For
    anything else the bytes are *described*, not mangled into a string that looks
    like data: the client is told the body is binary and how big it was, rather
    than being handed replacement characters it cannot tell from content.
    """
    lowered = content_type.lower()
    looks_textual = lowered == "" or any(hint in lowered for hint in _TEXTUAL_HINTS)

    if looks_textual:
        try:
            return raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            pass

    return "", "binary"
