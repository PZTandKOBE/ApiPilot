import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { useApiClientStore } from '@/stores/apiClient'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import { installProjectFixtures } from '../support/projects'
import AiTestLabView from '@/views/console/AiTestLabView.vue'

/**
 * Server-rendered smoke tests for the lab.
 *
 * These render the real view through its real states and assert against the
 * HTML, which is the closest thing to a browser check available without one:
 * the store, the rule engine, the dictionary and every component template are
 * all in the path. What they cannot cover is layout and pointer interaction.
 */
let router: Router

const createTestRouter = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/console/projects/:projectId/ai-test',
        name: 'console-project-ai-test',
        component: {},
      },
      {
        path: '/console/projects/:projectId/plans',
        name: 'console-project-plans',
        component: {},
      },
      // The lab renders the plan preview with `show-open-link`, which resolves
      // this route to build the "Open full plan" href. A stub without it makes
      // the fixture disagree with the route table the view is written against.
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

beforeEach(async () => {
  setActivePinia(createPinia())
  // The project store starts empty now: the lab reads `activeEnvironmentId` from
  // it, so the project it is working in is stated here rather than inherited.
  installProjectFixtures(useProjectStore())
  router = await createTestRouter()
})

const render = async (): Promise<string> => {
  const app = createSSRApp(AiTestLabView)
  app.use(router)
  // Element Plus asks for a deterministic id source under SSR; without it
  // every tooltip logs a warning. The app renders on the client, so this is
  // only here to keep the test output readable.
  app.provide(ID_INJECTION_KEY, { prefix: 1024, current: 0 })
  return renderToString(app)
}

const textOf = (html: string): string =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/\s+/g, ' ')
    .trim()

const has = (html: string, needle: string): boolean => textOf(html).includes(needle)

/** The rendered `<button>` carrying a label, for enabled/disabled checks. */
const buttonWith = (html: string, label: string): string =>
  (html.match(/<button[\s\S]*?<\/button>/g) ?? []).find((button) =>
    textOf(button).includes(label),
  ) ?? ''

const isDisabled = (button: string): boolean => /\sdisabled(?=[\s>])/.test(button)

const loadAndAnalyse = async () => {
  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  return agent
}

describe('empty state', () => {
  it('offers the one thing that can be done next', async () => {
    const html = await render()

    expect(has(html, 'AI Test Lab')).toBe(true)
    expect(has(html, 'Upload an API specification')).toBe(true)
    expect(has(html, 'Use demo API')).toBe(true)
    // No dashboard of empty panels.
    expect(has(html, 'API Understanding')).toBe(false)
    expect(has(html, 'Test plan')).toBe(false)
  })
})

describe('specification loaded', () => {
  it('shows what the parser read, not what the document claims', async () => {
    const agent = useAgentStore()
    await agent.loadDemoSpec()

    const html = await render()
    expect(has(html, 'Orders Platform API')).toBe(true)
    expect(has(html, '1.4.0')).toBe(true)
    expect(has(html, '18 Endpoints')).toBe(true)
    expect(has(html, 'Analyze API')).toBe(true)
    expect(has(html, 'API Understanding')).toBe(false)
  })
})

describe('understanding', () => {
  it('renders every derived fact', async () => {
    await loadAndAnalyse()
    const html = await render()

    expect(has(html, 'API Understanding')).toBe(true)
    for (const name of ['Auth', 'Users', 'Products', 'Orders', 'Payments']) {
      expect(has(html, name)).toBe(true)
    }
    expect(has(html, '/api/orders/{orderId}')).toBe(true)
    expect(has(html, 'bearer')).toBe(true)
    expect(has(html, 'POST /api/auth/login')).toBe(true)

    // Dependency bindings and their explanations.
    for (const binding of ['token', 'user_id', 'product_id', 'orderId']) {
      expect(has(html, binding)).toBe(true)
    }
    expect(has(html, 'cannot be called without the token issued by')).toBe(true)

    // Risks and the agent's own activity log.
    expect(has(html, 'endpoints require authentication')).toBe(true)
    expect(has(html, 'Parsed the OpenAPI 3 document')).toBe(true)
  })

  it('never puts hidden reasoning on the page', async () => {
    await loadAndAnalyse()
    const lowered = textOf(await render()).toLowerCase()

    for (const forbidden of [
      'thought',
      'reasoning',
      'chain of thought',
      'chain-of-thought',
      'internal reasoning',
      'thinking',
    ]) {
      expect(lowered).not.toContain(forbidden)
    }
  })
})

