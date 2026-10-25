// @vitest-environment happy-dom
import { createApp, h, nextTick, type App } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AnalysisReviewPanel from '@/components/console/Agent/AnalysisReviewPanel.vue'
import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

let app: App | null = null
let container: HTMLDivElement | null = null

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const mount = async (onContinue?: () => void): Promise<HTMLDivElement> => {
  container = document.createElement('div')
  document.body.appendChild(container)

  app = createApp({
    render: () =>
      h(AnalysisReviewPanel, {
        onContinueToPlan: onContinue,
      }),
  })
  app.provide(ID_INJECTION_KEY, { prefix: 2000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
  return container
}

const stepButtons = (): HTMLButtonElement[] =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('[data-testid="analysis-step"]'))

const panel = (): HTMLElement =>
  document.querySelector<HTMLElement>('[data-testid="analysis-review-panel"]') as HTMLElement

const visiblePanels = (): HTMLElement[] =>
  Array.from(panel().children).filter(
    (child) => (child as HTMLElement).style.display !== 'none',
  ) as HTMLElement[]

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

beforeEach(async () => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('en-US')

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

describe('AnalysisReviewPanel', () => {
  it('shows five labelled steps and exactly one visible panel at a time', async () => {
    await mount()

    const steps = stepButtons()
    expect(steps).toHaveLength(5)
    expect(steps.map((step) => step.textContent?.replace(/\s+/g, '').trim())).toEqual([
      '01APIspec',
      '02Understanding',
      '03Dependencies',
      '04Potentialrisks',
      '05Agentactions',
    ])
    expect(steps[0]?.getAttribute('aria-current')).toBe('step')
    expect(visiblePanels()).toHaveLength(1)
    expect(visiblePanels()[0]?.textContent).toContain('Orders Platform API')
    expect(document.body.textContent).toContain('01 / 05')

    const contentMarkers = [
      'Orders Platform API',
      'API Understanding',
      'POST /api/auth/login',
      'endpoints require authentication',
      'Parsed the OpenAPI 3 document',
    ]

    for (const [index, marker] of contentMarkers.entries()) {
      stepButtons()[index]?.click()
      await flush()
      expect(stepButtons()[index]?.getAttribute('aria-current')).toBe('step')
      expect(visiblePanels()).toHaveLength(1)
      expect(visiblePanels()[0]?.textContent).toContain(marker)

      if (index === 3) {
        expect(visiblePanels()[0]?.textContent).toContain('Related endpoints')
        expect(visiblePanels()[0]?.textContent).toContain('Fields')
      }
    }
  })

  it('navigates directly and with previous/next without calling the agent', async () => {
    const agent = useAgentStore()
    const analyze = vi.spyOn(agent, 'analyzeSpec')
    const pipelineStep = agent.step
    const taskStatus = agent.taskStatus
    await mount()

    const previous = buttonByText('Previous')
    expect(previous).toBeDefined()
    expect(previous?.disabled).toBe(true)

    stepButtons()[2]?.click()
    await flush()
    expect(stepButtons()[2]?.getAttribute('aria-current')).toBe('step')
    expect(document.body.textContent).toContain('03 / 05')
    expect(visiblePanels()).toHaveLength(1)
    expect(visiblePanels()[0]?.textContent).toContain('POST /api/auth/login')
    expect(document.activeElement).toBe(panel())

    buttonByText('Previous')?.click()
    await flush()
    expect(stepButtons()[1]?.getAttribute('aria-current')).toBe('step')
    expect(document.body.textContent).toContain('02 / 05')

    buttonByText('Next')?.click()
    await flush()
    expect(stepButtons()[2]?.getAttribute('aria-current')).toBe('step')

    stepButtons()[1]?.click()
    await flush()
    expect(stepButtons()[1]?.getAttribute('aria-current')).toBe('step')
    expect(agent.understanding).not.toBeNull()
    expect(agent.step).toBe(pipelineStep)
    expect(agent.taskStatus).toBe(taskStatus)
    expect(analyze).not.toHaveBeenCalled()
  })

  it('replaces Next with a test-plan navigation on the fifth step', async () => {
    const onContinue = vi.fn()
    const agent = useAgentStore()
    const approve = vi.spyOn(agent, 'approvePlan')
    const generate = vi.spyOn(agent, 'generatePlan')
    await mount(onContinue)

    stepButtons()[4]?.click()
    await flush()

    expect(stepButtons()[4]?.getAttribute('aria-current')).toBe('step')
    expect(document.body.textContent).toContain('05 / 05')
    expect(buttonByText('Next')).toBeUndefined()
    const continueButton = buttonByText('Go to test plans')
    expect(continueButton).toBeDefined()

    continueButton?.click()
    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(approve).not.toHaveBeenCalled()
    expect(generate).not.toHaveBeenCalled()
    expect(agent.understanding).not.toBeNull()
  })

  it('shows the existing empty states when dependency, risk and finding arrays are empty', async () => {
    const agent = useAgentStore()
    const current = agent.understanding
    expect(current).not.toBeNull()

    agent.understanding = {
      ...current!,
      dependencies: [],
      risks: [],
      findings: [],
    }

    await mount()

    stepButtons()[2]?.click()
    await flush()
    expect(visiblePanels()[0]?.textContent).toContain('No dependencies were found')

    stepButtons()[3]?.click()
    await flush()
    expect(visiblePanels()[0]?.textContent).toContain('No coverage risks were identified')

    stepButtons()[4]?.click()
    await flush()
    expect(visiblePanels()[0]?.textContent).toContain('The agent has not run yet')
  })

  it('keeps a selected plan untouched while the reader moves between steps', async () => {
    const agent = useAgentStore()
    const planBefore = agent.activePlan
    const before = planBefore?.status
    await mount()

    stepButtons()[4]?.click()
    await flush()
    stepButtons()[0]?.click()
    await flush()

    expect(agent.activePlan?.status).toBe(before)
    expect(agent.activePlan).toBe(planBefore)
    expect(agent.activePlan).not.toBeNull()
  })
})
