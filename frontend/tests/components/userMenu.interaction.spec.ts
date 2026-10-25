// @vitest-environment happy-dom
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, createApp, type App as VueApp } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import UserMenu from '@/components/console/UserMenu.vue'
import { readToken, resetSessionForTests } from '@/services/session'
import { useAuthStore } from '@/stores/auth'

let vueApp: VueApp | null = null
let container: HTMLDivElement | null = null

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const mountGuestMenu = async (): Promise<HTMLDivElement> => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.initialized = true
  auth.loading = false
  auth.mode = 'self_hosted'
  auth.providers = [
    { id: 'github', configured: false },
    { id: 'google', configured: false },
  ]
  auth.user = null

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

  container = document.createElement('div')
  document.body.appendChild(container)
  vueApp = createApp(UserMenu)
  vueApp.use(pinia)
  vueApp.use(router)
  vueApp.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
  vueApp.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  vueApp.mount(container)
  await flush()
  return container
}

const text = (): string => document.body.textContent ?? ''

afterEach(() => {
  vueApp?.unmount()
  vueApp = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  resetSessionForTests()
})

beforeEach(() => {
  document.body.innerHTML = ''
  resetSessionForTests()
})

describe('guest login interaction', () => {
  it('opens the guest menu and starts the existing sign-in surface', async () => {
    const root = await mountGuestMenu()
    const trigger = root.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')
    expect(trigger).not.toBeNull()
    expect(trigger?.textContent).toContain('Guest')
    expect(trigger?.tabIndex).not.toBe(-1)

    trigger?.click()
    await flush()

    expect(text()).toContain('Guest mode')
    expect(text()).toContain('Using a local Guest Session')
    expect(text()).toContain('Sign in to account')

    const login = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"], .el-dropdown-menu__item'))
      .find((item) => item.textContent?.includes('Sign in to account'))
    expect(login).toBeDefined()
    login?.click()
    await flush()

    expect(text()).toContain('Login is not enabled on this deployment.')
    expect(text()).not.toContain('Continue with GitHub')
    expect(text()).not.toContain('Continue with Google')
  })

  it('leaves the authenticated account menu intact', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.initialized = true
    auth.mode = 'official_cloud'
    auth.loginRequired = true
    auth.providers = [{ id: 'github', configured: true }]
    auth.user = {
      id: 'user-1',
      name: 'Ada Lovelace',
      email: null,
      avatarUrl: null,
      provider: 'github',
    }

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
    container = document.createElement('div')
    document.body.appendChild(container)
    vueApp = createApp(UserMenu)
    vueApp.use(pinia)
    vueApp.use(router)
    vueApp.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
    vueApp.provide(ZINDEX_INJECTION_KEY, { current: 0 })
    vueApp.mount(container)
    await flush()

    const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')
    expect(trigger?.textContent).toContain('Ada Lovelace')
    trigger?.click()
    await flush()

    // The account menu keeps identity and logout, but no Settings entry even
    // though this test router still registers a settings route.
    expect(text()).not.toContain('Settings')
    expect(text()).toContain('No email provided')
    expect(text()).toContain('Log out')
    expect(text()).not.toContain('Guest mode')
    expect(text()).not.toContain('Sign in to account')
  })

  it('shows both configured OAuth providers in the official-mode dialog', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.initialized = true
    auth.mode = 'official_cloud'
    auth.loginRequired = true
    auth.user = null
    auth.providers = [
      { id: 'github', configured: true },
      { id: 'google', configured: true },
    ]

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
    container = document.createElement('div')
    document.body.appendChild(container)
    vueApp = createApp(UserMenu)
    vueApp.use(pinia)
    vueApp.use(router)
    vueApp.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
    vueApp.provide(ZINDEX_INJECTION_KEY, { current: 0 })
    vueApp.mount(container)
    await flush()

    const signIn = container.querySelector<HTMLButtonElement>('button')
    expect(signIn?.textContent).toContain('Sign in')
    signIn?.click()
    await flush()

    const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('.el-dialog button'))
    const github = buttons.find((button) => button.textContent?.includes('Continue with GitHub'))
    const google = buttons.find((button) => button.textContent?.includes('Continue with Google'))
    expect(github).toBeDefined()
    expect(google).toBeDefined()
    expect(github?.disabled).toBe(false)
    expect(google?.disabled).toBe(false)
    expect(github?.className).toContain('signin-provider')
    expect(google?.className).toContain('signin-provider')
    expect(github?.parentElement).toBe(google?.parentElement)
    // The OAuth marks keep their own explicitly-sized SVGs.
    expect(github?.querySelector('svg')?.getAttribute('width')).toBe('16')
    expect(google?.querySelector('svg')?.getAttribute('width')).toBe('16')

    const signInSpy = vi.spyOn(auth, 'signIn').mockResolvedValue(undefined)
    github?.click()
    await flush()
    expect(signInSpy).toHaveBeenCalledWith('github', '/console')

    google?.click()
    await flush()
    expect(signInSpy).toHaveBeenCalledWith('google', '/console')
  })

  it('starts a real guest session from the official guest dialog', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.initialized = true
    auth.mode = 'official_cloud'
    auth.loginRequired = false
    auth.guestEnabled = true
    auth.user = null
    auth.providers = [
      { id: 'github', configured: true },
      { id: 'google', configured: true },
    ]

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
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/guest-sessions')) {
        return new Response(JSON.stringify({ sessionToken: 'dom-guest-token' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response('{}', { status: 500 })
    })

    container = document.createElement('div')
    document.body.appendChild(container)
    vueApp = createApp(UserMenu)
    vueApp.use(pinia)
    vueApp.use(router)
    vueApp.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
    vueApp.provide(ZINDEX_INJECTION_KEY, { current: 0 })
    vueApp.mount(container)
    await flush()

    const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')
    expect(trigger?.textContent).toContain('Guest')
    trigger?.click()
    await flush()

    const login = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"], .el-dropdown-menu__item'))
      .find((item) => item.textContent?.includes('Sign in to account'))
    login?.click()
    await flush()

    expect(text()).toContain('Continue as Guest')
    const guest = Array.from(document.querySelectorAll<HTMLButtonElement>('.el-dialog button'))
      .find((button) => button.textContent?.includes('Continue as Guest'))
    expect(guest).toBeDefined()
    expect(guest?.className).toContain('signin-provider')
    expect(guest?.className).toContain('signin-provider-guest')
    expect(guest?.querySelector('.signin-provider-label')?.textContent?.trim()).toBe(
      'Continue as Guest',
    )
    const guestIcon = guest?.querySelector('.signin-guest-icon')
    expect(guestIcon).not.toBeNull()
    expect(guestIcon?.querySelector('svg')).not.toBeNull()
    // The user glyph is an Element Plus icon component, not a bare SVG with no
    // button-sized dimensions.
    expect(guest?.querySelector('svg')?.parentElement?.classList.contains('el-icon')).toBe(true)
    guest?.click()
    await flush()
    await flush()

    expect(readToken()).toBe('dom-guest-token')
    expect(push).toHaveBeenCalled()
  })

  it('keeps a clickable account login entry for unconfigured official mode', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.initialized = true
    auth.mode = 'official_cloud'
    auth.loginRequired = true
    auth.user = null
    auth.providers = [
      { id: 'github', configured: false },
      { id: 'google', configured: false },
    ]

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
    container = document.createElement('div')
    document.body.appendChild(container)
    vueApp = createApp(UserMenu)
    vueApp.use(pinia)
    vueApp.use(router)
    vueApp.provide(ID_INJECTION_KEY, { prefix: 1000, current: 0 })
    vueApp.provide(ZINDEX_INJECTION_KEY, { current: 0 })
    vueApp.mount(container)
    await flush()

    const signIn = container.querySelector<HTMLButtonElement>('button')
    expect(signIn?.textContent).toContain('Sign in')
    signIn?.click()
    await flush()

    expect(text()).toContain('No OAuth provider is configured.')
    expect(text()).toContain('This provider is not configured on this deployment.')
    const github = Array.from(document.querySelectorAll<HTMLButtonElement>('.el-dialog button'))
      .find((button) => button.textContent?.includes('Continue with GitHub'))
    expect(github).toBeDefined()
    expect(github?.disabled).toBe(true)
    expect(github?.closest('button')?.getAttribute('disabled')).not.toBeNull()
  })
})
