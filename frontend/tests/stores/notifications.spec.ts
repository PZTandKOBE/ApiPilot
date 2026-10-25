// @vitest-environment happy-dom
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listReports } from '@/services/api/reports'
import { resetSessionForTests } from '@/services/session'
import { useAgentStore } from '@/stores/agent'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useUiStore } from '@/stores/ui'
import type { AgentTaskSummary } from '@/types/agent'
import type { RunReportSummary } from '@/types/report'

import { installProjectFixtures } from '../support/projects'

vi.mock('@/services/api/reports', () => ({
  listReports: vi.fn(),
}))

const mockedListReports = vi.mocked(listReports)

const REPORT: RunReportSummary = {
  id: 'report-1',
  projectId: 'prj_orders',
  runId: 'run-1',
  name: 'Orders report',
  filename: 'Orders-report.pdf',
  contentType: 'application/pdf',
  byteSize: 2048,
  sha256: 'abc',
  generatedAt: '2026-10-17T12:00:00.000Z',
  runStatus: 'passed',
}

const FAILED_TASK: AgentTaskSummary = {
  id: 'task-failed',
  projectId: 'prj_orders',
  prompt: 'Analyze the broken document',
  status: 'failed',
  createdAt: '2026-10-17T12:00:00.000Z',
  updatedAt: '2026-10-17T12:01:00.000Z',
}

const setup = async (): Promise<ReturnType<typeof useAgentStore>> => {
  setActivePinia(createPinia())
  window.localStorage.clear()
  installProjectFixtures(useProjectStore())
  resetSessionForTests()
  mockedListReports.mockReset()
  mockedListReports.mockResolvedValue([REPORT])

  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  return agent
}

beforeEach(async () => {
  document.body.innerHTML = ''
  await setup()
})

