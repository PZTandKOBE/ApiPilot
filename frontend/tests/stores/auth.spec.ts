import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { resetAuthRuntimeForTests } from '@/services/appConfig'
import { readToken, resetSessionForTests } from '@/services/session'
import { useAuthStore } from '@/stores/auth'
import type { User } from '@/types/user'

const user: User = {
  id: 'user-1',
  name: 'Ada',
  email: null,
  avatarUrl: null,
  provider: 'github',
}

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

const stubFetch = (handler: (url: string) => Response | Promise<Response>) => {
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => handler(String(input)))
}

beforeEach(() => {
  setActivePinia(createPinia())
  resetAuthRuntimeForTests()
  resetSessionForTests()
  vi.unstubAllGlobals()
})

describe('auth store', () => {
  it('loads self-hosted mode without asking for an account', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'self_hosted',
          loginRequired: false,
          guestEnabled: true,
          providers: [
            { id: 'github', configured: false },
            { id: 'google', configured: false },
          ],
        })
      }
      throw new Error('unexpected account request')
    })

    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.mode).toBe('self_hosted')
    expect(auth.user).toBeNull()
    expect(auth.guestEnabled).toBe(true)
    expect(auth.isGuest).toBe(true)
    expect(auth.isLoginAvailable).toBe(false)
    expect(auth.initialized).toBe(true)
  })

  it('starts an official guest session through the real session endpoint', async () => {
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() })
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'official_cloud',
          loginRequired: false,
          guestEnabled: true,
          providers: [
            { id: 'github', configured: true },
            { id: 'google', configured: true },
          ],
        })
      }
      if (url.endsWith('/api/auth/me')) return json({ code: 'auth-required' }, 401)
      if (url.endsWith('/api/guest-sessions')) {
        return json({ sessionToken: 'guest-token-for-test' }, 201)
      }
      return json({}, 500)
    })

    const auth = useAuthStore()
    await auth.initialize()
    const started = await auth.continueAsGuest()

    expect(started).toBe(true)
    expect(auth.user).toBeNull()
    expect(auth.guestEnabled).toBe(true)
    expect(readToken()).toBe('guest-token-for-test')
    expect(
      calls.some(
        (call) =>
          call.url.endsWith('/api/guest-sessions') && call.method === 'POST',
      ),
    ).toBe(true)
  })

  it('reads an existing guest token from storage after a reload', () => {
    resetSessionForTests()
    const cells = new Map<string, string>([
      ['aiata.guestSession.token', 'persisted-guest-token'],
    ])
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string): string | null => cells.get(key) ?? null,
        setItem: (key: string, value: string): void => {
          cells.set(key, value)
        },
        removeItem: (key: string): void => {
          cells.delete(key)
        },
      },
    })

    expect(readToken()).toBe('persisted-guest-token')
    resetSessionForTests()
  })

  it('does not pretend guest entry succeeded when issuance fails', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'official_cloud',
          loginRequired: false,
          guestEnabled: true,
          providers: [],
        })
      }
      if (url.endsWith('/api/auth/me')) return json({ code: 'auth-required' }, 401)
      if (url.endsWith('/api/guest-sessions')) {
        return json({ code: 'guest-sessions-disabled' }, 403)
      }
      return json({}, 500)
    })

    const auth = useAuthStore()
    await auth.initialize()
    const started = await auth.continueAsGuest()

    expect(started).toBe(false)
    expect(auth.guestError).toBe('auth.errors.guestStartFailed')
    expect(readToken()).toBeNull()
  })

  it('restores an official-cloud account from the cookie endpoint', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'official_cloud',
          loginRequired: true,
          providers: [
            { id: 'github', configured: true },
            { id: 'google', configured: false },
          ],
        })
      }
      if (url.endsWith('/api/auth/me')) return json(user)
      throw new Error('unexpected request')
    })

    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.mode).toBe('official_cloud')
    expect(auth.user).toEqual(user)
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.isLoginAvailable).toBe(true)
    expect(auth.providerConfigured('github')).toBe(true)
    expect(auth.providerConfigured('google')).toBe(false)
    expect(auth.initials).toBe('A')
  })

  it('keeps an unauthenticated official session signed out', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'official_cloud',
          loginRequired: true,
          providers: [{ id: 'github', configured: true }],
        })
      }
      return json({ code: 'auth-required' }, 401)
    })

    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.loginRequired).toBe(true)
    expect(auth.providers).toHaveLength(1)
  })

  it('refuses OAuth navigation in self-hosted mode even if a provider is configured', async () => {
    const assign = vi.fn()
    vi.stubGlobal('window', { location: { assign } })
    stubFetch(() =>
      json({
        deploymentMode: 'self_hosted',
        loginRequired: false,
        providers: [{ id: 'github', configured: true }],
      }),
    )

    const auth = useAuthStore()
    await auth.initialize()
    await auth.signIn('github')

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.signInError).toBe('auth.errors.authDisabled')
    expect(assign).not.toHaveBeenCalled()
  })

  it('navigates to the provider and rejects an unconfigured provider', async () => {
    const assign = vi.fn()
    vi.stubGlobal('window', { location: { assign } })
    stubFetch(() =>
      json({
        deploymentMode: 'official_cloud',
        loginRequired: true,
        providers: [
          { id: 'github', configured: true },
          { id: 'google', configured: false },
        ],
      }),
    )

    const auth = useAuthStore()
    await auth.initialize()

    await auth.signIn('google')
    expect(auth.signInError).toBe('auth.errors.providerUnavailable')
    expect(assign).not.toHaveBeenCalled()

    await auth.signIn('github', '/console')
    expect(assign).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/login/github?next=%2Fconsole'),
    )
  })

  it('clears the account after logout and surfaces a config failure', async () => {
    const logout = vi.fn(async () => undefined)
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/auth/config')) {
        return json({
          deploymentMode: 'official_cloud',
          loginRequired: true,
          providers: [{ id: 'github', configured: true }],
        })
      }
      if (url.endsWith('/api/auth/me')) return json(user)
      if (url.endsWith('/api/auth/logout') && init?.method === 'POST') {
        logout()
        return new Response(null, { status: 204 })
      }
      return json({}, 500)
    })

    const auth = useAuthStore()
    await auth.initialize()
    await auth.signOut()

    expect(logout).toHaveBeenCalledOnce()
    expect(auth.user).toBeNull()

    stubFetch(() => json({}, 503))
    const failed = useAuthStore()
    await failed.initialize(true)
    expect(failed.error).toBe('auth.errors.unavailable')
    expect(failed.initialized).toBe(true)
  })
})
