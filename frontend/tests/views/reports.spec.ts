import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useReportsStore } from '@/stores/reports'
import ReportsView from '@/views/console/ReportsView.vue'

let router: Router

const createTestRouter = async (): Promise<Router> => {
  const instance = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/reports', name: 'console-project-reports', component: {} },
    ],
  })
  await instance.push('/console/projects/prj_orders/reports')
  await instance.isReady()
  return instance
}

const render = async (): Promise<string> => {
  router = await createTestRouter()
  const app = createSSRApp(ReportsView)
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

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('report center', () => {
  it('lists only the saved report records supplied by its store', async () => {
    const store = useReportsStore()
    store.reports = [
      {
        id: 'report-1',
        projectId: 'prj_orders',
        runId: 'run-1234',
        name: 'ApiPilot 测试运行报告',
        filename: 'ApiPilot-Run-run-1234.pdf',
        contentType: 'application/pdf',
        byteSize: 2048,
        sha256: 'abc',
        generatedAt: '2026-10-17T12:00:00.000Z',
        runStatus: 'passed',
      },
    ]

    const html = await render()

    expect(textOf(html)).toContain('ApiPilot 测试运行报告')
    expect(textOf(html)).toContain('run-1234')
    expect(textOf(html)).toContain('Passed')
    expect(textOf(html)).toContain('Open PDF')
    expect(textOf(html)).toContain('Download')
    expect(textOf(html)).toContain('Print / Save as PDF')
  })

  it('groups the three report actions in one aligned control', async () => {
    const store = useReportsStore()
    store.reports = [
      {
        id: 'report-1',
        projectId: 'prj_orders',
        runId: 'run-1234',
        name: 'ApiPilot 测试运行报告',
        filename: 'ApiPilot-Run-run-1234.pdf',
        contentType: 'application/pdf',
        byteSize: 2048,
        sha256: 'abc',
        generatedAt: '2026-10-17T12:00:00.000Z',
        runStatus: 'passed',
      },
    ]

    const html = await render()
    const group = (html.match(/<div[^>]*data-testid="report-actions"[\s\S]*?<\/td>/g) ?? []).join('')

    expect((html.match(/data-testid="report-actions"/g) ?? [])).toHaveLength(1)
    expect(group).toContain('role="group"')
    expect(group).toContain('Open PDF')
    expect(group).toContain('Download')
    expect(group).toContain('Print / Save as PDF')
    expect(html).toContain('class="report-actions"')
  })

  it('shows the honest empty state when the server has no reports', async () => {
    useReportsStore()
    const html = await render()

    expect(textOf(html)).toContain('No saved reports yet')
    expect(textOf(html)).toContain('Open a finished run and generate its PDF report.')
  })

  it('shows the store error instead of an empty shelf', async () => {
    const store = useReportsStore()
    store.error = 'console.report.loadFailed'

    const html = await render()

    expect(textOf(html)).toContain('The saved reports could not be loaded.')
  })
})
