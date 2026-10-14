/**
 * The real transport: one request, through this product's own backend.
 *
 * The browser cannot call an arbitrary API itself — CORS and the credentials rules
 * are the browser's, not ours — so a manual request is sent to
 * `POST /api/projects/{projectId}/proxy` and the platform makes the call on the
 * user's behalf.  Everything that decides *whether* that call may happen lives in
 * the backend (Task B9: address classification, IP pinning, TLS verification,
 * resource limits); this module is only responsible for saying what the user
 * composed and reporting what came back.
 *
 * **The guest session is attached by the shared HTTP layer, and only there.**
 * `services/http.ts` is the one function every backend call goes through, so this
 * module never touches the token — and, just as importantly, never copies it into
 * the headers it is asking the platform to send upstream.  A user's own target
 * `Authorization` *is* forwarded, because configuring the API under test is the
 * point of the API Client.
 *
 * **A target's 4xx or 5xx is a result, not a failure.** The backend returns the
 * upstream status inside a normal `200` envelope precisely so the response panel
 * can render a 404 the same way it renders a 200.  Only the proxy's own refusals
 * (a blocked target, a timeout, an unreachable host) arrive as platform errors,
 * and those are translated into the client's existing error vocabulary rather than
 * being reported as if the target had answered.
 */

import { request, ApiError } from '@/services/http'
import type { ApiTransport } from '@/services/transport'
import type {
  ApiClientError,
  ApiErrorKind,
  ApiHeaderPair,
  ApiResponse,
  ApiResponseCookie,
  HttpMethod,
  ResolvedApiRequest,
} from '@/types/api'

/** What the backend's `ProxyRequest` accepts, and nothing else. */
export interface ProxyWireRequest {
  readonly method: HttpMethod
  readonly url: string
  readonly headers: readonly ApiHeaderPair[]
  readonly body: string | null
  readonly timeoutMs: number
}

/**
 * What the backend's `ProxyResponse` returns.
 *
 * camelCase because the backend's schemas serialise with a camelCase alias
 * generator — the same convention every other response in this codebase uses.
 * `bodyEncoding` and `bodyTruncated` are read: a binary body is reported as
 * *nothing but its size* rather than as mojibake, and the caller is told which of
 * the two it got.
 */
export interface ProxyWireResponse {
  readonly status: number
  readonly statusText: string
  readonly headers: readonly ApiHeaderPair[]
  readonly cookies: readonly ApiResponseCookie[]
  readonly body: string
  readonly contentType: string
  readonly bodyTruncated: boolean
  readonly bodyEncoding: 'utf-8' | 'binary'
  readonly timeMs: number
  readonly sizeBytes: number
}

export interface ProxyTransportOptions {
  /**
   * The project this console is on.
   *
   * Passed per call rather than held here, because the transport outlives any one
   * project and the store is the only thing that knows which one is active.  A
   * getter would let a stale id be captured; an argument cannot.
   */
  readonly projectId: string
}

/**
 * A proxy failure, in the vocabulary the API Client already renders.
 *
 * Thrown only for the *proxy's* answers.  A target's own 4xx/5xx never reaches
 * here — it comes back inside the envelope as an ordinary response.
 */
export class ProxyTransportError extends Error {
  readonly clientError: ApiClientError

  constructor(clientError: ApiClientError) {
    super(`${clientError.kind} ${clientError.messageKey}`)
    this.name = 'ProxyTransportError'
    this.clientError = clientError
  }
}

/**
 * Where each of the proxy's refusal codes lands in the client's vocabulary.
 *
 * The kinds are the ones `types/api.ts` already defines, so the response panel
 * needs no new branch to show one of these; the keys are the sentences this
 * namespace already owns.  `blocked` and `invalid` share a kind because from the
 * user's seat they are the same event — *this request will not be sent, and here
 * is why* — but they keep separate sentences, because "the URL is malformed" and
 * "that address is not one this service will call" are different mistakes.
 */
const FAILURES: Readonly<
  Record<string, { readonly kind: ApiErrorKind; readonly messageKey: string }>
> = {
  'proxy-timeout': {
    kind: 'timeout',
    messageKey: 'console.apiClient.error.timeout',
  },
  'proxy-target-unreachable': {
    kind: 'network',
    messageKey: 'console.apiClient.error.unreachable',
  },
  'proxy-target-blocked': {
    kind: 'transport',
    messageKey: 'console.apiClient.error.blocked',
  },
  'proxy-invalid-request': {
    kind: 'transport',
    messageKey: 'console.apiClient.error.invalid',
  },
  'proxy-response-too-large': {
    kind: 'transport',
    messageKey: 'console.apiClient.error.tooLarge',
  },
  'proxy-upstream-failed': {
    kind: 'network',
    messageKey: 'console.apiClient.error.network',
  },
  'guest-session-required': {
    kind: 'network',
    messageKey: 'console.apiClient.error.unauthorized',
  },
  'project-not-found': {
    kind: 'network',
    messageKey: 'console.apiClient.error.projectNotReady',
  },
}

