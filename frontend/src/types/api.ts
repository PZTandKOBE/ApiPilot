/**
 * API Client domain types.
 *
 * These describe what a user *composes* and what a transport *returns*, and
 * nothing about how either is stored or rendered. The same shapes are what a
 * FastAPI proxy will speak, so swapping `MockTransport` for `ProxyTransport`
 * is a service-layer change with no type churn.
 *
 * Unions are built from `as const` arrays rather than `enum`: the array is
 * usable at runtime (validation, `<select>` options) while the union keeps
 * `switch` exhaustiveness.
 */

/* ------------------------------------------------------------------ *
 * HTTP
 * ------------------------------------------------------------------ */

export const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

export type HttpMethod = (typeof HTTP_METHODS)[number]

export const isHttpMethod = (value: unknown): value is HttpMethod =>
  typeof value === 'string' &&
  (HTTP_METHODS as readonly string[]).includes(value)

/* ------------------------------------------------------------------ *
 * Request
 * ------------------------------------------------------------------ */

/**
 * One editable row in the params / headers editors.
 *
 * Rows carry their own `id` because they are keyed by identity, not by name:
 * a user must be able to have two rows with the same (or an empty) key while
 * typing, without the list re-mounting under them.
 */
export interface ApiKeyValue {
  readonly id: string
  readonly enabled: boolean
  readonly key: string
  readonly value: string
  readonly description: string
}

export const API_AUTH_TYPES = ['none', 'bearer', 'basic', 'apiKey'] as const

export type ApiAuthType = (typeof API_AUTH_TYPES)[number]

export const API_KEY_LOCATIONS = ['header', 'query'] as const

export type ApiKeyLocation = (typeof API_KEY_LOCATIONS)[number]

/**
 * Auth configuration, stored flat.
 *
 * Deliberately not a discriminated union: the editor is a form, and typing a
 * bearer token then switching to Basic and back must not silently discard it.
 * `type` gates which fields are read — see `resolveDraft`.
 */
export interface ApiAuth {
  readonly type: ApiAuthType
  readonly bearerToken: string
  readonly username: string
  readonly password: string
  readonly apiKeyName: string
  readonly apiKeyValue: string
  readonly apiKeyIn: ApiKeyLocation
}

export const API_BODY_MODES = ['none', 'json', 'raw'] as const

export type ApiBodyMode = (typeof API_BODY_MODES)[number]

export interface ApiBody {
  readonly mode: ApiBodyMode
  /** Kept as text: invalid JSON must survive a round trip so the user can fix it. */
  readonly text: string
}

/**
 * The editable request — templates unresolved.
 *
 * This is what gets persisted and what history restores. Variable placeholders
 * (`{{token}}`) stay in it verbatim.
 */
export interface ApiRequestDraft {
  readonly method: HttpMethod
  readonly url: string
  readonly params: readonly ApiKeyValue[]
  readonly headers: readonly ApiKeyValue[]
  readonly auth: ApiAuth
  readonly body: ApiBody
}

/* ------------------------------------------------------------------ *
 * Resolution
 * ------------------------------------------------------------------ */

/** A concrete header name/value pair, sent or received. */
export interface ApiHeaderPair {
  readonly name: string
  readonly value: string
}

/**
 * A request with every `{{variable}}` substituted and auth folded into headers
 * or query params. This is what a transport is handed.
 */
export interface ResolvedApiRequest {
  readonly method: HttpMethod
  readonly url: string
  readonly headers: readonly ApiHeaderPair[]
  readonly body: string | null
  readonly timeoutMs: number
}

/* ------------------------------------------------------------------ *
 * Response
 * ------------------------------------------------------------------ */

export interface ApiResponseCookie {
  readonly name: string
  readonly value: string
  readonly domain: string
  readonly path: string
  readonly httpOnly: boolean
  readonly secure: boolean
  readonly expires: string
}

/**
 * A completed round trip.
 *
 * A 404 or a 500 is a *successful* response, not an error — that distinction
 * is what lets the response panel render them normally. Only transport-level
 * failures (see `ApiClientError`) take the error path.
 */
export interface ApiResponse {
  readonly status: number
  readonly statusText: string
  readonly headers: readonly ApiHeaderPair[]
  readonly cookies: readonly ApiResponseCookie[]
  readonly body: string
  readonly contentType: string
  readonly timeMs: number
  readonly sizeBytes: number
  readonly receivedAt: string
}

export const API_ERROR_KINDS = [
  'network',
  'timeout',
  'transport',
  'unresolved-variables',
  'missing-base-url',
] as const

export type ApiErrorKind = (typeof API_ERROR_KINDS)[number]

/**
 * Why a request never produced a response.
 *
 * Carries an i18n key rather than a sentence: the same error has to read
 * correctly in both locales, including after the user switches language
 * without re-sending.
 */
export interface ApiClientError {
  readonly kind: ApiErrorKind
  readonly messageKey: string
  readonly params?: Readonly<Record<string, string | number>>
  /** Variable names that could not be resolved, when `kind` says so. */
  readonly variables?: readonly string[]
}

/* ------------------------------------------------------------------ *
 * Saved work
 * ------------------------------------------------------------------ */

export interface ApiSavedRequest {
  readonly id: string
  readonly name: string
  readonly draft: ApiRequestDraft
  readonly savedAt: string
}

export interface ApiCollectionFolder {
  readonly id: string
  readonly name: string
  readonly requests: readonly ApiSavedRequest[]
}

/**
 * Two fixed levels — collection, folder, request — rather than an unbounded
 * tree. It covers how API collections are actually organised without making
 * persistence validation recursive.
 */
export interface ApiCollection {
  readonly id: string
  readonly projectId: string
  readonly name: string
  readonly folders: readonly ApiCollectionFolder[]
  /** Requests sitting directly in the collection, outside any folder. */
  readonly requests: readonly ApiSavedRequest[]
}

export interface ApiHistoryItem {
  readonly id: string
  readonly projectId: string
  readonly method: HttpMethod
  /** The *unresolved* URL, so restoring brings `{{variables}}` back. */
  readonly url: string
  readonly status: number
  readonly timeMs: number
  readonly sizeBytes: number
  readonly at: string
  readonly draft: ApiRequestDraft
}

/**
 * Handoff payload for the agent (see the "Generate Test" entry point).
 *
 * The API Client is manual testing and the AI Test Lab is agent testing; this
 * is the seam between them. It carries the resolved request so the agent has
 * something concrete to reason about, plus the draft so the lab can show the
 * user what it was given.
 */
export interface AgentHandoff {
  readonly projectId: string
  readonly draft: ApiRequestDraft
  readonly resolved: ResolvedApiRequest
  readonly requestedAt: string
}
