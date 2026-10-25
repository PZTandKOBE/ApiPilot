import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resetSessionForTests } from '@/services/session'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

interface Recorded {
  readonly method: string
  readonly url: string
}

let requests: Recorded[] = []
let deleteStatus = 204

const installFetch = (): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (rawUrl: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      requests.push({ method, url: String(rawUrl) })

      if (String(rawUrl).endsWith('/api/guest-sessions')) {
        return json(201, { sessionToken: 'gst_deletion' })
      }

      if (method === 'DELETE' && String(rawUrl).includes('/api/projects/')) {
        if (deleteStatus >= 400) {
          return json(deleteStatus, {
            code: 'internal-error',
            messageKey: 'console.project.deleteFailed',
          })
        }

        return new Response(null, { status: deleteStatus })
      }

      throw new Error('unexpected request: ' + method + ' ' + String(rawUrl))
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  resetSessionForTests()
  requests = []
  deleteStatus = 204
  installFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetSessionForTests()
})

describe('project deletion', () => {
  it('removes the active project and selects the remaining project', async () => {
    const store = useProjectStore()

    const deleted = await store.deleteProject('prj_orders')

    expect(deleted).toBe(true)
    expect(store.projects.map((project) => project.id)).not.toContain('prj_orders')
    expect(store.activeProjectId).toBe('prj_payments')
    expect(store.activeEnvironmentId).toBe('env_payments_dev')
    expect(store.deletingProject).toBe(false)

    const request = requests.find((item) => item.method === 'DELETE')
    expect(request?.url).toContain('/api/projects/prj_orders')
  })

  it('keeps the active project when a different project is deleted', async () => {
    const store = useProjectStore()
    store.selectProject('prj_payments')

    const deleted = await store.deleteProject('prj_orders')

    expect(deleted).toBe(true)
    expect(store.activeProjectId).toBe('prj_payments')
    expect(store.activeEnvironmentId).toBe('env_payments_dev')
  })

  it('leaves an empty active state when the last project is deleted', async () => {
    const store = useProjectStore()
    store.projects = [store.projectById('prj_orders')!]

    const deleted = await store.deleteProject('prj_orders')

    expect(deleted).toBe(true)
    expect(store.projects).toHaveLength(0)
    expect(store.activeProjectId).toBe('')
    expect(store.activeEnvironmentId).toBe('')
  })

  it('keeps the project and reports failure when the server refuses', async () => {
    deleteStatus = 500
    const store = useProjectStore()

    const deleted = await store.deleteProject('prj_orders')

    expect(deleted).toBe(false)
    expect(store.projectById('prj_orders')).not.toBeNull()
    expect(store.activeProjectId).toBe('prj_orders')
    expect(store.error).not.toBeNull()
    expect(store.deletingProject).toBe(false)
  })
})

describe('plan deletion', () => {
  it('removes every version in the document series but keeps other plans', async () => {
    const store = useAgentStore()
    await store.loadDemoSpec()
    await store.analyzeSpec()
    await store.regeneratePlan()

    const series = store.projectPlans
    expect(series.length).toBe(2)
    const first = series[0]
    expect(first).toBeDefined()

    const deleted = await store.deletePlan('prj_orders', first!.id)

    expect(deleted).toBe(true)
    expect(store.projectPlans).toHaveLength(0)
    expect(store.deletingPlan).toBe(false)
  })

  it('does not remove local plans when deletion fails or the target is unknown', async () => {
    const store = useAgentStore()
    await store.loadDemoSpec()
    await store.analyzeSpec()
    const plan = store.activePlan
    expect(plan).not.toBeNull()

    const missing = await store.deletePlan('prj_orders', 'plan_missing')
    expect(missing).toBe(false)
    expect(store.projectPlans).toHaveLength(1)
  })
})