/** How a throw that never reached the proxy is described. */
const NETWORK_FAILURE: ApiClientError = {
  kind: 'network',
  messageKey: 'console.apiClient.error.network',
}

const TIMEOUT_FAILURE: ApiClientError = {
  kind: 'timeout',
  messageKey: 'console.apiClient.error.timeout',
}

/**
 * Turn a platform error into the sentence the user should read.
 *
 * `AbortError` is deliberately not translated: a cancelled request is the user's
 * own doing, and the store already leaves the previous response on screen for it.
 */
const describe = (thrown: unknown): ApiClientError => {
  if (thrown instanceof ApiError) {
    const known = FAILURES[thrown.code]
    if (known !== undefined) return known

    // A 5xx from the platform itself, with no code of ours: the proxy is up but
    // could not do its job.  There is nothing useful to add to the sentence, and
    // nothing internal is repeated.
    return NETWORK_FAILURE
  }

  if (thrown instanceof DOMException && thrown.name === 'TimeoutError') {
    return TIMEOUT_FAILURE
  }

  // fetch itself rejecting: DNS, TLS, offline, a CORS refusal.  Not the target's
  // answer, and emphatically not a mock response.
  return NETWORK_FAILURE
}

/**
 * The request as the backend's schema wants it.
 *
 * A straight projection — the store has already resolved variables and folded
 * auth into headers, and nothing here re-derives any of that.  The list is copied
 * rather than re-shaped because `ApiHeaderPair` is already `{ name, value }`,
 * which is what the wire format declares.
 */
const toWireRequest = (request: ResolvedApiRequest): ProxyWireRequest => ({
  method: request.method,
  url: request.url,
  headers: request.headers.map((header) => ({
    name: header.name,
    value: header.value,
  })),
  body: request.body,
  timeoutMs: request.timeoutMs,
})

/**
 * The envelope as the client's `ApiResponse`.
 *
 * Two things are worth reading twice.
 *
 * **`sizeBytes` comes from the backend, not from the string.** Measuring the
 * decoded body would report a 40 KB PNG as zero bytes, because a binary body
 * arrives as an empty string by design.  The proxy counted the bytes it actually
 * received, and that count is the honest one to show.
 *
 * **A binary or truncated body says so, in the response headers.** The panel
 * renders headers verbatim, so a synthetic entry is visible where the user is
 * already looking and cannot be mistaken for something the target sent — both
 * names are prefixed `X-Proxy-`, which the proxy's own forwarded headers never
 * are (it drops nothing silently, but it also never invents that prefix).
 * Without it, "the body is empty" and "the body was never text" would look
 * identical, and a silent empty pane is the failure mode the backend's
 * `bodyEncoding` field exists to prevent.
 */
const toApiResponse = (wire: ProxyWireResponse): ApiResponse => {
  const headers: ApiHeaderPair[] = [...wire.headers]

  if (wire.bodyEncoding !== 'utf-8') {
    headers.push({
      name: 'X-Proxy-Body-Encoding',
      value: wire.bodyEncoding,
    })
    headers.push({
      name: 'X-Proxy-Body-Note',
      value: `body is ${wire.bodyEncoding}; ${wire.sizeBytes} bytes received and not decoded`,
    })
  }

  if (wire.bodyTruncated) {
    headers.push({
      name: 'X-Proxy-Body-Truncated',
      value: 'true',
    })
  }

  return {
    status: wire.status,
    statusText: wire.statusText,
    headers,
    cookies: wire.cookies,
    body: wire.body,
    contentType: wire.contentType,
    timeMs: wire.timeMs,
    sizeBytes: wire.sizeBytes,
    receivedAt: new Date().toISOString(),
  }
}

/**
 * The transport the console uses outside tests.
 *
 * `projectId` is an argument, not a field: see `ProxyTransportOptions`.
 */
export const createProxyTransport = (): ApiTransport => ({
  kind: 'proxy',

  async send({ request: outgoing, projectId, signal }): Promise<ApiResponse> {
    if (projectId === '') {
      // Belt and braces: the store refuses before it gets here, and a request
      // addressed to no project would 404 against the platform anyway.  Refusing
      // locally keeps the failure legible instead of turning it into a 404 the
      // user would read as "my project is gone".
      throw new ProxyTransportError({
        kind: 'transport',
        messageKey: 'console.apiClient.error.projectNotReady',
      })
    }

    let wire: ProxyWireResponse

    try {
      wire = await request<ProxyWireResponse>(
        `/api/projects/${encodeURIComponent(projectId)}/proxy`,
        {
          method: 'POST',
          body: toWireRequest(outgoing),
          signal,
        },
      )
    } catch (thrown) {
      if (isAbort(thrown)) throw thrown
      throw new ProxyTransportError(describe(thrown))
    }

    return toApiResponse(wire)
  },
})

const isAbort = (thrown: unknown): boolean =>
  thrown instanceof DOMException && thrown.name === 'AbortError'
