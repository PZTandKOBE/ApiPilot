import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, request } from '@/services/http'
import {
  SESSION_HEADER,
  SessionError,
  readToken,
  resetSessionForTests,
} from '@/services/session'

/**
 * The guest session's failure paths, counted rather than described.
 *
 * Every assertion here is about how many requests were made.  A test that only
 * checked the final message would pass against the behaviour that once created
 * 11,815 sessions: an issuance that failed was swallowed, the business request
 * went out with no header, the 401 path minted another session, and the page
 * retried.  So the counts are the test.
 */

type Call = { url: string; method: string; headers: Record<string, string> }

const calls: Call[] = []

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

const sessionCalls = () => calls.filter((call) => call.url.endsWith('/api/guest-sessions'))
const businessCalls = () => calls.filter((call) => !call.url.endsWith('/api/guest-sessions'))

const installFetch = (handler: (call: Call) => Response | Promise<Response>) => {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const call: Call = {
      url: String(input),
      method: (init?.method ?? 'GET').toUpperCase(),
      headers: (init?.headers ?? {}) as Record<string, string>,
    }
    calls.push(call)
    return await handler(call)
  })
}

beforeEach(() => {
  calls.length = 0
  resetSessionForTests()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetSessionForTests()
})

describe('a session that is obtained', () => {
  it('carries the header on the business request', async () => {
    installFetch((call) =>
      call.url.endsWith('/api/guest-sessions')
        ? jsonResponse({ sessionToken: 'tok-1' }, 201)
        : jsonResponse({ ok: true }),
    )

    await expect(request('/api/projects')).resolves.toEqual({ ok: true })

    expect(sessionCalls()).toHaveLength(1)
    expect(businessCalls()).toHaveLength(1)
    expect(businessCalls()[0]?.headers[SESSION_HEADER]).toBe('tok-1')
    expect(readToken()).toBe('tok-1')
  })
})

describe('a session that cannot be obtained', () => {
  it('surfaces the failure to the caller instead of sending an unauthenticated request', async () => {
    installFetch(() => {
      throw new TypeError('Failed to fetch')
    })

    await expect(request('/api/projects')).rejects.toBeInstanceOf(SessionError)

    // The decisive count: no business request was attempted at all.
    expect(businessCalls()).toHaveLength(0)
    expect(sessionCalls()).toHaveLength(1)
  })

  it('reports an unreadable 201 as a failure, not as a missing session', async () => {
    // The CORS shape: the server created a session, the browser refused the body.
    installFetch((call) =>
      call.url.endsWith('/api/guest-sessions')
        ? new Response('', { status: 201 })
        : jsonResponse({ ok: true }),
    )

    await expect(request('/api/projects')).rejects.toMatchObject({
      name: 'SessionError',
      code: 'guest-session-invalid-response',
    })
    expect(businessCalls()).toHaveLength(0)
  })

  it('stops asking after a bounded number of failures', async () => {
    installFetch(() => {
      throw new TypeError('Failed to fetch')
    })

    for (let attempt = 0; attempt < 12; attempt += 1) {
      await expect(request('/api/projects')).rejects.toBeInstanceOf(SessionError)
    }

    // Three tries, then the tab stops: twelve calls, at most three issuances.
    expect(sessionCalls().length).toBeLessThanOrEqual(3)
    expect(businessCalls()).toHaveLength(0)
    await expect(request('/api/projects')).rejects.toMatchObject({
      code: 'guest-session-suppressed',
    })
  })

  it('tries again once the cooldown has passed', async () => {
    const now = vi.spyOn(Date, 'now')
    let clock = 1_000_000
    now.mockImplementation(() => clock)

    installFetch(() => {
      throw new TypeError('Failed to fetch')
    })

    for (let attempt = 0; attempt < 4; attempt += 1) {
      await expect(request('/api/projects')).rejects.toBeInstanceOf(SessionError)
    }
    const afterBudget = sessionCalls().length
    expect(afterBudget).toBe(3)

    // A permanent failure must not become permanent for the tab: once the
    // configured window passes, the next call asks again.
    clock += 10_000
    installFetch((call) =>
      call.url.endsWith('/api/guest-sessions')
        ? jsonResponse({ sessionToken: 'tok-2' }, 201)
        : jsonResponse({ ok: true }),
    )

    await expect(request('/api/projects')).resolves.toEqual({ ok: true })
    expect(sessionCalls().length).toBe(afterBudget + 1)
    expect(readToken()).toBe('tok-2')
  })
})

describe('concurrent first use', () => {
  it('shares one issuance between simultaneous requests', async () => {
    installFetch(async (call) => {
      if (call.url.endsWith('/api/guest-sessions')) {
        await new Promise((resolve) => setTimeout(resolve, 5))
        return jsonResponse({ sessionToken: 'tok-shared' }, 201)
      }
      return jsonResponse({ ok: true })
    })

    await Promise.all([
      request('/api/projects'),
      request('/api/projects'),
      request('/api/projects'),
      request('/api/projects'),
      request('/api/projects'),
    ])

    expect(sessionCalls()).toHaveLength(1)
    expect(businessCalls()).toHaveLength(5)
    expect(businessCalls().every((call) => call.headers[SESSION_HEADER] === 'tok-shared')).toBe(true)
  })
})

describe('a token the server refuses', () => {
  it('is replaced once and the request retried exactly once', async () => {
    let issued = 0
    installFetch((call) => {
      if (call.url.endsWith('/api/guest-sessions')) {
        issued += 1
        return jsonResponse({ sessionToken: 'tok-' + issued }, 201)
      }
      return jsonResponse({ code: 'guest-session-required' }, 401)
    })

    await expect(request('/api/projects')).rejects.toBeInstanceOf(ApiError)

    // Two business attempts (the original and the one retry), two issuances,
    // and then it stops rather than looping.
    expect(businessCalls()).toHaveLength(2)
    expect(sessionCalls()).toHaveLength(2)
  })

  it('recovers when the replacement is accepted', async () => {
    let attempts = 0
    installFetch((call) => {
      if (call.url.endsWith('/api/guest-sessions')) {
        return jsonResponse({ sessionToken: 'tok-' + (attempts + 1) }, 201)
      }
      attempts += 1
      return attempts === 1
        ? jsonResponse({ code: 'guest-session-required' }, 401)
        : jsonResponse({ ok: true })
    })

    await expect(request('/api/projects')).resolves.toEqual({ ok: true })
    expect(businessCalls()).toHaveLength(2)
    expect(sessionCalls()).toHaveLength(2)
  })
})
