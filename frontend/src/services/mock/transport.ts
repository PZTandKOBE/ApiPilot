/**
 * Mock transport.
 *
 * The default transport while no backend exists. It is a real transport, not a
 * placeholder: it parses the outgoing request, routes on method and path,
 * validates bodies, and returns a response with headers, timing and size — so
 * the whole Request → resolve → Transport → Response data flow is exercised
 * for real, and swapping in the proxy changes only which implementation the
 * store is handed.
 */

import type { ApiHeaderPair, ApiResponse, HttpMethod, ResolvedApiRequest } from '@/types/api'
import { byteLength } from '@/utils/format'
import { statusText } from '@/utils/http'
import {
  MOCK_ROUTES,
  jsonReply,
  unmatchedReply,
  type MockReply,
  type MockRequestContext,
  type MockRoute,
} from './responses'
import type { ApiTransport, TransportSendInput } from '../transport'

/**
 * Stable non-cryptographic hash, used for latency and request ids.
 *
 * Deterministic on purpose: a request that felt slow yesterday should feel
 * slow today, so a UI problem seen once can be reproduced.
 */
const hash = (text: string): number => {
  let value = 0

  for (let index = 0; index < text.length; index += 1) {
    value = (value * 31 + text.charCodeAt(index)) | 0
  }

  return Math.abs(value)
}

/** 70–270 ms, derived from the request so different calls differ. */
const latencyFor = (request: ResolvedApiRequest): number =>
  70 + (hash(`${request.method} ${request.url}`) % 200)

const abortError = (): DOMException =>
  new DOMException('The request was aborted', 'AbortError')

/** Resolves after `millis`, or rejects as soon as the signal fires. */
const delay = (millis: number, signal?: AbortSignal): Promise<void> =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, millis)

    function onAbort(): void {
      clearTimeout(timer)
      reject(abortError())
    }

    if (signal?.aborted === true) {
      onAbort()
      return
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })

/** Matches `/api/orders/:orderId` against a concrete path. */
const matchPattern = (
  pattern: string,
  path: string,
): Readonly<Record<string, string>> | null => {
  const patternSegments = pattern.split('/').filter((segment) => segment !== '')
  const pathSegments = path.split('/').filter((segment) => segment !== '')

  if (patternSegments.length !== pathSegments.length) return null

  const params: Record<string, string> = {}

  for (let index = 0; index < patternSegments.length; index += 1) {
    const expected = patternSegments[index]
    const actual = pathSegments[index]

    if (expected === undefined || actual === undefined) return null

    if (expected.startsWith(':')) {
      params[expected.slice(1)] = decodeURIComponent(actual)
      continue
    }

    if (expected !== actual) return null
  }

  return params
}

interface MatchedRoute {
  readonly route: MockRoute
  readonly params: Readonly<Record<string, string>>
}

const matchRoute = (method: HttpMethod, path: string): MatchedRoute | null => {
  for (const route of MOCK_ROUTES) {
    if (route.method !== method) continue

    const params = matchPattern(route.pattern, path)
    if (params !== null) return { route, params }
  }

  return null
}

const toRequestContext = (
  request: ResolvedApiRequest,
  url: URL,
  pathParams: Readonly<Record<string, string>>,
): MockRequestContext => {
  const query: Record<string, string> = {}
  for (const [key, value] of url.searchParams.entries()) query[key] = value

  const headers: Record<string, string> = {}
  for (const header of request.headers) {
    headers[header.name.toLowerCase()] = header.value
  }

  return {
    path: url.pathname,
    pathParams,
    query,
    headers,
    body: request.body,
  }
}

const buildReply = (request: ResolvedApiRequest): MockReply => {
  let url: URL

  try {
    url = new URL(request.url)
  } catch {
    return jsonReply(400, {
      error: 'invalid_url',
      message: `The URL "${request.url}" could not be parsed.`,
    })
  }

  const matched = matchRoute(request.method, url.pathname)
  if (matched === null) return unmatchedReply(request.method, url.pathname)

  return matched.route.respond(toRequestContext(request, url, matched.params))
}

export const createMockTransport = (): ApiTransport => ({
  kind: 'mock',

  async send({ request, signal }: TransportSendInput): Promise<ApiResponse> {
    const startedAt = performance.now()

    await delay(latencyFor(request), signal)

    const reply = buildReply(request)
    const body = reply.body
    const contentType =
      reply.contentType ?? (body === '' ? '' : 'text/plain; charset=utf-8')

    const headers: ApiHeaderPair[] = [
      ...(contentType === '' ? [] : [{ name: 'Content-Type', value: contentType }]),
      { name: 'X-Request-Id', value: `req_${hash(request.url).toString(36)}` },
      // Unmissable in the response headers tab: nothing here touched a network.
      { name: 'X-Mock-Transport', value: 'true' },
      ...(reply.headers ?? []),
    ]

    return {
      status: reply.status,
      statusText: statusText(reply.status),
      headers,
      cookies: reply.cookies ?? [],
      body,
      contentType,
      timeMs: Math.round(performance.now() - startedAt),
      sizeBytes: byteLength(body),
      receivedAt: new Date().toISOString(),
    }
  },
})
