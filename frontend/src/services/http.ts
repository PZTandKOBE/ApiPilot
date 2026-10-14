/**
 * The one place the console talks HTTP to FastAPI.
 *
 * There is no HTTP client in this repository yet. The API Client sends its
 * requests through `services/transport.ts` -- mocked today, proxied later, and
 * deliberately a different seam because a hand-made request is not a REST call
 * to this service -- and the agent still runs entirely in the browser. So this
 * module exists rather than a second one being invented per feature: the run
 * endpoints are the first thing here that has a real server behind it.
 *
 * Two decisions are worth knowing about.
 *
 * **The base URL is configuration with a default.** `VITE_API_BASE_URL` wins
 * when it is set; otherwise the service assumes uvicorn's default port on the
 * loopback interface, which is where `uv run backend` puts it and one of the two
 * origins the backend's CORS list already allows. Nothing here is a hard-coded
 * production address: a deployment sets the variable.
 *
 * **Errors arrive as the envelope the backend sends.** `{ code, messageKey,
 * params }` is what every non-2xx response carries; this module turns it into an
 * `ApiError` and leaves the question of which sentence a caller should fall back
 * to where it belongs -- with the caller, because only the caller knows which
 * operation failed.
 */

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

/**
 * Where the API is.
 *
 * Trailing slashes are trimmed rather than tolerated: every path in this code
 * starts with one, and a base URL ending in one would ask for `//api/...` --
 * which most servers accept and some proxies mangle.
 */
export const apiBaseUrl = (): string => {
  const configured: unknown = import.meta.env.VITE_API_BASE_URL
  const raw =
    typeof configured === 'string' && configured.trim() !== ''
      ? configured.trim()
      : DEFAULT_BASE_URL

  return raw.endsWith('/') ? raw.slice(0, -1) : raw
}

// The identity this product's own backend requires. The import is circular on
// purpose and safe: `session.ts` calls `apiBaseUrl` and this module calls the
// session helpers, both from inside functions, so neither evaluates the other
// while the modules are loading.
import { SESSION_HEADER, ensureSession, recoverSession } from '@/services/session'

export interface ApiErrorInit {
  readonly status: number
  readonly code: string
  readonly messageKey: string
  readonly params?: Readonly<Record<string, string | number>>
  readonly details?: unknown
}

/** A non-2xx answer, with the backend's envelope unpacked.
 *
 * `messageKey` may be empty when the response was not one of ours -- a proxy's
 * error page, a connection reset -- and the caller supplies the sentence it
 * knows is right for the operation it attempted.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly messageKey: string
  readonly params?: Readonly<Record<string, string | number>>
  readonly details?: unknown

  constructor(init: ApiErrorInit) {
    super(init.status + ' ' + init.code)
    this.name = 'ApiError'
    this.status = init.status
    this.code = init.code
    this.messageKey = init.messageKey
    this.params = init.params
    this.details = init.details
  }
}

export interface RequestOptions {
  readonly method?: 'GET' | 'POST'
  /** Sent as JSON. `undefined` sends no body and no content type. */
  readonly body?: unknown
  readonly signal?: AbortSignal
}

const errorFrom = async (response: Response): Promise<ApiError> => {
  let body: unknown = null

  try {
    body = await response.json()
  } catch {
    body = null
  }

  const envelope = (
    typeof body === 'object' && body !== null ? body : {}
  ) as Record<string, unknown>

  const params = envelope.params

  return new ApiError({
    status: response.status,
    code: typeof envelope.code === 'string' ? envelope.code : 'http-error',
    messageKey: typeof envelope.messageKey === 'string' ? envelope.messageKey : '',
    params:
      typeof params === 'object' && params !== null
        ? (params as Record<string, string | number>)
        : undefined,
    details: envelope.details,
  })
}

/**
 * One request, one response, and at most one retry.
 *
 * A rejected promise is either an `ApiError` -- the server answered, and said
 * why -- or whatever `fetch` threw, which is a network failure and is the
 * caller's to describe. Keeping those two apart is what lets a run page say
 * "no run with that id" for the first and "the run could not be loaded" for the
 * second.
 *
 * **Every call carries the guest session.** The token is attached here, in the one
 * function every backend call goes through, so a new call site cannot forget it.
 * The session itself is obtained through `services/session.ts`, which uses its own
 * `fetch`: a request that needed a session to get a session would not terminate.
 *
 * **A 401 is retried once, and only once.** The token is cleared, a replacement is
 * issued, and the same request is sent again -- which is the whole recovery story
 * for a session that expired while a tab sat open. If the second attempt is
 * refused too, the `ApiError` reaches the caller unchanged: no loop, and no
 * silent fallback to an unauthenticated request, because a page that quietly
 * showed less would be lying about what the server said.
 *
 * **The retry cannot duplicate a write.** The server checks identity before it
 * touches anything, so the refused attempt created nothing to duplicate.
 */
export const request = async <T>(path: string, options: RequestOptions = {}): Promise<T> => {
  const send = async (token: string | null): Promise<Response> => {
    const hasBody = options.body !== undefined
    const headers: Record<string, string> = {}

    if (hasBody) headers['Content-Type'] = 'application/json'
    if (token !== null) headers[SESSION_HEADER] = token

    return await fetch(apiBaseUrl() + path, {
      method: options.method ?? 'GET',
      headers,
      body: hasBody ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    })
  }

  const token = await ensureSession().catch(() => null)
  let response = await send(token)

  if (response.status === 401) {
    const replacement = await recoverSession().catch(() => null)

    if (replacement !== null) {
      response = await send(replacement)
    }
  }

  if (!response.ok) {
    throw await errorFrom(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
