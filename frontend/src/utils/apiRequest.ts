/**
 * Draft → wire-format resolution.
 *
 * A pure function of (draft, variables, base URL). Keeping it out of the store
 * means the store orchestrates while this stays trivially inspectable — and
 * the same function is what a future "preview the outgoing request" panel
 * would call.
 */

import type {
  ApiAuth,
  ApiHeaderPair,
  ApiRequestDraft,
  ResolvedApiRequest,
} from '@/types/api'
import { resolveTemplate } from './variables'

/** How long a request may hang before it is reported as a timeout. */
export const DEFAULT_TIMEOUT_MS = 30_000

/** Why a draft could not be turned into a sendable request. */
export type ResolutionFailureReason =
  | 'unresolved-variables'
  | 'missing-base-url'

export type ResolutionOutcome =
  | { readonly ok: true; readonly request: ResolvedApiRequest }
  | {
      readonly ok: false
      readonly reason: 'unresolved-variables'
      readonly names: readonly string[]
    }
  | { readonly ok: false; readonly reason: 'missing-base-url' }

/**
 * `btoa` takes a binary string, so the text is encoded to UTF-8 bytes first —
 * otherwise a non-ASCII password throws instead of producing a credential.
 */
const toBase64 = (text: string): string => {
  const bytes = new TextEncoder().encode(text)
  let binary = ''

  for (const byte of bytes) binary += String.fromCharCode(byte)

  return btoa(binary)
}

export interface AuthContribution {
  readonly headers: readonly ApiHeaderPair[]
  readonly query: readonly ApiHeaderPair[]
}

/**
 * Fold the auth configuration into concrete headers / query params.
 *
 * Empty credentials contribute nothing rather than producing a header with a
 * blank value — a request with `Authorization: Bearer ` is rejected by the
 * far end in a way that is hard to read back to the auth form.
 *
 * Exported because the auth editor shows the same result as a preview: the
 * user should see what their configuration turns into *before* sending, and a
 * second implementation of this mapping would eventually disagree with it.
 */
export const describeAuthContribution = (auth: ApiAuth): AuthContribution => {
  const none: AuthContribution = { headers: [], query: [] }

  switch (auth.type) {
    case 'none':
      return none

    case 'bearer':
      return auth.bearerToken.trim() === ''
        ? none
        : {
            headers: [
              { name: 'Authorization', value: `Bearer ${auth.bearerToken}` },
            ],
            query: [],
          }

    case 'basic':
      return auth.username.trim() === '' && auth.password === ''
        ? none
        : {
            headers: [
              {
                name: 'Authorization',
                value: `Basic ${toBase64(`${auth.username}:${auth.password}`)}`,
              },
            ],
            query: [],
          }

    case 'apiKey': {
      const name = auth.apiKeyName.trim()
      if (name === '' || auth.apiKeyValue === '') return none

      const pair: ApiHeaderPair = { name, value: auth.apiKeyValue }
      return auth.apiKeyIn === 'query'
        ? { headers: [], query: [pair] }
        : { headers: [pair], query: [] }
    }
  }
}

const toAbsoluteUrl = (url: string, baseUrl: string): string | null => {
  if (/^https?:\/\//i.test(url)) return url

  const base = baseUrl.trim().replace(/\/+$/, '')
  if (base === '') return null

  return url.startsWith('/') ? `${base}${url}` : `${base}/${url}`
}

/**
 * Append query pairs to an absolute URL.
 *
 * Falls back to string concatenation when `URL` rejects the input: the user
 * may be mid-typing a malformed URL, and the request should still go out with
 * the query visible rather than the whole send being blocked by a parse error.
 */
const appendQuery = (
  url: string,
  pairs: readonly ApiHeaderPair[],
): string => {
  if (pairs.length === 0) return url

  try {
    const parsed = new URL(url)
    for (const pair of pairs) parsed.searchParams.append(pair.name, pair.value)
    return parsed.toString()
  } catch {
    const separator = url.includes('?') ? '&' : '?'
    const query = pairs
      .map(
        (pair) =>
          `${encodeURIComponent(pair.name)}=${encodeURIComponent(pair.value)}`,
      )
      .join('&')

    return `${url}${separator}${query}`
  }
}

export const resolveDraft = (
  draft: ApiRequestDraft,
  variables: Readonly<Record<string, string>>,
  baseUrl: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): ResolutionOutcome => {
  const missing = new Set<string>()

  const substitute = (text: string): string => {
    const outcome = resolveTemplate(text, variables)
    for (const name of outcome.missing) missing.add(name)
    return outcome.value
  }

  // Everything templated is substituted before the missing check, so the error
  // can list *all* undefined names at once instead of one per attempt.
  const url = substitute(draft.url.trim())

  const params: ApiHeaderPair[] = draft.params
    .filter((row) => row.enabled && row.key.trim() !== '')
    .map((row) => ({ name: substitute(row.key), value: substitute(row.value) }))

  const headers: ApiHeaderPair[] = draft.headers
    .filter((row) => row.enabled && row.key.trim() !== '')
    .map((row) => ({ name: substitute(row.key), value: substitute(row.value) }))

  const auth = describeAuthContribution({
    ...draft.auth,
    bearerToken: substitute(draft.auth.bearerToken),
    username: substitute(draft.auth.username),
    password: substitute(draft.auth.password),
    apiKeyName: substitute(draft.auth.apiKeyName),
    apiKeyValue: substitute(draft.auth.apiKeyValue),
  })

  const body = draft.body.mode === 'none' ? null : substitute(draft.body.text)

  if (missing.size > 0) {
    return { ok: false, reason: 'unresolved-variables', names: [...missing] }
  }

  const absolute = toAbsoluteUrl(url, baseUrl)
  if (absolute === null) return { ok: false, reason: 'missing-base-url' }

  // An explicit header always wins over one derived from the auth form: the
  // user typed it, and overriding their input would be surprising.
  const explicit = new Set(headers.map((pair) => pair.name.toLowerCase()))
  const finalHeaders = [
    ...headers,
    ...auth.headers.filter((pair) => !explicit.has(pair.name.toLowerCase())),
  ]

  return {
    ok: true,
    request: {
      method: draft.method,
      url: appendQuery(absolute, [...params, ...auth.query]),
      headers: finalHeaders,
      body,
      timeoutMs,
    },
  }
}
