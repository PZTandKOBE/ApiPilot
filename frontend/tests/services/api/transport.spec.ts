import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createProxyTransport, ProxyTransportError } from '@/services/api/transport'
import { apiBaseUrl } from '@/services/http'
import { SESSION_HEADER, resetSessionForTests } from '@/services/session'
import { useLocaleStore } from '@/stores/locale'
import type { ResolvedApiRequest } from '@/types/api'

/**
 * The real transport: what it sends to the platform, and what it makes of the
 * answer.
 *
 * The *server* is a double — there is no backend running for this suite and there
 * must not be one — but nothing on this side of `fetch` is: the URL, the body, the
 * headers the shared HTTP layer attaches, and the mapping from the proxy's
 * envelope back to `ApiResponse` are the shipped code.  The distinction matters,
 * so every assertion below reads either the recorded platform request or the
 * returned `ApiResponse`, and never the double's own bookkeeping.
 *
 * What this file deliberately does not prove: that FastAPI answers, that the SSRF
 * policy refuses a private address, or that TLS is verified.  Those are the
 * backend's, and Task B9's review measures them against a real server.  What is
 * proved here is that the browser asks the *proxy* — and only the proxy — for them.
 */

const PROJECT_ID = 'prj_rt_17'

const baseUrl = apiBaseUrl()

/** One recorded call to the platform. */
interface PlatformCall {
  readonly url: string
  readonly method: string
  readonly headers: Readonly<Record<string, string>>
  readonly body: unknown
}

/**
 * The platform, as far as this suite is concerned: a recorder with answers.
 *
 * `sessionToken` stands in for the guest-session endpoint; `failures` stands in
 * for the proxy's error envelope.  Both are the published wire formats, so a stub
 * that drifted from them would fail these tests rather than pass them.
 */
class Platform {
  readonly calls: PlatformCall[] = []
  sessionToken: string | null = 'gs_test_token'
  /** What the proxy route answers: a body, or a status to fail with. */
  proxyReply: { readonly status: number; readonly body: unknown } = {
    status: 200,
    body: { status: 204, statusText: 'No Content', headers: [], cookies: [], body: '', contentType: '', bodyTruncated: false, bodyEncoding: 'utf-8', timeMs: 12, sizeBytes: 0 },
  }

  install(): void {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? 'GET').toUpperCase()
        const headers: Record<string, string> = {}

        for (const [name, value] of Object.entries(
          (init?.headers ?? {}) as Record<string, string>,
        )) {
          headers[name.toLowerCase()] = String(value)
        }

        this.calls.push({
          url,
          method,
          headers,
          body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
        })

        if (url.endsWith('/api/guest-sessions')) {
          if (this.sessionToken === null) return this.json(503, { code: 'no-sessions' })
          return this.json(201, { sessionToken: this.sessionToken })
        }

        if (url.includes('/proxy')) {
          return this.json(this.proxyReply.status, this.proxyReply.body)
        }

        throw new Error('unexpected platform call: ' + url)
      }),
    )
  }

  json(status: number, body: unknown): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: '',
      json: async () => body,
    } as unknown as Response
  }

  get last(): PlatformCall {
    const call = this.calls.at(-1)
    if (call === undefined) throw new Error('no platform call was made')

    return call
  }

  get proxyCalls(): readonly PlatformCall[] {
    return this.calls.filter((call) => call.url.includes('/proxy'))
  }

  /** The request body the proxy route received. */
  get proxyBody(): Record<string, any> {
    return this.last.body as Record<string, any>
  }
}

let platform: Platform

const outgoing = (
  patch: Partial<ResolvedApiRequest> = {},
): ResolvedApiRequest => ({
  method: 'POST',
  url: 'https://api.under-test.example/orders?page=2',
  headers: [
    { name: 'Content-Type', value: 'application/json' },
    { name: 'Authorization', value: 'Bearer target-token' },
  ],
  body: '{"product_id":"prod_001"}',
  timeoutMs: 12_000,
  ...patch,
})

