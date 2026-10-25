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
      // The lab navigates to this real plan detail route after generation.
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

describe('analysis review', () => {
  it('does not present the previous project’s analysis after a project switch', async () => {
    await loadAndAnalyse()
    useProjectStore().selectProject('prj_payments')

    const html = await render()
    expect(has(html, 'Analysis review')).toBe(false)
    expect(has(html, 'Orders Platform API')).toBe(false)
    expect(has(html, 'Test plan ready')).toBe(false)
    expect(has(html, 'View test plan')).toBe(false)
    expect(has(html, 'Upload an API specification')).toBe(true)
  })

  it('keeps the pipeline and five-step review, then hands off to Test Plans', async () => {
    await loadAndAnalyse()
    const html = await render()

    // Main process indicator remains in its original place and meaning.
    for (const label of ['API Spec', 'Analyze', 'Understanding', 'Test Plan', 'Approve', 'Execute']) {
      expect(has(html, label)).toBe(true)
    }

    // Review navigation is a second, independent layer.
    expect(has(html, 'Analysis review')).toBe(true)
    expect(has(html, '01 / 05')).toBe(true)
    for (const label of ['API spec', 'Understanding', 'Dependencies', 'Potential risks', 'Agent actions']) {
      expect(has(html, label)).toBe(true)
    }
    expect(has(html, 'Go to test plan review')).toBe(false)
    expect(has(html, 'Next')).toBe(true)

    // The lab ends with a compact handoff, not the full plan page.
    expect(has(html, 'Test plan ready')).toBe(true)
    expect(has(html, 'View test plan')).toBe(true)
    expect(has(html, 'Regenerate plan')).toBe(true)
    expect(has(html, 'Scenarios')).toBe(false)
    expect(has(html, 'Assertions')).toBe(false)
    expect(has(html, 'Delete plan')).toBe(false)
    expect(buttonWith(html, 'Approve')).toBe('')
    expect(buttonWith(html, 'Reject')).toBe('')
    expect(buttonWith(html, 'Run test')).toBe('')
  })

  it('keeps the generation action when analysis exists without a plan', async () => {
    const agent = await loadAndAnalyse()
    const planId = agent.activePlan?.id ?? ''
    expect(planId).not.toBe('')
    expect(await agent.deletePlan('prj_orders', planId)).toBe(true)

    const html = await render()
    expect(has(html, 'Generate test plan')).toBe(true)
    expect(has(html, 'Go to test plans')).toBe(true)
    expect(has(html, 'View test plan')).toBe(false)
    expect(has(html, 'Test plan ready')).toBe(false)
  })
})

describe('the plan handoff in the rendered page', () => {
  it('offers regeneration once a plan exists', async () => {
    const agent = useAgentStore()

    await agent.loadDemoSpec()
    await agent.analyzeSpec()

    const html = await render()
    expect(has(html, 'Regenerate plan')).toBe(true)
    expect(has(html, 'Version 1')).toBe(true)
    expect(has(html, 'View test plan')).toBe(true)
  })

  it('does not expose plan approval or execution controls in the lab', async () => {
    await loadAndAnalyse()
    const html = await render()

    expect(has(html, 'Test plan ready')).toBe(true)
    expect(buttonWith(html, 'Approve')).toBe('')
    expect(buttonWith(html, 'Reject')).toBe('')
    expect(buttonWith(html, 'Run test')).toBe('')
    expect(has(html, 'has to be approved before it can run')).toBe(false)
    expect(has(html, 'Scenarios')).toBe(false)
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
    expect(has(html, '分析结果审阅')).toBe(true)
    expect(has(html, '测试计划已生成')).toBe(true)
    expect(has(html, '查看测试计划')).toBe(true)
    expect(has(html, '01 / 05')).toBe(true)
    expect(has(html, 'Agent 动作')).toBe(true)
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
