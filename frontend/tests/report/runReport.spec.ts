import { describe, expect, it } from 'vitest'

import type { RunDetail, RunScenario, RunStatus, TestRun } from '@/types/run'
import {
  buildRunReport,
  isReportableRun,
  redactReportPath,
  redactReportText,
  redactReportUrl,
  reportFilename,
} from '@/utils/runReport'

const generated = '2026-10-17T12:00:00.000Z'

const run = (status: RunStatus): TestRun => ({
  id: 'run-1234',
  projectId: 'prj_orders',
  planId: 'plan_orders_v2',
  planName: { text: 'Orders lifecycle' },
  specId: 'spec_orders',
  environmentId: 'env_orders',
  baseUrl: 'https://alice:pa55@api.example.com/v1?token=super-secret-token',
  variableKeys: ['token', 'password'],
  status,
  createdAt: '2026-10-17T11:00:00.000Z',
  startedAt: '2026-10-17T11:00:01.000Z',
  finishedAt: '2026-10-17T11:00:04.000Z',
  durationMs: 3210,
  failure:
    status === 'failed'
      ? {
          message: { text: 'The request failed.' },
          detail:
            'Authorization: Bearer super-secret-token at https://api.example.com/orders?token=super-secret-token',
        }
      : null,
  summary: {
    scenarios: status === 'cancelled' ? 0 : 1,
    steps: status === 'cancelled' ? 0 : 2,
    assertions: status === 'cancelled' ? 0 : 2,
    passedSteps: status === 'passed' ? 2 : 0,
    failedSteps: status === 'failed' ? 1 : 0,
    passedAssertions: status === 'passed' ? 2 : 0,
    failedAssertions: status === 'failed' ? 2 : 0,
  },
})

const scenario = (status: RunStatus): RunScenario => ({
  id: 'scenario-1',
  index: 0,
  name: { text: '订单创建与读取：这是一个足够长的中文场景名称，用于验证报告换行。' },
  status: status === 'failed' ? 'failed' : 'passed',
  riskLevel: 'high',
  steps: [
    {
      id: 'step-1',
      scenarioId: 'scenario-1',
      index: 0,
      kind: 'request',
      description: {
        text: '创建订单并检查响应。'.repeat(30),
      },
      endpointId: 'ep_post_orders',
      method: 'POST',
      path: '/orders?token=super-secret-token',
      status: status === 'failed' ? 'failed' : 'passed',
      durationMs: 120,
      failure:
        status === 'failed'
          ? {
              message: { text: 'Request failed' },
              detail: 'Authorization: Bearer super-secret-token',
            }
          : null,
      evidence: [
        {
          label: { key: 'console.runs.evidence.endpoint' },
          value: 'POST /orders?token=super-secret-token',
        },
      ],
    },
    {
      id: 'step-2',
      scenarioId: 'scenario-1',
      index: 1,
      kind: 'extract',
      description: { text: '从创建响应中提取 orderId' },
      endpointId: 'ep_post_orders',
      method: null,
      path: null,
      status: status === 'failed' ? 'skipped' : 'passed',
      durationMs: null,
      failure: null,
      evidence: [
        {
          label: { key: 'console.runs.evidence.extracted' },
          value: 'orderId',
        },
      ],
    },
  ],
  assertions: [
    {
      id: 'assert-status',
      scenarioId: 'scenario-1',
      stepId: 'step-1',
      kind: 'status',
      target: 'status',
      expected: '201',
      actual: status === 'failed' ? '500' : '201',
      status: status === 'failed' ? 'failed' : 'passed',
      description: { text: '响应状态码为 201' },
    },
    {
      id: 'assert-field',
      scenarioId: 'scenario-1',
      stepId: 'step-1',
      kind: 'field',
      target: 'body.token',
      expected: 'present',
      actual: 'super-secret-token',
      status: status === 'failed' ? 'failed' : 'passed',
      description: { text: '响应体包含 token' },
    },
  ],
})

const detail = (status: RunStatus): RunDetail => ({
  run: run(status),
  scenarios: status === 'cancelled' ? [] : [scenario(status)],
  lastSeq: 10,
})

