// @vitest-environment happy-dom
import { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createApp, nextTick, type App as VueApp } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import {
  downloadReportPdf,
  fetchReportPdf,
  listReports,
} from '@/services/api/reports'
import { useLocaleStore } from '@/stores/locale'
import { useReportsStore } from '@/stores/reports'
import ReportsView from '@/views/console/ReportsView.vue'
import type { RunReportSummary } from '@/types/report'

vi.mock('@/services/api/reports', () => ({
  listReports: vi.fn(),
  fetchReportPdf: vi.fn(),
  downloadReportPdf: vi.fn(),
}))

const REPORT: RunReportSummary = {
  id: 'report-1',
  projectId: 'prj_orders',
  runId: 'run-1234',
  name: 'ApiPilot report',
  filename: 'ApiPilot-report.pdf',
  contentType: 'application/pdf',
  byteSize: 2048,
  sha256: 'abc',
  generatedAt: '2026-10-17T12:00:00.000Z',
  runStatus: 'passed',
}

let app: VueApp | null = null
let container: HTMLDivElement | null = null
let router: Router

const flush = async (): Promise<void> => {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

const mount = async (): Promise<void> => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  useLocaleStore().setLocale('en-US')

  vi.mocked(listReports).mockResolvedValue([REPORT])
  vi.mocked(fetchReportPdf).mockResolvedValue(new Blob(['%PDF-1.4']))
  vi.mocked(downloadReportPdf).mockResolvedValue(new Blob(['%PDF-1.4']))

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/console/projects/:projectId/reports', name: 'console-project-reports', component: {} },
    ],
  })
  await router.push('/console/projects/prj_orders/reports')
  await router.isReady()

  container = document.createElement('div')
  document.body.appendChild(container)
  app = createApp(ReportsView)
  app.use(router)
  app.provide(ID_INJECTION_KEY, { prefix: 7000, current: 0 })
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 })
  app.mount(container)
  await flush()
}

const buttonByText = (text: string): HTMLButtonElement | undefined =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.trim() === text,
  )

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal('open', vi.fn(() => ({}) as Window))
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:report'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

afterEach(() => {
  app?.unmount()
  app = null
  container?.remove()
  container = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('report action group', () => {
  it('keeps the three controls together and wires each original action', async () => {
    await mount()
    const group = document.querySelector('[data-testid="report-actions"]')
    expect(group).not.toBeNull()
    expect(group?.getAttribute('role')).toBe('group')
    expect(group?.querySelectorAll('button')).toHaveLength(3)

    buttonByText('Open PDF')?.click()
    await flush()
    expect(fetchReportPdf).toHaveBeenCalledWith('prj_orders', REPORT.id)

    buttonByText('Download')?.click()
    await flush()
    expect(downloadReportPdf).toHaveBeenCalledWith('prj_orders', REPORT.id)

    buttonByText('Print / Save as PDF')?.click()
    await flush()
    expect(fetchReportPdf).toHaveBeenCalledTimes(2)

    expect(useReportsStore().reports).toHaveLength(1)
  })
})