const envelope = (patch: Record<string, unknown> = {}): Record<string, unknown> => ({
  status: 200,
  statusText: 'OK',
  headers: [{ name: 'Content-Type', value: 'application/json' }],
  cookies: [],
  body: '{"ok":true}',
  contentType: 'application/json',
  bodyTruncated: false,
  bodyEncoding: 'utf-8',
  timeMs: 37,
  sizeBytes: 11,
  ...patch,
})

const send = (patch: Partial<ResolvedApiRequest> = {}, projectId = PROJECT_ID) =>
  createProxyTransport().send({ request: outgoing(patch), projectId })

beforeEach(() => {
  // The locale store is a pinia store like any other, and the translation check
  // below reads it rather than a hand-copied dictionary.
  setActivePinia(createPinia())
  platform = new Platform()
  platform.install()
  // The session is cached in module state and would otherwise leak between tests.
  resetSessionForTests()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetSessionForTests()
})

describe('what the browser asks the platform for', () => {
  it('posts to the project-scoped proxy route', async () => {
    await send()

    expect(platform.proxyCalls).toHaveLength(1)
    expect(platform.last.url).toBe(`${baseUrl}/api/projects/${PROJECT_ID}/proxy`)
    expect(platform.last.method).toBe('POST')
  })

  it('carries the project id in the platform path, never in the body', async () => {
    await send()

    expect(platform.last.url).toContain(`/api/projects/${PROJECT_ID}/`)

    // The body is the proxy's request schema and nothing else.  An ownership
    // field here would be a claim the backend must not accept, and the schema
    // forbids it -- so it must not be sent either.
    expect(Object.keys(platform.proxyBody).sort()).toEqual([
      'body',
      'headers',
      'method',
      'timeoutMs',
      'url',
    ])
    expect(JSON.stringify(platform.proxyBody)).not.toContain('projectId')
  })

  it('sends the request the store already resolved, unchanged', async () => {
    await send()

    expect(platform.proxyBody).toEqual({
      method: 'POST',
      url: 'https://api.under-test.example/orders?page=2',
      headers: [
        { name: 'Content-Type', value: 'application/json' },
        { name: 'Authorization', value: 'Bearer target-token' },
      ],
      body: '{"product_id":"prod_001"}',
      timeoutMs: 12_000,
    })
  })

  it('passes the timeout the client resolved, without inventing one', async () => {
    await send({ timeoutMs: 4_500 })

    expect(platform.proxyBody.timeoutMs).toBe(4_500)

    // And a client that resolved a different value gets that value: the transport
    // is a projection, not a second place where a default is decided.  The
    // backend's own default applies only when the field is absent, which the
    // store's resolver never produces -- it always resolves one.
    await send({ timeoutMs: 30_000 })

    expect(platform.proxyBody.timeoutMs).toBe(30_000)
  })

  it('lets the shared HTTP layer attach the guest session, and only there', async () => {
    await send()

    // Attached by `services/http.ts`; the transport never sees the token.
    expect(platform.calls.map((call) => call.url)).toContain(
      `${baseUrl}/api/guest-sessions`,
    )
    expect(platform.last.headers[SESSION_HEADER.toLowerCase()]).toBe('gs_test_token')
  })

  it('never puts the guest session into the headers sent upstream', async () => {
    await send()

    const upstream = platform.proxyBody.headers as readonly {
      readonly name: string
      readonly value: string
    }[]

    expect(
      upstream.filter(
        (header) => header.name.toLowerCase() === SESSION_HEADER.toLowerCase(),
      ),
    ).toEqual([])
    expect(JSON.stringify(upstream)).not.toContain('gs_test_token')
  })

  it('forwards the target Authorization the user configured', async () => {
    await send()

    const upstream = platform.proxyBody.headers as readonly {
      readonly name: string
      readonly value: string
    }[]

    expect(upstream).toContainEqual({
      name: 'Authorization',
      value: 'Bearer target-token',
    })
  })

  it('never fetches the target URL itself', async () => {
    await send()

    // The whole point of the proxy: the browser's only network call is to this
    // product's own backend.
    for (const call of platform.calls) {
      expect(call.url.startsWith(baseUrl)).toBe(true)
    }
    expect(platform.calls.some((call) => call.url.includes('under-test.example'))).toBe(
      false,
    )
  })

  it('passes the abort signal through to the platform call', async () => {
    // Recorded on the stub itself, because `Platform` deliberately keeps only the
    // parts of a call the assertions above are about.
    const signals: (AbortSignal | undefined)[] = []
    const inner = globalThis.fetch as unknown as (
      input: unknown,
      init?: RequestInit,
    ) => Promise<Response>

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: RequestInit) => {
        if (String(input).includes('/proxy')) signals.push(init?.signal ?? undefined)
        return await inner(input, init)
      }),
    )

    const controller = new AbortController()
    const promise = createProxyTransport().send({
      request: outgoing(),
      projectId: PROJECT_ID,
      signal: controller.signal,
    })

    controller.abort()
    await promise

    // The signal reaches fetch rather than being dropped, which is what would make
    // Cancel stop working on this transport.  `Platform` ignores it, so the call
    // resolves and the assertion is about the wiring, not about aborting.
    expect(signals).toEqual([controller.signal])
  })
})

