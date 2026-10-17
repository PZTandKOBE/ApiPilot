import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import { installProjectFixtures } from '../support/projects'
import type { TestPlan } from '@/types/agent'
import TestPlanDetailView from '@/views/console/TestPlanDetailView.vue'
import TestPlansView from '@/views/console/TestPlansView.vue'

import { installStorage, removeStorage } from '../support/storage'

/**
 * The plan list and the plan detail page, server-rendered.
 *
 * Both read the same store the lab writes to, so these also stand as the check
 * that there is exactly one source of plans in the application.
 */
let router: Router

const createTestRouter = async (path: string): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/plans', name: 'console-project-plans', component: {} },
      {
        path: '/console/projects/:projectId/plans/:planId',
        name: 'console-project-plan-detail',
        component: {},
      },
      { path: '/console/projects/:projectId/ai-test', name: 'console-project-ai-test', component: {} },
    ],
  })

  await instance.push(path)
  await instance.isReady()
  return instance
}

beforeEach(() => {
  setActivePinia(createPinia())
  // The project store starts empty now; the agent store scopes a document to the
  // active project, so these tests state which project that is.
  installProjectFixtures(useProjectStore())
})

const render = async (
  component: unknown,
  path = '/console/projects/prj_orders/plans',
): Promise<string> => {
  router = await createTestRouter(path)

  const app = createSSRApp(component as never)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 1024, current: 0 })
  return renderToString(app)
}

const textOf = (html: string): string =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

const has = (html: string, needle: string): boolean => textOf(html).includes(needle)

const withPlan = async () => {
  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.generatePlan()
  return agent
}

describe('plan list', () => {
  it('guides the user into the lab when there is nothing to show', async () => {
    const html = await render(TestPlansView)

    expect(has(html, 'Test Plans')).toBe(true)
    expect(has(html, 'No test plans yet')).toBe(true)
    expect(has(html, 'Open AI Test Lab')).toBe(true)
  })

  it('lists what the agent produced, with the state it is in', async () => {
    await withPlan()
    const html = await render(TestPlansView)

    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'Validate the complete Orders lifecycle')).toBe(true)
    expect(has(html, 'Draft')).toBe(true)
    expect(has(html, 'High')).toBe(true)
    // Counts come from the plan, not from a constant.
    expect(has(html, '4 Scenarios · 14 Steps · 11 Assertions')).toBe(true)
    expect(has(html, 'Generated')).toBe(true)
    expect(has(html, 'Source')).toBe(true)
  })

  it('shows every version and marks the newest one current', async () => {
    const agent = await withPlan()
    expect(agent.activePlan).not.toBeNull()

    await agent.regeneratePlan()

    const html = await render(TestPlansView)
    expect(has(html, 'Version 1')).toBe(true)
    expect(has(html, 'Version 2')).toBe(true)
    expect(has(html, 'Current')).toBe(true)
    expect(has(html, 'Runs')).toBe(true)
  })

  it('shows each approval state as it changes', async () => {
    const agent = await withPlan()
    const planId = agent.activePlan?.id ?? ''

    agent.startReview(planId)
    expect(has(await render(TestPlansView), 'In review')).toBe(true)

    agent.rejectPlan(planId, 'Not enough coverage.')
    expect(has(await render(TestPlansView), 'Rejected')).toBe(true)

    agent.approvePlan(planId)
    const approved = await render(TestPlansView)
    expect(has(approved, 'Approved')).toBe(true)
    expect(has(approved, 'Approved')).toBe(true)
  })
})

/**
 * Two plans for one project, neither produced by the agent.
 *
 * A project can only hold one plan per specification, and `applySpec` evicts
 * the plans of every other document in the project — so a second plan cannot
 * be reached through the public API today. Restoring from storage is how a
 * real user would arrive at that state (an older build, a newer one, or a
 * hand-edited entry), and it is the only way to ask the question these tests
 * exist to ask: does the list render the collection, or the active plan?
 */
const planFixture = (
  id: string,
  name: string,
  generatedAt: string,
  status: TestPlan['status'] = 'draft',
): TestPlan => ({
  id,
  projectId: 'prj_orders',
  specId: 'spec_orders',
  name: { text: name },
  goal: { text: `${name} goal` },
  riskLevel: 'medium',
  status,
  scenarios: [
    {
      id: `${id}_scenario`,
      index: 0,
      name: { text: `${name} scenario` },
      description: { text: `${name} scenario description` },
      riskLevel: 'medium',
      steps: [
        {
          id: `${id}_step`,
          index: 0,
          kind: 'request',
          description: { text: `${name} step` },
          endpointId: 'ep_get_api_orders_orderid',
          method: 'GET',
          path: '/api/orders/{orderId}',
          produces: null,
          consumes: [],
        },
      ],
      expected: { text: `${name} expected` },
      assertions: [
        {
          id: `${id}_assertion`,
          kind: 'status',
          target: 'status',
          expected: '200',
          description: { text: `${name} assertion` },
        },
      ],
    },
  ],
  source: 'generated',
  generatedAt,
  approvedAt: null,
  rejectedAt: null,
  rejectionReason: null,
})

