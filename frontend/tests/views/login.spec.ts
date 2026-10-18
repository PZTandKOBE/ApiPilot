import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

const render = async (path: string): Promise<{ html: string; text: string }> => {
  const router: Router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: {} },
      { path: '/login', name: 'login', component: {} },
      { path: '/console', name: 'console-dashboard', component: {} },
      { path: '/learn', name: 'learn', component: {} },
    ],
  })
  await router.push(path)
  await router.isReady()

  const app = createSSRApp(LoginView)
  app.use(router)
  const html = await renderToString(app)
  const text = html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()
  return { html, text }
}

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.mode = 'self_hosted'
  auth.initialized = true
  auth.loading = false
  auth.guestEnabled = false
  auth.providers = []
})

describe('login page', () => {
  it('shows the self-hosted guest path without dead OAuth controls', async () => {
    const { text, html } = await render('/login')

    expect(text).toContain('Self-hosted mode')
    expect(text).toContain('Login is not enabled on this deployment.')
    expect(text).toContain('Continue to console')
    expect(html).not.toContain('Continue with GitHub')
    expect(html).toContain('https://github.com/PZTandKOBE/ApiPilot')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('shows configured provider buttons and a readable unavailable provider', async () => {
    const auth = useAuthStore()
    auth.mode = 'official_cloud'
    auth.loginRequired = true
    auth.providers = [
      { id: 'github', configured: true },
      { id: 'google', configured: false },
    ]

    const { text } = await render('/login')

    expect(text).toContain('Continue with GitHub')
    expect(text).toContain('This provider is not configured on this deployment.')
    expect(text).toContain('First sign-in creates your ApiPilot account.')
  })

  it('shows a clear no-provider message instead of starting OAuth', async () => {
    const auth = useAuthStore()
    auth.mode = 'official_cloud'
    auth.loginRequired = true
    auth.providers = [
      { id: 'github', configured: false },
      { id: 'google', configured: false },
    ]

    const { text } = await render('/login')

    expect(text).toContain('No OAuth provider is configured.')
    expect(text).not.toContain('Continue with GitHub')
    expect(text).not.toContain('Continue with Google')
  })

  it('offers guest experience beside the official login options', async () => {
    const auth = useAuthStore()
    auth.mode = 'official_cloud'
    auth.loginRequired = false
    auth.guestEnabled = true
    auth.providers = [
      { id: 'github', configured: true },
      { id: 'google', configured: true },
    ]

    const { text } = await render('/login')

    expect(text).toContain('Continue with GitHub')
    expect(text).toContain('Continue with Google')
    expect(text).toContain('Continue as Guest')
    expect(text).toContain('or')
  })

  it('renders the callback error instead of a blank page', async () => {
    const auth = useAuthStore()
    auth.mode = 'official_cloud'
    auth.providers = [{ id: 'github', configured: true }]

    const { text } = await render('/login?error=state-invalid')

    expect(text).toContain('The sign-in request expired or was already used.')
  })

  it('shows a signed-in account and its console continuation', async () => {
    const auth = useAuthStore()
    auth.mode = 'official_cloud'
    auth.user = {
      id: 'user-1',
      name: 'Ada',
      email: null,
      avatarUrl: null,
      provider: 'github',
    }

    const { text } = await render('/login?next=/console')

    expect(text).toContain('Ada')
    expect(text).toContain('No email provided')
    expect(text).toContain('Continue to console')
  })
})
