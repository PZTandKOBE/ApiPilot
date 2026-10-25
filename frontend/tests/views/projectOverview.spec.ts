import { renderToString } from 'vue/server-renderer'
import { createSSRApp, h } from 'vue'
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useLocaleStore } from '@/stores/locale'
import { useProjectStore } from '@/stores/project'
import ProjectOverviewView from '@/views/console/ProjectOverviewView.vue'

import { FIRST_PROJECT_FIXTURE, installProjectFixtures } from '../support/projects'

vi.mock('@/services/api/projects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api/projects')>()

  return {
    ...actual,
    getProjectSpec: vi.fn(async () => null),
  }
})

const render = async (): Promise<string> => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/console/projects/:projectId/overview',
        name: 'console-project-overview',
        component: {},
      },
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
    ],
  })
  await router.push('/console/projects/' + FIRST_PROJECT_FIXTURE.id + '/overview')
  await router.isReady()

  const app = createSSRApp({
    render: () => h(ProjectOverviewView, { projectId: FIRST_PROJECT_FIXTURE.id }),
  })
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

beforeEach(() => {
  setActivePinia(createPinia())
  installProjectFixtures(useProjectStore())
  useLocaleStore().setLocale('zh-CN')
})

describe('project overview header', () => {
  it('offers project editing and uses the current navigation names', async () => {
    const html = await render()
    const text = textOf(html)

    expect(text).toContain('编辑项目')
    expect(text).toContain('新增环境')
    expect(text).toContain('API 调试')
    expect(text).toContain('生成测试计划')
    expect(text).not.toContain('打开 API 客户端')
    expect(text).not.toContain('打开 AI 测试实验室')
  })
})