/** Builds the stores against seeded storage, then takes the stub away. */
const restore = (plans: readonly TestPlan[]) => {
  installStorage({ 'aiata.console.agentPlans': plans })
  const agent = useAgentStore()
  removeStorage()
  return agent
}

describe('plan list', () => {
  it('renders every plan in the project, not the one that happens to be active', async () => {
    const older = planFixture('plan_older', 'Checkout smoke', '2026-01-01T00:00:00.000Z', 'approved')
    const newer = planFixture('plan_newer', 'Checkout regression', '2026-02-01T00:00:00.000Z')

    const agent = restore([older, newer])
    expect(agent.projectPlans).toHaveLength(2)
    // The store's own answer to "which plan are we looking at" is the newest.
    expect(agent.activePlan?.id).toBe('plan_newer')

    const html = await render(TestPlansView)

    // Both rows, in newest-first order. A list that rendered `activePlan`
    // would show only the second — which is what this test is for.
    expect(has(html, 'Checkout smoke')).toBe(true)
    expect(has(html, 'Checkout regression')).toBe(true)
    expect(textOf(html).indexOf('Checkout regression')).toBeLessThan(
      textOf(html).indexOf('Checkout smoke'),
    )
    expect(has(html, 'Approved')).toBe(true)
    expect(has(html, 'Draft')).toBe(true)
  })
})

describe('plan detail', () => {
  it('opens an old version by its own id after a regeneration', async () => {
    const agent = await withPlan()
    const oldId = agent.activePlan?.id ?? ''
    expect(oldId).not.toBe('')

    await agent.regeneratePlan()
    const html = await render(
      TestPlanDetailView,
      '/console/projects/prj_orders/plans/' + oldId,
    )

    expect(has(html, 'Version 1')).toBe(true)
    expect(has(html, 'Current')).toBe(false)
  })

  it('renders the plan its own url points at, not the active one', async () => {
    const older = planFixture('plan_older', 'Checkout smoke', '2026-01-01T00:00:00.000Z', 'approved')
    const newer = planFixture('plan_newer', 'Checkout regression', '2026-02-01T00:00:00.000Z')

    const agent = restore([older, newer])
    expect(agent.activePlan?.id).toBe('plan_newer')

    const html = await render(
      TestPlanDetailView,
      '/console/projects/prj_orders/plans/plan_older',
    )

    expect(has(html, 'Checkout smoke')).toBe(true)
    expect(has(html, 'Checkout smoke scenario')).toBe(true)
    // The active plan is the other one, and it must not leak onto this page.
    expect(has(html, 'Checkout regression')).toBe(false)
  })

  it('reports a missing plan id instead of throwing', async () => {
    await withPlan()

    // The detail view rendered while the router is somewhere else entirely:
    // `params.planId` is undefined rather than a string.
    const html = await render(TestPlanDetailView, '/console/projects/prj_orders/plans')

    expect(has(html, 'Test plan not found')).toBe(true)
    expect(has(html, 'Back to Test Plans')).toBe(true)
  })

  it('renders the plan the route points at', async () => {
    const agent = await withPlan()
    const planId = agent.activePlan?.id ?? ''

    const html = await render(
      TestPlanDetailView,
      `/console/projects/prj_orders/plans/${planId}`,
    )

    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'Back to Test Plans')).toBe(true)
    expect(has(html, 'User authentication')).toBe(true)
    expect(has(html, 'Scenarios')).toBe(true)
    expect(has(html, 'has to be approved before it can run')).toBe(true)
  })

  it('reports an unknown plan id instead of rendering an empty page', async () => {
    await withPlan()

    const html = await render(
      TestPlanDetailView,
      '/console/projects/prj_orders/plans/plan_does_not_exist',
    )

    expect(has(html, 'Test plan not found')).toBe(true)
    expect(has(html, 'Back to Test Plans')).toBe(true)
    expect(has(html, 'Open AI Test Lab')).toBe(true)
  })

  it('keeps the plan visible after its metadata is edited', async () => {
    const agent = await withPlan()
    const planId = agent.activePlan?.id ?? ''
    agent.approvePlan(planId)
    agent.updatePlanMeta(planId, { name: 'Checkout regression', goal: 'Cover the paid path.' })

    const html = await render(
      TestPlanDetailView,
      `/console/projects/prj_orders/plans/${planId}`,
    )

    expect(has(html, 'Checkout regression')).toBe(true)
    expect(has(html, 'Cover the paid path.')).toBe(true)
    // Metadata editing never touches the approval.
    expect(has(html, 'Approved')).toBe(true)
    expect(has(html, 'has to be approved before it can run')).toBe(false)
  })

  it('translates the page without translating the agent’s plan', async () => {
    const agent = await withPlan()
    const planId = agent.activePlan?.id ?? ''
    useLocaleStore().setLocale('zh-CN')

    const html = await render(
      TestPlanDetailView,
      `/console/projects/prj_orders/plans/${planId}`,
    )

    expect(has(html, '返回测试计划')).toBe(true)
    expect(has(html, '必须经过批准')).toBe(true)
    // The plan's own words are dictionary-authored, so they translate too.
    expect(has(html, 'Orders 生命周期验证')).toBe(true)

    useLocaleStore().setLocale('en-US')
  })
})
