// @vitest-environment happy-dom
import { createApp, nextTick, type App } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import AiTestLabView from '@/views/console/AiTestLabView.vue'

import { installProjectFixtures } from '../support/projects'

let app: App | null = null
let container: HTMLDivElement | null = null
let router: Router

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

const createTestRouter = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/ai-test', name: 'console-project-ai-test', component: {} },
      { path: '/console/projects/:projectId/plans', name: 'console-project-plans', component: {} },
      {
        path: '/console/projects/:projectId/plans/:planId',
        name: 'console-project-plan-detail',
        component: {},
      },
    ],
  })
  await instance.push('/console/projects/prj_orders/ai-test')
  await instance.isReady()
  return instance
}

const mount = async (): Promise<void> => {
  container = document.createElement('div')
  document.body.appendChild(container)

  app = createApp(AiTestLabView)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 3000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
}

beforeEach(async () => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  // Persisted plans outlive a test file's stores in happy-dom; start each case
  // with the same clean browser the production page would see on first load.
  window.localStorage.clear()
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('en-US')
  router = await createTestRouter()

  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
})

afterEach(() => {
  app?.unmount()
  app = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('AI Test Lab review and plan handoff integration', () => {
  it('keeps the five-step review and the existing plan after a refused second task', async () => {
    const agent = useAgentStore()
    await mount()

    expect(document.querySelector('[data-testid="analysis-review"]')).not.toBeNull()

    await agent.analyzeSpec()
    await flush()

    expect(agent.planError?.code).toBe('plan-exists')
    expect(agent.understanding).not.toBeNull()
    expect(agent.activePlan).not.toBeNull()
    expect(document.querySelector('[data-testid="analysis-review"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="plan-handoff"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Test plan ready')
    expect(document.body.textContent).toContain('A test plan already exists')
    // plan-exists is a destination, not a fatal error banner when the plan is available.
    expect(document.body.textContent).not.toContain('The agent could not finish')

    buttonByText('View test plan')?.click()
    await flush()
    expect(router.currentRoute.value.name).toBe('console-project-plan-detail')
    expect(router.currentRoute.value.params.planId).toBe(agent.activePlan?.id)
  })

  it('restores the review from the task audit when the page loses in-memory analysis', async () => {
    const agent = useAgentStore()
    agent.$patch({ understanding: null })
    expect(agent.understanding).toBeNull()

    await mount()
    await flush()

    expect(agent.understanding).not.toBeNull()
    expect(document.querySelector('[data-testid="analysis-review"]')).not.toBeNull()
  })

  it('does not render the full plan or approval controls in the lab', async () => {
    const agent = useAgentStore()
    await mount()
    expect(agent.activePlan).not.toBeNull()

    expect(document.querySelector('[data-testid="plan-handoff"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Test plan ready')
    expect(document.body.textContent).toContain('View test plan')

    // The plan's editing, approval, execution and delete actions belong to the
    // independent plan page, not this lab.
    expect(buttonByText('Edit')).toBeUndefined()
    expect(buttonByText('Approve')).toBeUndefined()
    expect(buttonByText('Reject')).toBeUndefined()
    expect(buttonByText('Run test')).toBeUndefined()
    expect(buttonByText('Delete plan')).toBeUndefined()
    expect(document.body.textContent).not.toContain('User authentication')
    expect(document.body.textContent).not.toContain('Delete plan')
  })

  it('navigates the final review step to the generated plan detail without generating or approving', async () => {
    const agent = useAgentStore()
    const generate = vi.spyOn(agent, 'generatePlan')
    const regenerate = vi.spyOn(agent, 'regeneratePlan')
    const approve = vi.spyOn(agent, 'approvePlan')
    const planId = agent.activePlan?.id ?? ''
    expect(planId).not.toBe('')
    await mount()

    const steps = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[data-testid="analysis-step"]'),
    )
    expect(steps).toHaveLength(5)
    steps[4]?.click()
    await flush()

    const continueButton = buttonByText('Go to test plans')
    expect(continueButton).toBeDefined()
    continueButton?.click()
    await flush()

    expect(router.currentRoute.value.name).toBe('console-project-plan-detail')
    expect(router.currentRoute.value.params.projectId).toBe('prj_orders')
    expect(router.currentRoute.value.params.planId).toBe(planId)
    expect(generate).not.toHaveBeenCalled()
    expect(regenerate).not.toHaveBeenCalled()
    expect(approve).not.toHaveBeenCalled()
    expect(agent.understanding).not.toBeNull()

    // The old in-page return link is gone with the embedded section.
    expect(buttonByText('Back to analysis review')).toBeUndefined()
  })

  it('opens the current plan from the compact handoff using its real id', async () => {
    const agent = useAgentStore()
    const plan = agent.activePlan
    expect(plan).not.toBeNull()
    await mount()

    buttonByText('View test plan')?.click()
    await flush()

    expect(router.currentRoute.value.name).toBe('console-project-plan-detail')
    expect(router.currentRoute.value.params.projectId).toBe(plan?.projectId)
    expect(router.currentRoute.value.params.planId).toBe(plan?.id)
  })

  it('navigates to the current version after a regeneration', async () => {
    const agent = useAgentStore()
    const previous = agent.activePlan
    expect(previous).not.toBeNull()
    await mount()

    await agent.regeneratePlan()
    await flush()

    const current = agent.activePlan
    expect(current).not.toBeNull()
    expect(current?.id).not.toBe(previous?.id)

    buttonByText('View test plan')?.click()
    await flush()

    expect(router.currentRoute.value.name).toBe('console-project-plan-detail')
    expect(router.currentRoute.value.params.planId).toBe(current?.id)
  })

  it('shows a failure and no success state when generation fails', async () => {
    const agent = useAgentStore()
    await mount()
    const plan = agent.activePlan
    expect(plan).not.toBeNull()
    expect(await agent.deletePlan('prj_orders', plan!.id)).toBe(true)
    await flush()

    vi.spyOn(agent, 'generatePlan').mockImplementation(async () => {
      agent.$patch({
        planError: {
          code: 'generate-failed',
          messageKey: 'console.aiTest.errors.generateFailed',
        },
      })
    })

    buttonByText('Generate test plan')?.click()
    await flush()

    expect(document.body.textContent).toContain(
      'The test plan could not be generated from this analysis.',
    )
    expect(document.body.textContent).not.toContain('Test plan ready')
    expect(buttonByText('View test plan')).toBeUndefined()
    expect(buttonByText('Generate test plan')).toBeDefined()
  })

  it('falls back to the plan list when no plan is available', async () => {
    const agent = useAgentStore()
    await mount()

    const plan = agent.activePlan
    expect(plan).not.toBeNull()
    expect(await agent.deletePlan('prj_orders', plan!.id)).toBe(true)
    await flush()

    expect(agent.activePlan).toBeNull()
    expect(document.body.textContent).toContain('Generate test plan')

    const steps = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[data-testid="analysis-step"]'),
    )
    steps[4]?.click()
    await flush()

    buttonByText('Go to test plans')?.click()
    await flush()

    expect(router.currentRoute.value.name).toBe('console-project-plans')
    expect(router.currentRoute.value.params.projectId).toBe('prj_orders')
  })
})