describe('real notification projection', () => {
  it('creates agent, pending-plan and saved-report notifications from real rows', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()

    expect(ui.notifications).toHaveLength(3)
    expect(ui.unreadCount).toBe(3)

    const agentItem = ui.notifications.find((item) =>
      item.id.startsWith('agent:'),
    )
    const planItem = ui.notifications.find((item) => item.id.startsWith('plan:'))
    const reportItem = ui.notifications.find((item) =>
      item.id.startsWith('report:'),
    )

    expect(agentItem?.titleKey).toBe('console.topbar.notification.agentTitle')
    expect(agentItem?.projectId).toBe('prj_orders')
    expect(agentItem?.to).toBe('/console/projects/prj_orders/ai-test')
    expect(agentItem?.createdAt).toBeGreaterThan(0)

    expect(planItem?.titleKey).toBe('console.topbar.notification.planTitle')
    expect(planItem?.localizedName).toEqual(
      useAgentStore().projectPlans[0]?.name,
    )
    expect(planItem?.to).toMatch(/^\/console\/projects\/prj_orders\/plans\/plan_/)

    expect(reportItem?.titleKey).toBe('console.topbar.notification.reportTitle')
    expect(reportItem?.detailParams).toEqual({ name: 'Orders report' })
    expect(reportItem?.to).toBe('/console/projects/prj_orders/reports')
    expect(reportItem?.createdAt).toBe(Date.parse(REPORT.generatedAt))

    const times = ui.notifications.map((item) => item.createdAt)
    expect(times).toEqual([...times].sort((left, right) => right - left))
  })

  it('does not notify for a failed agent task or a missing report', async () => {
    const agent = useAgentStore()
    vi.spyOn(agent, 'listRecentTasks').mockResolvedValue([FAILED_TASK])
    mockedListReports.mockResolvedValue([])

    const ui = useUiStore()
    await ui.loadNotifications()

    expect(ui.notifications.some((item) => item.id.startsWith('agent:'))).toBe(false)
    expect(ui.notifications.some((item) => item.id.startsWith('report:'))).toBe(false)
    expect(ui.notifications.some((item) => item.id.startsWith('plan:'))).toBe(true)
  })

  it('removes the pending-plan notification once the plan is approved', async () => {
    const agent = useAgentStore()
    const plan = agent.activePlan
    expect(plan).not.toBeNull()

    const ui = useUiStore()
    await ui.loadNotifications()
    expect(ui.notifications.some((item) => item.id.startsWith('plan:'))).toBe(true)

    agent.approvePlan(plan!.id)
    await ui.loadNotifications()

    expect(ui.notifications.some((item) => item.id.startsWith('plan:'))).toBe(false)
    expect(ui.unreadCount).toBe(2)
  })

  it('moves the pending approval notification to the newest plan version', async () => {
    const agent = useAgentStore()
    const ui = useUiStore()
    await ui.loadNotifications()
    const before = ui.notifications.find((item) => item.id.startsWith('plan:'))
    expect(before).toBeDefined()

    await agent.regeneratePlan()
    await ui.loadNotifications()

    const plans = ui.notifications.filter((item) => item.id.startsWith('plan:'))
    expect(plans).toHaveLength(1)
    expect(plans[0]?.id).not.toBe(before?.id)
    expect(plans[0]?.to).toContain(agent.activePlan?.id)
  })

  it('keeps IDs stable across refreshes and preserves read markers', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()
    const firstIds = ui.notifications.map((item) => item.id)
    const agentItem = ui.notifications.find((item) => item.id.startsWith('agent:'))
    expect(agentItem).toBeDefined()

    await ui.loadNotifications()
    expect(ui.notifications.map((item) => item.id)).toEqual(firstIds)

    ui.markRead(agentItem!.id)
    expect(ui.unreadCount).toBe(2)

    await ui.loadNotifications()
    expect(ui.unreadCount).toBe(2)
    expect(
      ui.notifications.find((item) => item.id === agentItem!.id)?.read,
    ).toBe(true)
  })

  it('marks everything read and keeps that state on refresh', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()

    ui.markAllRead()
    expect(ui.unreadCount).toBe(0)

    await ui.loadNotifications()
    expect(ui.unreadCount).toBe(0)
    expect(ui.notifications.every((item) => item.read)).toBe(true)
  })

  it('drops a report notification when that report is no longer listed', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()
    expect(ui.notifications.some((item) => item.id.startsWith('report:'))).toBe(true)

    mockedListReports.mockResolvedValue([])
    await ui.loadNotifications()

    expect(ui.notifications.some((item) => item.id.startsWith('report:'))).toBe(false)
    expect(ui.notifications.some((item) => item.id.startsWith('agent:'))).toBe(true)
  })

  it('drops another project from the feed and never leaks its rows', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()
    expect(ui.notifications).toHaveLength(3)

    mockedListReports.mockResolvedValue([])
    useProjectStore().selectProject('prj_payments')
    await ui.loadNotifications()

    expect(ui.notifications).toHaveLength(0)
    expect(ui.unreadCount).toBe(0)

    useProjectStore().selectProject('prj_orders')
    await ui.loadNotifications()
    expect(ui.notifications.length).toBeGreaterThan(0)
    expect(ui.notifications.every((item) => item.projectId === 'prj_orders')).toBe(true)
  })

  it('does not reuse the read state of another identity', async () => {
    const ui = useUiStore()
    await ui.loadNotifications()
    ui.markAllRead()
    expect(ui.unreadCount).toBe(0)

    const auth = useAuthStore()
    auth.$patch({
      user: {
        id: 'user-1',
        name: 'Ada Lovelace',
        email: null,
        avatarUrl: null,
        provider: 'github',
      },
    })
    await ui.loadNotifications()
    expect(ui.unreadCount).toBe(3)

    auth.$patch({ user: null })
    await ui.loadNotifications()
    expect(ui.unreadCount).toBe(0)
  })

  it('distinguishes a load error from a genuinely empty feed', async () => {
    mockedListReports.mockRejectedValue(new Error('reports unavailable'))
    const ui = useUiStore()
    await ui.loadNotifications()

    expect(ui.notificationError).toBe('console.topbar.notification.loadFailed')
    // Other project-scoped sources still populate; this is a partial failure.
    expect(ui.notifications.length).toBeGreaterThan(0)
  })

  it('shows an empty feed when all real sources are empty', async () => {
    mockedListReports.mockResolvedValue([])
    useProjectStore().selectProject('prj_payments')

    const ui = useUiStore()
    await ui.loadNotifications()

    expect(ui.notifications).toHaveLength(0)
    expect(ui.unreadCount).toBe(0)
    expect(ui.notificationError).toBeNull()
  })
})
