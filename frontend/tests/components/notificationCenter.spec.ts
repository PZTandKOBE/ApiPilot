// @vitest-environment happy-dom
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createApp, nextTick, type App as VueApp } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import NotificationCenter from '@/components/console/NotificationCenter.vue'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import type { ConsoleNotification } from '@/types/console'

import { installProjectFixtures } from '../support/projects'

let app: VueApp | null = null
let container: HTMLDivElement | null = null
let router: Router

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const sample = (): readonly ConsoleNotification[] => [
  {
    id: 'plan:prj_orders:plan_1:v1',
    projectId: 'prj_orders',
    kind: 'warning',
    titleKey: 'console.topbar.notification.planTitle',
    detailKey: 'console.topbar.notification.planBody',
    detailParams: { project: 'Orders project' },
    localizedName: { text: 'Checkout plan' },
    to: '/console/projects/prj_orders/plans/plan_1',
    createdAt: Date.now() - 120_000,
    read: false,
  },
  {
    id: 'report:prj_orders:report_1',
    projectId: 'prj_orders',
    kind: 'success',
    titleKey: 'console.topbar.notification.reportTitle',
    detailKey: 'console.topbar.notification.reportBody',
    detailParams: { name: 'Orders report' },
    to: '/console/projects/prj_orders/reports',
    createdAt: Date.now() - 300_000,
    read: true,
  },
]

const mount = async (
  notifications: readonly ConsoleNotification[] = sample(),
  error: string | null = null,
): Promise<void> => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('en-US')
  const ui = useUiStore()
  vi.spyOn(ui, 'loadNotifications').mockResolvedValue(undefined)
  ui.$patch({
    notifications,
    notificationError: error,
    notificationLoading: false,
  })

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/ai-test', name: 'console-project-ai-test', component: {} },
      { path: '/console/projects/:projectId/plans', name: 'console-project-plans', component: {} },
      {
        path: '/console/projects/:projectId/plans/:planId',
        name: 'console-project-plan-detail',
        component: {},
      },
      { path: '/console/projects/:projectId/reports', name: 'console-project-reports', component: {} },
    ],
  })
  await router.push('/console/projects/prj_orders/ai-test')
  await router.isReady()

  container = document.createElement('div')
  document.body.appendChild(container)
  app = createApp(NotificationCenter)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 6000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
}

const trigger = (): HTMLButtonElement | null =>
  document.querySelector<HTMLButtonElement>('button[aria-label="Notifications"]')

const clickOpen = async (): Promise<void> => {
  trigger()?.click()
  await flush()
}

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

beforeEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

afterEach(() => {
  app?.unmount()
  app = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('NotificationCenter', () => {
  it('opens and closes the panel and shows real notification content', async () => {
    await mount()

    await clickOpen()

    expect(document.querySelector('[data-testid="notification-center"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Test plan awaiting approval')
    expect(document.body.textContent).toContain('Checkout plan')
    expect(document.body.textContent).toContain('Orders project')
    expect(document.body.textContent).toContain('Test report ready')
    expect(document.body.textContent).toContain('Orders report')
    expect(document.body.textContent).toContain('minutes ago')

    const center = document.querySelector<HTMLElement>(
      '[data-testid="notification-center"]',
    )
    expect(center?.getAttribute('data-open')).toBe('true')

    document.querySelector<HTMLButtonElement>('button[aria-label="Close"]')?.click()
    await flush()
    expect(center?.getAttribute('data-open')).toBe('false')
  })

  it('translates the chrome and notification titles with the active locale', async () => {
    await mount()
    await clickOpen()

    useLocaleStore().setLocale('zh-CN')
    await flush()

    expect(document.body.textContent).toContain('测试计划待批准')
    expect(document.body.textContent).toContain('测试报告已生成')
    expect(document.body.textContent).toContain('全部标为已读')
    expect(document.body.textContent).toContain('Checkout plan')
  })

  it('marks a clicked notification read and navigates to its real destination', async () => {
    await mount()
    const ui = useUiStore()
    const markRead = vi.spyOn(ui, 'markRead')
    const push = vi.spyOn(router, 'push')
    await clickOpen()

    const item = Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) => button.textContent?.includes('Test plan awaiting approval'),
    )
    item?.click()
    await flush()

    expect(markRead).toHaveBeenCalledWith('plan:prj_orders:plan_1:v1')
    expect(push).toHaveBeenCalledWith('/console/projects/prj_orders/plans/plan_1')
    expect(
      document
        .querySelector('[data-testid="notification-center"]')
        ?.getAttribute('data-open'),
    ).toBe('false')
  })

  it('marks all notifications read from the header action', async () => {
    await mount()
    const ui = useUiStore()
    const markAll = vi.spyOn(ui, 'markAllRead')
    await clickOpen()

    buttonByText('Mark all as read')?.click()
    await flush()

    expect(markAll).toHaveBeenCalledTimes(1)
  })

  it('shows a real empty state when the feed has no events', async () => {
    await mount([])
    await clickOpen()

    expect(document.body.textContent).toContain('Nothing to catch up on')
    expect(document.querySelector('[data-testid="notification-list"]')).toBeNull()
  })

  it('shows an error and retries without pretending the feed is empty', async () => {
    await mount([], 'console.topbar.notification.loadFailed')
    const ui = useUiStore()
    const load = vi.mocked(ui.loadNotifications)
    await clickOpen()

    expect(document.body.textContent).toContain(
      'Notifications could not be loaded',
    )
    expect(document.body.textContent).not.toContain('Nothing to catch up on')

    buttonByText('Try again')?.click()
    await flush()
    expect(load.mock.calls.length).toBeGreaterThan(1)
  })
})
