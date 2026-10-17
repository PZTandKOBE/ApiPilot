import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { installProjectFixtures } from '../support/projects'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import RunDetailView from '@/views/console/RunDetailView.vue'
import RunsView from '@/views/console/RunsView.vue'

/**
 * The run list and the run detail page, server-rendered.
 *
 * Each test registers its own route table. That is not tidiness: `RouterLink`
 * resolves its destination at render time, so a view rendered against a router
 * that has never heard of `console-project-run-detail` throws during render and
 * the assertion that follows would be testing the wreckage rather than the
 * page.
 *
 * The detail page is rendered after `openRun`, not by mounting it. `onMounted`
 * does not run under `renderToString`, and the load it would trigger is the
 * thing under test in the store's own spec — here the question is only whether
 * the page draws what the store already has.
 */
let router: Router

const createTestRouter = async (path: string): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/runs', name: 'console-project-runs', component: {} },
      {
        path: '/console/projects/:projectId/runs/:runId',
        name: 'console-project-run-detail',
        component: {},
      },
      { path: '/console/projects/:projectId/plans', name: 'console-project-plans', component: {} },
      {
        path: '/console/projects/:projectId/ai-test',
        name: 'console-project-ai-test',
        component: {},
      },
    ],
  })

  await instance.push(path)
  await instance.isReady()
  return instance
}

beforeEach(() => {
  setActivePinia(createPinia())
})

const render = async (component: unknown, path: string): Promise<string> => {
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

const listPath = '/console/projects/prj_orders/runs'

/** A demo plan, approved and run to completion — the way a user gets here. */
const withFinishedRun = async () => {
  const agent = useAgentStore()
  const runs = useRunsStore()

  // The store starts empty now: this spec creates runs, and a run needs an
  // environment with a base URL, so the projects it runs against are stated here.
  installProjectFixtures(useProjectStore())

  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.generatePlan()
  agent.approvePlan(agent.activePlan?.id ?? '')

  const run = await runs.createRun({ immediate: true })

  return { agent, runs, runId: run?.id ?? '' }
}

describe('run list', () => {
  it('says what is missing when there is nothing to run', async () => {
    useRunsStore()
    const html = await render(RunsView, listPath)

    expect(has(html, 'Test Runs')).toBe(true)
    expect(has(html, 'No test runs yet')).toBe(true)
    expect(has(html, 'Open AI Test Lab')).toBe(true)
    // The reason Run is unavailable is stated, not merely implied by a
    // disabled button.
    expect(has(html, 'A run needs an approved plan for a loaded specification.')).toBe(
      true,
    )
  })

  it('lists what ran, with the state it ended in', async () => {
    const { agent, runId } = await withFinishedRun()
    const html = await render(RunsView, listPath)

    expect(runId).not.toBe('')
    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'Plan ID')).toBe(true)
    // The run names the version it actually executed; a later regeneration
    // must not rewrite this row's plan id.
    expect(has(html, agent.activePlan?.id ?? '__missing__')).toBe(true)
    expect(has(html, 'Passed')).toBe(true)
    // Counts come from the run's own summary, not from a constant.
    expect(has(html, '4 Scenarios')).toBe(true)
    expect(has(html, 'Started')).toBe(true)
    expect(has(html, 'No test runs yet')).toBe(false)
  })

  it('translates the page without translating the plan’s own words', async () => {
    await withFinishedRun()
    useLocaleStore().setLocale('zh-CN')

    const html = await render(RunsView, listPath)

    expect(has(html, '测试运行')).toBe(true)
    expect(has(html, '通过')).toBe(true)
    expect(has(html, '开始于')).toBe(true)
    // What the run copied at creation is the plan's *name*, and a name the
    // dictionary authored still resolves through it — so the run keeps saying
    // the right thing about the plan even after the plan is regenerated.
    expect(has(html, 'Orders 生命周期验证')).toBe(true)

    useLocaleStore().setLocale('en-US')
    expect(has(await render(RunsView, listPath), 'Orders lifecycle validation')).toBe(
      true,
    )
  })
})

describe('run detail', () => {
  const detailPath = (runId: string) => `/console/projects/prj_orders/runs/${runId}`

  it('renders every step, every assertion and the evidence they left', async () => {
    const { runs, runId } = await withFinishedRun()
    await runs.openRun(runId, { immediate: true })

    const html = await render(RunDetailView, detailPath(runId))

    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'Back to Test Runs')).toBe(true)
    expect(has(html, 'User authentication')).toBe(true)

    // The evidence section is what separates "it passed" from "here is why
    // you should believe that".
    expect(has(html, 'Evidence')).toBe(true)
    expect(has(html, 'Requested')).toBe(true)
    expect(has(html, 'POST /api/auth/login')).toBe(true)

    // The endpoint comes from the run payload, not from the local plan.
    expect(has(html, 'GET /api/orders/{orderId}')).toBe(true)
  })

  it('reports an unknown run instead of rendering an empty page', async () => {
    // The load is driven here rather than by the view, because `onMounted`
    // does not run under `renderToString` — and the failing load is what puts
    // `run-not-found` in the store for the page to read.
    await useRunsStore().openRun('run_does_not_exist', { immediate: true })

    const html = await render(RunDetailView, detailPath('run_does_not_exist'))

    expect(has(html, 'Test run not found')).toBe(true)
    expect(has(html, 'Back to Test Runs')).toBe(true)
  })

  it('shows the environment and base url the run actually used', async () => {
    const { runs, runId } = await withFinishedRun()
    await runs.openRun(runId, { immediate: true })

    const html = await render(RunDetailView, detailPath(runId))

    expect(has(html, 'Environment')).toBe(true)
    expect(has(html, 'Base URL')).toBe(true)
    expect(has(html, 'https://api.dev.example.com')).toBe(true)
  })

  it('renders the run its own url points at, not the one opened last', async () => {
    const { agent, runs, runId } = await withFinishedRun()
    const project = useProjectStore()

    // A second run, against a different environment so the two are told apart
    // by something a reader can see. Opening it moves the store's active run
    // off the first one — which is exactly the state a page reading
    // `activeDetail` would get wrong, and does get wrong silently.
    project.selectEnvironment('env_orders_prod')
    const second = await runs.createRun({ immediate: true })
    expect(second?.id).not.toBe(runId)
    expect(runs.activeRun?.id).toBe(second?.id)

    await runs.loadRun(runId, { immediate: true })

    const html = await render(RunDetailView, detailPath(runId))
    expect(agent.activePlan?.status).toBe('approved')

    expect(has(html, 'env_orders_dev')).toBe(true)
    expect(has(html, 'env_orders_prod')).toBe(false)
  })

  it('offers no way to run anything from the page', async () => {
    const { runs, runId } = await withFinishedRun()
    await runs.openRun(runId, { immediate: true })

    const html = await render(RunDetailView, detailPath(runId))

    // A finished run cannot be cancelled, and nothing here starts one. The
    // frontend never executes — it watches.
    const buttons = html.match(/<button[\s\S]*?<\/button>/g) ?? []
    const cancel = buttons.filter((button) => textOf(button).includes('Cancel run'))

    expect(cancel).toHaveLength(1)
    expect(/\sdisabled(?=[\s>])/.test(cancel[0] ?? '')).toBe(true)
    expect(has(html, 'Run test')).toBe(false)
    expect(has(html, 'Start a run')).toBe(false)
  })
})
