import { readFileSync } from 'node:fs'

import { renderToString } from 'vue/server-renderer'
import { createSSRApp } from 'vue'
import { ID_INJECTION_KEY } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import { installProjectFixtures } from '../support/projects'
import RunReportView from '@/views/console/RunReportView.vue'

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
      {
        path: '/console/projects/:projectId/runs/:runId/report',
        name: 'console-project-run-report',
        component: {},
      },
      {
        path: '/console/projects/:projectId/reports',
        name: 'console-project-reports',
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

const render = async (path: string): Promise<string> => {
  router = await createTestRouter(path)
  const app = createSSRApp(RunReportView)
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

const withFinishedRun = async () => {
  const agent = useAgentStore()
  const runs = useRunsStore()

  installProjectFixtures(useProjectStore())
  await agent.loadDemoSpec()
  await agent.analyzeSpec()
  await agent.generatePlan()
  agent.approvePlan(agent.activePlan?.id ?? '')
  const run = await runs.createRun({ immediate: true })
  const runId = run?.id ?? ''
  await runs.openRun(runId, { immediate: true })

  return { runs, runId }
}

const reportPath = (runId: string): string =>
  '/console/projects/prj_orders/runs/' + runId + '/report'

describe('run report page', () => {
  it('renders a printable report from the saved run detail', async () => {
    const { runId } = await withFinishedRun()
    const html = await render(reportPath(runId))

    expect(has(html, 'Test run report')).toBe(true)
    expect(has(html, 'Run summary')).toBe(true)
    expect(has(html, 'Execution detail')).toBe(true)
    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'Print / Save as PDF')).toBe(true)
    expect(has(html, 'Generate & save PDF')).toBe(true)
    expect(has(html, runId)).toBe(true)
    expect(has(html, 'Scope and limitations')).toBe(true)
    expect(has(html, 'This report uses only the run data saved by ApiPilot.')).toBe(true)
  })

  it('offers the print flow without claiming an automatic download', async () => {
    const { runId } = await withFinishedRun()
    const html = await render(reportPath(runId))
    const text = textOf(html)

    expect(text).toContain('browser print dialog')
    expect(text).toContain('not downloaded automatically')
  })

  it('keeps the historical run fields after the live plan and environment change', async () => {
    const { runId } = await withFinishedRun()
    const agent = useAgentStore()
    const project = useProjectStore()

    // Remove the live plan and switch the selected environment. Neither is an
    // input to the report: the saved run detail is.
    agent.resetSpec()
    project.selectEnvironment('env_orders_prod')

    const html = await render(reportPath(runId))

    expect(has(html, 'Orders lifecycle validation')).toBe(true)
    expect(has(html, 'https://api.dev.example.com')).toBe(true)
    expect(has(html, 'https://api.example.com')).toBe(false)
  })

  it('refuses an unfinished run even when the report URL is opened directly', async () => {
    const agent = useAgentStore()
    const runs = useRunsStore()

    installProjectFixtures(useProjectStore())
    await agent.loadDemoSpec()
    await agent.analyzeSpec()
    await agent.generatePlan()
    agent.approvePlan(agent.activePlan?.id ?? '')
    const run = await runs.createRun({ immediate: false })
    await runs.openRun(run?.id ?? '', { immediate: true })

    const html = await render(reportPath(run?.id ?? ''))

    expect(has(html, 'Report unavailable while this run is unfinished')).toBe(true)
    expect(has(html, 'A PDF report is available after the run reaches passed, failed or cancelled.')).toBe(
      true,
    )
  })
})

describe('report print stylesheet', () => {
  it('keeps pagination, table headers, counter support and a CJK font stack', () => {
    const css = readFileSync(
      new URL('../../src/styles/report.css', import.meta.url),
      'utf8',
    )

    expect(css).toContain('@media print')
    expect(css).toContain('@page')
    expect(css).toContain('counter(page)')
    expect(css).toContain('break-inside: avoid')
    expect(css).toContain('table-header-group')
    expect(css).toContain('Microsoft YaHei')
    expect(css).toContain('overflow-wrap: anywhere')
  })
})
