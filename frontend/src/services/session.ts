/**
 * The guest session: where this console's identity comes from.
 *
 * The backend verifies a guest by an opaque token in the ``X-Guest-Session`` header
 * and stores only its SHA-256 digest. This module owns the browser's half of that
 * bargain: obtain a token once, keep it for the tab and across reloads, hand it to
 * every request that goes to *this* product's backend, and give it up when the
 * server says it is no longer valid.
 *
 * Four decisions worth stating plainly.
 *
 * **It does not go through the shared HTTP layer.** ``request()`` attaches a session
 * to every call, so issuing one through it would need a session to get a session.
 * The two calls here use ``fetch`` directly, and nothing in this module imports a
 * request helper that could recurse.
 *
 * **One issuance at a time.** A page that loads five views at once would otherwise
 * mint five sessions, leave four of them orphaned in the database and race to see
 * which token ends up in storage. ``ensureSession()`` shares one in-flight promise.
 *
 * **localStorage, and what that means.** The token has to survive a reload, so it
 * lives in ``aiata.guestSession.token``. localStorage is readable by any script on
 * this origin, so this is *not* HttpOnly-grade protection: an XSS on this origin
 * can read the token, exactly as it could read anything else the console holds.
 * What the token is worth is bounded by what a guest owns -- it is not a user
 * account, and the server never returns it again after issuing it.
 *
 * **Nothing here is logged, and nothing here is put in a URL.** The token travels
 * in a header on the requests below and nowhere else; a query string would end up
 * in a server log, a browser history entry and a Referer header.
 *
 * The token is only ever sent to this product's own backend. ``services/transport.ts``
 * sends requests to the API a *user* asked us to test, and that traffic carries
 * that API's own credentials -- never this one.
 */

import { apiBaseUrl } from '@/services/http'

/** The header the backend reads. One spelling, one place. */
export const SESSION_HEADER = 'X-Guest-Session'

/** Where the token lives between reloads. */
export const SESSION_STORAGE_KEY = 'aiata.guestSession.token'

const ISSUE_PATH = '/api/guest-sessions'
const CURRENT_PATH = '/api/guest-sessions/current'

let cached: string | null = null
let inFlight: Promise<string> | null = null

const storage = (): Storage | null => {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    // A browser with storage disabled answers by throwing on access.
    return null
  }
}

/** The token this tab holds, or null. Reads storage once, then remembers. */
export const readToken = (): string | null => {
  if (cached !== null) return cached

  const store = storage()
  if (store === null) return null

  try {
    cached = store.getItem(SESSION_STORAGE_KEY)
  } catch {
    cached = null
  }

  return cached
}

/** Forget the token: memory, storage and the pending issuance. */
export const clearToken = (): void => {
  cached = null

  const store = storage()
  if (store === null) return

  try {
    store.removeItem(SESSION_STORAGE_KEY)
  } catch {
    // Nothing to do: the in-memory copy is already gone, which is what matters
    // for the rest of this page's life.
  }
}

const writeToken = (token: string): void => {
  cached = token

  const store = storage()
  if (store === null) return

  try {
    store.setItem(SESSION_STORAGE_KEY, token)
  } catch {
    // Quota or a locked-down profile: the session still works for this page.
  }
}

export class SessionError extends Error {
  readonly code: string

  constructor(code: string) {
    super(code)
    this.name = 'SessionError'
    this.code = code
  }
}

const issue = async (): Promise<string> => {
  let response: Response

  try {
    response = await fetch(apiBaseUrl() + ISSUE_PATH, { method: 'POST' })
  } catch {
    throw new SessionError('guest-session-unreachable')
  }

  if (!response.ok) {
    throw new SessionError('guest-session-unavailable')
  }

  let body: unknown

  try {
    body = await response.json()
  } catch {
    throw new SessionError('guest-session-invalid-response')
  }

  const token = (body as { sessionToken?: unknown } | null)?.sessionToken

  if (typeof token !== 'string' || token === '') {
    throw new SessionError('guest-session-invalid-response')
  }

  writeToken(token)

  return token
}

/**
 * The token to use, issuing one if this tab has none yet.
 *
 * Concurrent callers share a single issuance: the first call starts it, the rest
 * await the same promise. A rejected issuance is not cached -- the next caller
 * tries again rather than inheriting a failure that may have been a dropped
 * connection.
 */
export const ensureSession = (): Promise<string> => {
  const existing = readToken()
  if (existing !== null) return Promise.resolve(existing)

  if (inFlight !== null) return inFlight

  inFlight = issue().finally(() => {
    inFlight = null
  })

  return inFlight
}

/**
 * Replace a token the server has just refused.
 *
 * Called once per failed request, never in a loop: the caller retries the request
 * it was making, and a second 401 surfaces to the page instead of starting over.
 */
export const recoverSession = async (): Promise<string> => {
  clearToken()

  return await ensureSession()
}

/**
 * End this session, server-side and locally.
 *
 * Deliberately not retried: if the token is already invalid, the local copy is
 * still cleared and the call is done. Issuing a replacement here would turn
 * "sign out" into "sign in again, then sign that out", which is the loop this
 * function exists to avoid.
 */
export const revokeSession = async (): Promise<void> => {
  const token = readToken()

  if (token === null) return

  try {
    await fetch(apiBaseUrl() + CURRENT_PATH, {
      method: 'DELETE',
      headers: { [SESSION_HEADER]: token },
    })
  } finally {
    clearToken()
  }
}

/** For tests: forget both the token and any in-flight issuance. */
export const resetSessionForTests = (): void => {
  clearToken()
  inFlight = null
}
