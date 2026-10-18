import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchPublicAuthConfig,
  resetAuthRuntimeForTests,
} from '@/services/appConfig'
import { request } from '@/services/http'
import {
  ensureSession,
  readToken,
  resetSessionForTests,
} from '@/services/session'

interface Call {
  url: string
  method: string
  credentials: RequestCredentials | undefined
  headers: Record<string, string>
}

const calls: Call[] = []

const install = (): void => {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({
      url,
      method: (init?.method ?? 'GET').toUpperCase(),
      credentials: init?.credentials,
      headers: (init?.headers ?? {}) as Record<string, string>,
    })
    if (url.endsWith('/api/auth/config')) {
      return new Response(
        JSON.stringify({
          deploymentMode: 'official_cloud',
          loginRequired: true,
          providers: [{ id: 'github', configured: true }],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    }
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetAuthRuntimeForTests()
  resetSessionForTests()
  calls.length = 0
})

describe('official-cloud request transport', () => {
  it('uses the cookie credential and never mints a guest session', async () => {
    install()
    await fetchPublicAuthConfig()

    await expect(request('/api/projects')).resolves.toEqual({ ok: true })

    expect(calls.some((call) => call.url.endsWith('/api/guest-sessions'))).toBe(false)
    expect(calls.some((call) => call.headers['X-Guest-Session'] !== undefined)).toBe(false)
    const business = calls.find((call) => call.url.endsWith('/api/projects'))
    expect(business?.credentials).toBe('include')
    expect(readToken()).toBeNull()
  })

  it('sends an explicitly started official guest token without minting implicitly', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({
        url,
        method: (init?.method ?? 'GET').toUpperCase(),
        credentials: init?.credentials,
        headers: (init?.headers ?? {}) as Record<string, string>,
      })
      if (url.endsWith('/api/auth/config')) {
        return new Response(
          JSON.stringify({
            deploymentMode: 'official_cloud',
            loginRequired: false,
            guestEnabled: true,
            providers: [{ id: 'github', configured: true }],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
      }
      if (url.endsWith('/api/guest-sessions')) {
        return new Response(JSON.stringify({ sessionToken: 'guest-token' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })

    await fetchPublicAuthConfig()
    await ensureSession()
    await expect(request('/api/projects')).resolves.toEqual({ ok: true })

    const business = calls.find((call) => call.url.endsWith('/api/projects'))
    expect(business?.headers['X-Guest-Session']).toBe('guest-token')
    expect(
      calls.filter((call) => call.url.endsWith('/api/guest-sessions')),
    ).toHaveLength(1)
  })
})