describe('run report projection', () => {
  it('covers passed, failed and cancelled terminal states', () => {
    const passed = buildRunReport(detail('passed'), generated)
    expect(passed.status).toBe('passed')
    expect(passed.summary.passedSteps).toBe(2)
    expect(passed.summary.passedAssertions).toBe(2)
    expect(passed.scenarios).toHaveLength(1)

    const failed = buildRunReport(detail('failed'), generated)
    expect(failed.status).toBe('failed')
    expect(failed.summary.failedSteps).toBe(1)
    expect(failed.summary.skippedSteps).toBe(1)
    expect(failed.summary.failedAssertions).toBe(2)
    expect(failed.failure?.message).toEqual({ text: 'The request failed.' })

    const cancelled = buildRunReport(detail('cancelled'), generated)
    expect(cancelled.status).toBe('cancelled')
    expect(cancelled.scenarios).toEqual([])
    expect(cancelled.summary.steps).toBe(0)
  })

  it('keeps long Chinese descriptions instead of truncating them', () => {
    const report = buildRunReport(detail('passed'), generated)
    const description = report.scenarios[0]?.steps[0]?.description

    expect(description).toEqual({
      text: '创建订单并检查响应。'.repeat(30),
    })
  })

  it('does not include credentials, tokens or variable values', () => {
    const report = buildRunReport(detail('failed'), generated)
    const serialized = JSON.stringify(report)

    expect(serialized).not.toContain('super-secret-token')
    expect(serialized).not.toContain('pa55')
    expect(report.baseUrl).not.toContain('super-secret-token')
    expect(report.baseUrl).not.toContain('pa55')
    expect(report.scenarios[0]?.steps[0]?.path).toBe('/orders?[redacted]')
    expect(report.scenarios[0]?.steps[0]?.failure?.detail).not.toContain(
      'super-secret-token',
    )
    expect(report.scenarios[0]?.assertions[1]?.actual).toBeNull()
  })

  it('handles a scenario with no assertions', () => {
    const source = detail('passed')
    const noAssertions: RunDetail = {
      ...source,
      scenarios: [{ ...(source.scenarios[0] as RunScenario), assertions: [] }],
    }
    const report = buildRunReport(noAssertions, generated)

    expect(report.scenarios[0]?.assertions).toEqual([])
    expect(report.summary.assertions).toBe(0)
    expect(report.summary.passedAssertions).toBe(0)
    expect(report.summary.failedAssertions).toBe(0)
  })

  it('omits scenario and assertion content honestly when none exists', () => {
    const report = buildRunReport(
      {
        run: { ...run('cancelled'), variableKeys: [] },
        scenarios: [],
        lastSeq: 0,
      },
      generated,
    )

    expect(report.variableCount).toBe(0)
    expect(report.scenarios).toEqual([])
    expect(report.summary.assertions).toBe(0)
  })
})

describe('report safety helpers', () => {
  it('strips every query value from paths', () => {
    expect(redactReportPath('/orders?token=secret&x=1')).toBe('/orders?[redacted]')
    expect(redactReportPath('/orders#fragment')).toBe('/orders')
    expect(redactReportPath(null)).toBeNull()
  })

  it('removes URL credentials and query values', () => {
    const safe = redactReportUrl('https://alice:pa55@api.example.com/v1?api_key=secret')

    expect(safe).not.toContain('alice')
    expect(safe).not.toContain('pa55')
    expect(safe).not.toContain('secret')
  })

  it('redacts common credential shapes in arbitrary error text', () => {
    const safe = redactReportText(
      'Authorization: Bearer abc.def.ghi Cookie: sid=secret password=pa55 token=jwt-value url=https://x.test/a?token=secret',
    )

    expect(safe).not.toContain('abc.def.ghi')
    expect(safe).not.toContain('sid=secret')
    expect(safe).not.toContain('pa55')
    expect(safe).not.toContain('jwt-value')
    expect(safe).not.toContain('secret')
    expect(safe).toContain('Authorization:')
  })

  it('produces a safe, recognizable PDF filename', () => {
    expect(reportFilename('run-1234')).toBe('ApiPilot-Run-run-1234.pdf')
    expect(reportFilename('../../etc/passwd')).toBe('ApiPilot-Run-.._.._etc_passwd.pdf')
    expect(reportFilename('')).toBe('ApiPilot-Run-unknown.pdf')
  })

  it('allows only terminal run states', () => {
    expect(isReportableRun('passed')).toBe(true)
    expect(isReportableRun('failed')).toBe(true)
    expect(isReportableRun('cancelled')).toBe(true)
    expect(isReportableRun('queued')).toBe(false)
    expect(isReportableRun('running')).toBe(false)
  })
})
