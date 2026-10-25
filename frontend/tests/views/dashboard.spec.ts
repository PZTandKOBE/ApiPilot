import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import DashboardView from '@/views/console/DashboardView.vue'

import { installProjectFixtures } from '../support/projects'

/**
 * Dashboard data states.
 *
 * The page runs against the real stores and the mock services the test
 * environment selects. The three data cards have distinct sources: the agent
 * task collection, the plan list and the run list; these cases pin the empty,
 * pending, populated and failed variants so "no data" is never shown for a
 * request that has not finished or has failed.
 *
 * onMounted does not run under SSR, so the tests install state explicitly
 * before rendering. That is also what keeps the assertions deterministic: the
 * page's load path is a client concern, the render of the state is this test's.
 */
let router: Router

const createTestRouter = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/dashboard', name: 'console-dashboard', component: {} },
      { path: '/console/projects', name: 'console-projects', component: {} },
      {
        path: '/console/projects/:projectId/overview',
        name: 'console-project-overview',
        component: {},
      },
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
      {
        path: '/console/projects/:projectId/plans/:planId',
        name: 'console-project-plan-detail',
        component: {},
      },
      {
        path: '/console/projects/:projectId/runs',
        name: 'console-project-runs',
        component: {},
      },
      {
        path: '/console/projects/:projectId/runs/:runId',
        name: 'console-project-run-detail',
        component: {},
      },
    ],
  })

  await instance.push('/console/dashboard')
  await instance.isReady()
  return instance
}

const render = async (): Promise<string> => {
  router = await createTestRouter()

  const app = createSSRApp(DashboardView)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 1024, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })

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

const setup = (): void => {
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
}

const withDraftPlan = async (): Promise<void> => {
  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.loadTasks()
}

const withFinishedRun = async (): Promise<void> => {
  const agent = useAgentStore()
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.generatePlan()
  agent.approvePlan(agent.activePlan?.id ?? '')

  await useRunsStore().createRun({ immediate: true })
  await agent.loadTasks()
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('dashboard data states', () => {
  it('uses a real empty state when all three sources are loaded and empty', async () => {
    setup()
    const html = await render()

    expect(has(html, '项目总览')).toBe(true)
    expect(has(html, 'Agent 动态')).toBe(true)
    expect(has(html, '最近任务')).toBe(false)
    expect(has(html, '还没有 Agent 任务记录')).toBe(true)
    expect(has(html, '暂无待批准的计划')).toBe(true)
    expect(has(html, '暂无测试执行')).toBe(true)
  })

  it('lists a real task as Agent activity and a draft plan as awaiting approval', async () => {
    setup()
    await withDraftPlan()

    const html = await render()

    // The task card reads the task collection, not the plan list.
    expect(has(html, '设计一份测试计划')).toBe(true)
    expect(has(html, '已完成')).toBe(true)
    // The plan card is still the plan list.
    expect(has(html, 'Orders 生命周期验证')).toBe(true)
    expect(has(html, '草稿')).toBe(true)
    expect(has(html, '暂无待批准的计划')).toBe(false)
    expect(html).toContain('aria-label="删除项目"')
  })

  it('keeps an approved plan out of the pending list and shows its finished run', async () => {
    setup()
    await withFinishedRun()

    const html = await render()

    expect(has(html, 'Orders 生命周期验证')).toBe(true)
    expect(has(html, '通过')).toBe(true)
    expect(has(html, '暂无待批准的计划')).toBe(true)
    expect(has(html, '暂无测试执行')).toBe(false)
  })

  it('separates task, plan and run request failures from an empty list', async () => {
    setup()
    const agent = useAgentStore()
    const runs = useRunsStore()
    agent.tasksError = {
      code: 'analyze-failed',
      messageKey: 'console.aiTest.errors.loadFailed',
    }
    agent.plansError = {
      code: 'generate-failed',
      messageKey: 'console.aiTest.errors.loadFailed',
    }
    runs.error = {
      code: 'create-failed',
      messageKey: 'console.runs.errors.loadFailed',
    }

    const html = await render()

    expect(has(html, 'Agent 任务加载失败')).toBe(true)
    expect(has(html, '无法读取当前项目的 Agent 任务，请重试')).toBe(true)
    expect(has(html, '测试计划加载失败')).toBe(true)
    expect(has(html, '无法读取当前项目的测试计划，请重试')).toBe(true)
    expect(has(html, '测试执行加载失败')).toBe(true)
    expect(has(html, '无法读取当前项目的测试执行，请重试')).toBe(true)
    expect(has(html, 'Agent 未能完成')).toBe(false)
    expect(has(html, '运行无法继续')).toBe(false)
    expect(has(html, '还没有 Agent 任务记录')).toBe(false)
    expect(has(html, '暂无测试执行')).toBe(false)
  })

  it('shows the task activity loading state instead of an empty card', async () => {
    setup()
    useAgentStore().tasksLoading = true

    const html = await render()

    expect(html).toContain('aria-label="加载中"')
    expect(has(html, '还没有 Agent 任务记录')).toBe(false)
  })

  it('shows a loading state before project initialisation finishes', async () => {
    setup()
    useProjectStore().status = 'loading'

    const html = await render()

    expect(html).toContain('aria-label="加载中"')
    expect(has(html, '还没有 Agent 任务记录')).toBe(false)
    expect(has(html, '暂无待批准的计划')).toBe(false)
  })

  it('shows the project failure with a retry instead of an empty dashboard', async () => {
    setup()
    useProjectStore().status = 'error'

    const html = await render()

    expect(has(html, '项目加载失败')).toBe(true)
    expect(has(html, '无法读取当前项目和它关联的数据，请重试')).toBe(true)
    expect(has(html, '重试')).toBe(true)
  })
})