describe('the approval boundary in the rendered page', () => {
  it('keeps Run disabled until the plan is approved', async () => {
    const agent = await loadAndAnalyse()
    await agent.generatePlan()

    const draft = await render()
    expect(has(draft, 'Draft')).toBe(true)
    expect(isDisabled(buttonWith(draft, 'Run test'))).toBe(true)
    expect(has(draft, 'has to be approved before it can run')).toBe(true)

    const planId = agent.activePlan?.id ?? ''
    agent.startReview(planId)
    expect(has(await render(), 'In review')).toBe(true)
    expect(isDisabled(buttonWith(await render(), 'Run test'))).toBe(true)

    agent.rejectPlan(planId, 'Missing refund coverage.')
    const rejected = await render()
    expect(has(rejected, 'Rejected')).toBe(true)
    expect(has(rejected, 'Missing refund coverage.')).toBe(true)
    expect(isDisabled(buttonWith(rejected, 'Run test'))).toBe(true)

    agent.approvePlan(planId)
    const approved = await render()
    expect(has(approved, 'Approved')).toBe(true)
    expect(isDisabled(buttonWith(approved, 'Run test'))).toBe(false)
    expect(has(approved, 'has to be approved before it can run')).toBe(false)
  })
})

describe('API Client handoff', () => {
  it('shows the incoming request and consumes it in one action', async () => {
    const agent = useAgentStore()
    const api = useApiClientStore()

    api.setMethod('POST')
    api.setUrl('/api/orders')
    api.setHeaders([
      { id: 'h1', enabled: true, key: 'Content-Type', value: 'application/json', description: '' },
      { id: 'h2', enabled: false, key: 'X-Ignored', value: 'nope', description: '' },
    ])
    api.setBody({ mode: 'json', text: '{"product_id":"prod_001","quantity":2}' })
    api.requestAgentHandoff()

    const html = await render()
    expect(has(html, 'Request received from the API Client')).toBe(true)
    expect(has(html, 'https://api.dev.example.com/api/orders')).toBe(true)
    expect(has(html, 'Content-Type')).toBe(true)
    // A disabled row is not part of the request and is not shown as if it were.
    expect(has(html, 'X-Ignored')).toBe(false)
    expect(has(html, 'prod_001')).toBe(true)
    // The demo remains available rather than being replaced.
    expect(has(html, 'Use demo API')).toBe(true)

    await agent.adoptHandoff()
    const adopted = await render()
    expect(has(adopted, 'API Client request')).toBe(true)
    expect(has(adopted, '1 Endpoints')).toBe(true)
  })
})

describe('locale switching', () => {
  it('translates the interface but not the API author’s words', async () => {
    const locale = useLocaleStore()
    const agent = await loadAndAnalyse()
    void agent

    locale.setLocale('zh-CN')
    const html = await render()

    expect(has(html, 'AI 测试实验室')).toBe(true)
    expect(has(html, 'API 理解结果')).toBe(true)
    expect(has(html, '个接口需要认证')).toBe(true)
    expect(has(html, '就无法调用')).toBe(true)

    // Document content stays exactly as its author wrote it.
    expect(has(html, 'Orders')).toBe(true)
    expect(has(html, 'Create an order')).toBe(true)
    expect(has(html, 'API Understanding')).toBe(false)

    locale.setLocale('en-US')
    expect(has(await render(), 'API Understanding')).toBe(true)
  })
})

describe('error state', () => {
  it('reports a parse failure in the reader’s language', async () => {
    const agent = useAgentStore()
    await agent.loadSpec({ filename: 'broken.json', content: '{ not json', source: 'paste' })

    const html = await render()
    expect(has(html, 'The agent could not finish')).toBe(true)
    expect(has(html, 'The document could not be parsed')).toBe(true)
    // The technical detail is shown, but never in place of the localized line.
    expect(has(html, 'SyntaxError')).toBe(false)

    useLocaleStore().setLocale('zh-CN')
    expect(has(await render(), '文档解析失败')).toBe(true)
  })
})
