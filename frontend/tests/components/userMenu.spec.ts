import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'

import UserMenu from '@/components/console/UserMenu.vue'
import { useAuthStore } from '@/stores/auth'

const render = async (setup: (auth: ReturnType<typeof useAuthStore>) => void): Promise<string> => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.initialized = true
  auth.loading = false
  setup(auth)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console', name: 'console-dashboard', component: {} },
      { path: '/console/settings', name: 'console-settings', component: {} },
      { path: '/login', name: 'login', component: {} },
    ],
  })
  await router.push('/console')
  await router.isReady()

  const app = createSSRApp(UserMenu)
  app.use(pinia)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  return renderToString(app)
}

describe('console user menu authentication states', () => {
  it('shows a sign-in action, never a fake account menu, for a self-hosted guest', async () => {
    const html = await render((auth) => {
      auth.mode = 'self_hosted'
      auth.user = null
      auth.providers = [
        { id: 'github', configured: false },
        { id: 'google', configured: false },
      ]
    })

    expect(html).toContain('Guest')
    expect(html).not.toContain('el-button--primary')
    expect(html).not.toContain('Log out')
    expect(html).not.toContain('No email provided')
    expect(html).not.toContain('Ada')
  })

  it('does not show an account menu for an unauthenticated official-cloud user', async () => {
    const html = await render((auth) => {
      auth.mode = 'official_cloud'
      auth.loginRequired = true
      auth.user = null
      auth.providers = [{ id: 'github', configured: false }]
    })

    expect(html).toContain('el-button--primary')
    expect(html).not.toContain('Log out')
    expect(html).not.toContain('No email provided')
  })

  it('shows account identity only after /me has supplied a user', async () => {
    const html = await render((auth) => {
      auth.mode = 'official_cloud'
      auth.loginRequired = true
      auth.providers = [{ id: 'github', configured: true }]
      auth.user = {
        id: 'user-1',
        name: 'Ada',
        email: null,
        avatarUrl: null,
        provider: 'github',
      }
    })

    expect(html).toContain('Ada')
    expect(html).not.toContain('el-button--primary')
  })
})
