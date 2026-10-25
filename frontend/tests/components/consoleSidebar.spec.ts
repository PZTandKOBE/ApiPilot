import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import ConsoleSidebar from '@/components/console/ConsoleSidebar.vue'
import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'

import { installProjectFixtures } from '../support/projects'

/**
 * The primary rail's labels.
 *
 * The rail is rendered through its real component and the real navigation
 * resolver, because the bug this protects against is not a wrong dictionary
 * string: it is a label that is still paired with an explanatory second line,
 * or a route name that no longer resolves. Both would survive a dictionary-only
 * assertion.
 */
const createTestRouter = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/dashboard', name: 'console-dashboard', component: {} },
      { path: '/console/projects', name: 'console-projects', component: {} },
      {
        path: '/console/projects/:projectId/api',
        name: 'console-project-api',
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
        path: '/console/projects/:projectId/runs',
        name: 'console-project-runs',
        component: {},
      },
      {
        path: '/console/projects/:projectId/reports',
        name: 'console-project-reports',
        component: {},
      },
    ],
  })

  await instance.push('/console/dashboard')
  await instance.isReady()
  return instance
}

const render = async (): Promise<string> => {
  const router = await createTestRouter()
  const app = createSSRApp(ConsoleSidebar)
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

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
})

describe('console sidebar navigation', () => {
  it('uses the direct Chinese labels and drops the explanatory subtitles', async () => {
    const html = await render()

    expect(has(html, '项目总览')).toBe(true)
    expect(has(html, 'API 调试')).toBe(true)
    expect(has(html, '生成测试计划')).toBe(true)
    expect(has(html, '测试执行')).toBe(true)
    expect(has(html, '测试报告')).toBe(true)
    // The product removed these two visible destinations from the sidebar.
    expect(has(html, '工作流')).toBe(false)
    expect(has(html, '设置')).toBe(false)
    // The footer collapse control is still present and usable.
    expect(has(html, '收起侧边栏')).toBe(true)
    expect(has(html, '仪表盘')).toBe(false)
    expect(has(html, 'API 客户端')).toBe(false)
    expect(has(html, 'AI 测试实验室')).toBe(false)
    expect(has(html, '手动构造并发送请求')).toBe(false)
    expect(has(html, '由 Agent 分析规范并生成计划')).toBe(false)
    expect(html).toContain('aria-current="page"')
  })

  it('keeps the same direct labels in English', async () => {
    useLocaleStore().setLocale('en-US')
    const html = await render()

    expect(has(html, 'Project overview')).toBe(true)
    expect(has(html, 'API debug')).toBe(true)
    expect(has(html, 'Generate test plan')).toBe(true)
    expect(has(html, 'Test Runs')).toBe(true)
    expect(has(html, 'Reports')).toBe(true)
    expect(has(html, 'Workflows')).toBe(false)
    expect(has(html, 'Settings')).toBe(false)
    expect(has(html, 'Collapse sidebar')).toBe(true)
    expect(has(html, 'Dashboard')).toBe(false)
    expect(has(html, 'API Client')).toBe(false)
    expect(has(html, 'AI Test Lab')).toBe(false)
    expect(has(html, 'Send requests by hand')).toBe(false)
  })
})