describe('what the platform answers', () => {
  it('keeps an upstream 200, its headers and its metadata', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({
        headers: [
          { name: 'Content-Type', value: 'application/json' },
          { name: 'X-Custom', value: 'kept' },
        ],
      }),
    }

    const response = await send()

    expect(response.status).toBe(200)
    expect(response.statusText).toBe('OK')
    expect(response.headers).toEqual([
      { name: 'Content-Type', value: 'application/json' },
      { name: 'X-Custom', value: 'kept' },
    ])
    expect(response.body).toBe('{"ok":true}')
    expect(response.contentType).toBe('application/json')
    expect(response.timeMs).toBe(37)
    expect(response.sizeBytes).toBe(11)
    expect(Number.isNaN(Date.parse(response.receivedAt))).toBe(false)
  })

  it('keeps an upstream 404 as a response, not as a failure', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({
        status: 404,
        statusText: 'Not Found',
        body: '{"error":"no such order"}',
      }),
    }

    const response = await send()

    expect(response.status).toBe(404)
    expect(response.statusText).toBe('Not Found')
    expect(response.body).toBe('{"error":"no such order"}')
  })

  it('keeps an upstream 500 as a response too', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({ status: 500, statusText: 'Internal Server Error', body: 'boom' }),
    }

    expect((await send()).status).toBe(500)
  })

  it('tells an upstream 404 apart from the platform 404 for a missing project', async () => {
    // The target answered 404: a result about the request.
    platform.proxyReply = { status: 200, body: envelope({ status: 404 }) }
    expect((await send()).status).toBe(404)

    // The platform answered 404: the project is not this guest's, so the call was
    // never forwarded.  Same number, entirely different meaning -- and it must not
    // reach the response panel as if the target had spoken.
    platform.proxyReply = {
      status: 404,
      body: { code: 'project-not-found', messageKey: 'console.runs.errors.notFound' },
    }

    await expect(send()).rejects.toBeInstanceOf(ProxyTransportError)
  })

  it('carries cookies and an empty body through', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({
        body: '',
        sizeBytes: 0,
        cookies: [
          {
            name: 'sid',
            value: 'abc',
            domain: '',
            path: '/',
            httpOnly: true,
            secure: true,
            expires: '',
          },
        ],
      }),
    }

    const response = await send()

    expect(response.body).toBe('')
    expect(response.cookies).toHaveLength(1)
    expect(response.cookies[0]?.name).toBe('sid')
  })

  it('passes a plain-text body through as it arrived', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({
        body: 'created',
        contentType: 'text/plain; charset=utf-8',
        sizeBytes: 7,
        headers: [{ name: 'Content-Type', value: 'text/plain; charset=utf-8' }],
      }),
    }

    const response = await send()

    // Not parsed, not re-encoded, not decorated: the panel shows what the target
    // said, and a body that is not JSON is not an error.
    expect(response.body).toBe('created')
    expect(response.contentType).toBe('text/plain; charset=utf-8')
    expect(response.sizeBytes).toBe(7)
  })

  it('carries an empty body as an empty body, with no invented explanation', async () => {
    // A bodyless answer is a legitimate one.  The proxy reports it as an empty
    // string with the size it measured, and nothing is added to the headers to
    // "explain" it -- unlike the binary case, where emptiness and never-decoded
    // are genuinely indistinguishable.
    platform.proxyReply = {
      status: 200,
      body: envelope({
        status: 200,
        body: '',
        sizeBytes: 0,
        contentType: '',
        headers: [{ name: 'Content-Length', value: '0' }],
      }),
    }

    const response = await send({ method: 'GET', body: null })

    expect(response.body).toBe('')
    expect(response.sizeBytes).toBe(0)
    expect(response.contentType).toBe('')
    expect(response.headers).toEqual([{ name: 'Content-Length', value: '0' }])
    expect(platform.proxyBody.method).toBe('GET')
  })

  it('only ever sends a method the proxy schema declares', async () => {
    // The wire method is the frontend's own union, so a method the backend would
    // reject cannot be spelled here: `HEAD` and `OPTIONS` exist in HTTP and in the
    // proxy's schema, but the API Client does not offer them, and this transport
    // does not smuggle one in.
    for (const method of ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const) {
      await send({ method })
      expect(platform.proxyBody.method).toBe(method)
    }
  })

  it('carries a 204 with no body and no content type', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({ status: 204, statusText: 'No Content', body: '', contentType: '', sizeBytes: 0 }),
    }

    const response = await send({ method: 'DELETE', body: null })

    expect(response.status).toBe(204)
    expect(response.body).toBe('')
    expect(response.contentType).toBe('')
    expect(platform.proxyBody.body).toBeNull()
  })

  it('reports a binary body by its size instead of faking text', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({
        body: '',
        bodyEncoding: 'binary',
        sizeBytes: 40_960,
        contentType: 'image/png',
      }),
    }

    const response = await send()

    // The bytes are not invented, and the count is the one the proxy measured --
    // measuring the empty string here would report 0 for a 40 KB image.
    expect(response.body).toBe('')
    expect(response.sizeBytes).toBe(40_960)
    expect(response.contentType).toBe('image/png')
    expect(response.headers).toContainEqual({
      name: 'X-Proxy-Body-Encoding',
      value: 'binary',
    })
  })

  it('marks a truncated body as truncated', async () => {
    platform.proxyReply = {
      status: 200,
      body: envelope({ bodyTruncated: true, body: 'first part' }),
    }

    const response = await send()

    expect(response.body).toBe('first part')
    expect(response.headers).toContainEqual({
      name: 'X-Proxy-Body-Truncated',
      value: 'true',
    })
  })

  it('never writes the response to the console', async () => {
    const logged: unknown[] = []
    const original = console.log
    console.log = (...args: unknown[]) => void logged.push(args)

    try {
      platform.proxyReply = {
        status: 200,
        body: envelope({ body: '{"secret":"do-not-log-me"}' }),
      }
      await send()
    } finally {
      console.log = original
    }

    expect(platform.proxyCalls).toHaveLength(1)

    expect(JSON.stringify(logged)).not.toContain('do-not-log-me')
  })

  it('reports a proxy timeout as a timeout, not as a target response', async () => {
    platform.proxyReply = {
      status: 504,
      body: { code: 'proxy-timeout', messageKey: 'console.runs.errors.loadFailed' },
    }

    const failure = await send().catch((thrown: unknown) => thrown)

    expect(failure).toBeInstanceOf(ProxyTransportError)
    expect((failure as ProxyTransportError).clientError).toEqual({
      kind: 'timeout',
      messageKey: 'console.apiClient.error.timeout',
    })
  })

  it('reports a refused address as blocked', async () => {
    platform.proxyReply = {
      status: 400,
      body: { code: 'proxy-target-blocked', messageKey: 'console.apiClient.error.network' },
    }

    const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError

    expect(failure.clientError.kind).toBe('transport')
    expect(failure.clientError.messageKey).toBe('console.apiClient.error.blocked')
  })

  it('reports an unreachable target as unreachable', async () => {
    platform.proxyReply = {
      status: 502,
      body: { code: 'proxy-target-unreachable', messageKey: 'console.apiClient.error.network' },
    }

    const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError

    expect(failure.clientError.kind).toBe('network')
    expect(failure.clientError.messageKey).toBe('console.apiClient.error.unreachable')
  })

  it('reports a refused guest session rather than pretending to have sent', async () => {
    platform.proxyReply = {
      status: 401,
      body: { code: 'guest-session-required', messageKey: 'console.runs.errors.unauthorized' },
    }
    platform.sessionToken = 'gs_fresh_token'

    const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError

    expect(failure.clientError.messageKey).toBe('console.apiClient.error.unauthorized')
  })

  it('does not fall back to the mock when the platform is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown) => {
        await Promise.resolve()
        if (String(input).endsWith('/api/guest-sessions')) {
          return platform.json(201, { sessionToken: 'gs_offline_token' })
        }
        throw new TypeError('Failed to fetch')
      }),
    )

    const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError

    expect(failure).toBeInstanceOf(ProxyTransportError)
    expect(failure.clientError).toEqual({
      kind: 'network',
      messageKey: 'console.apiClient.error.network',
    })
  })

  it('refuses to send at all when it is handed no project', async () => {
    const failure = (await send({}, '').catch((thrown: unknown) => thrown)) as ProxyTransportError

    expect(failure).toBeInstanceOf(ProxyTransportError)
    expect(failure.clientError.messageKey).toBe('console.apiClient.error.projectNotReady')
    // Nothing was asked of the platform: the refusal happened before the call.
    expect(platform.proxyCalls).toEqual([])
  })

  it('reports every refusal with a sentence both locales actually have', async () => {
    // The keys below are data the transport emits, so the source scan in
    // `tests/i18n/keys.spec.ts` cannot see them.  A key with no translation renders
    // as the key itself -- `console.apiClient.error.blocked` on screen -- so each
    // one is resolved through the real dictionaries for both languages.
    const codes: readonly (readonly [string, number])[] = [
      ['proxy-timeout', 504],
      ['proxy-target-blocked', 400],
      ['proxy-target-unreachable', 502],
      ['proxy-invalid-request', 400],
      ['proxy-response-too-large', 502],
      ['proxy-upstream-failed', 502],
      ['guest-session-required', 401],
      ['project-not-found', 404],
    ]

    const locale = useLocaleStore()

    for (const [code, status] of codes) {
      platform.proxyReply = { status, body: { code, messageKey: '' } }

      const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError
      const key = failure.clientError.messageKey

      for (const language of ['en-US', 'zh-CN'] as const) {
        locale.setLocale(language)
        const sentence = locale.t(key)
        expect(sentence, `${language} ${code} -> ${key}`).not.toBe(key)
        expect(sentence.length).toBeGreaterThan(0)
      }
    }
  })

  it('never surfaces an internal detail from the platform', async () => {
    platform.proxyReply = {
      status: 500,
      body: {
        code: 'internal-error',
        messageKey: '',
        details: { traceback: 'File "/srv/backend/services/api_proxy.py", line 764' },
      },
    }

    const failure = (await send().catch((thrown: unknown) => thrown)) as ProxyTransportError
    const rendered = JSON.stringify(failure.clientError)

    expect(rendered).not.toContain('traceback')
    expect(rendered).not.toContain('api_proxy.py')
    expect(rendered).not.toContain('/srv/')
    // The error is a sentence to render, not a payload to inspect.
    expect(Object.keys(failure.clientError).sort()).toEqual(['kind', 'messageKey'])
  })
})
