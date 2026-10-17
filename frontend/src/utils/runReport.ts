/**
 * What a run report is allowed to contain, and what must never leave this file.
 *
 * The report is a projection of the *persisted run detail*: it never reads the
 * current plan, the current environment or a live response. The only input is
 * RunDetail, and every string that could have come from a request, an error or
 * a response is passed through the redaction rules below.
 */
import type { AgentEvidence, LocalizedText } from '@/types/agent'
import type { HttpMethod } from '@/types/api'
import type {
  RunAssertion,
  RunDetail,
  RunFailure,
  RunStatus,
  RunStep,
  RunStepStatus,
} from '@/types/run'
import { isTerminalRunStatus } from '@/types/run'

const REDACTED = '[redacted]'

const URL_IN_TEXT = /https?:\/\/[^\s<>"']+/gi
const BEARER = /\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi
const JWT = /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g
const API_KEY = /\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b/g
const HEADER_VALUE =
  /((?:authorization|cookie|set-cookie|x-api-key|api-key|token|password|secret)\s*[:=]\s*)([^\s,;]+)/gi
const QUERY_VALUE =
  /([?&](?:token|access_token|refresh_token|id_token|api[_-]?key|apikey|key|secret|password|passwd|pwd|authorization|cookie|session|jwt)=)[^&#\s]+/gi
const RELATIVE_URL_QUERY = /(\/[^\s?#]*\?)[^\s#]*/g

/** Strip every query value, not just the names that look sensitive. */
export const redactReportPath = (value: string | null): string | null => {
  if (value === null || value.trim() === '') return value

  const clean = value.split('#')[0] ?? value
  const query = clean.indexOf('?')

  return query >= 0 ? clean.slice(0, query) + '?[redacted]' : clean
}

/** A URL without credentials or query values; a malformed value is still scrubbed. */
export const redactReportUrl = (value: string): string => {
  if (value.trim() === '') return value

  const clean = value.split('#')[0] ?? value
  const query = clean.indexOf('?')
  const base = query >= 0 ? clean.slice(0, query) : clean

  let safe = base

  try {
    const parsed = new URL(base)
    parsed.username = ''
    parsed.password = ''
    safe = parsed.toString()
  } catch {
    // Relative paths and hand-written endpoint strings are fine as a path; the
    // query is still removed below.
  }

  return query >= 0 ? safe + '?[redacted]' : safe
}

/**
 * The one text scrubber used by the report.
 *
 * It intentionally removes values, not words: a field label such as
 * "Authorization" remains readable, while the token after it does not.
 */
export const redactReportText = (value: string): string => {
  if (value === '') return value

  let safe = value.replace(URL_IN_TEXT, (url) => redactReportUrl(url))
  safe = safe.replace(BEARER, '$1 ' + REDACTED)
  safe = safe.replace(JWT, REDACTED)
  safe = safe.replace(API_KEY, REDACTED)
  safe = safe.replace(HEADER_VALUE, '$1' + REDACTED)
  safe = safe.replace(QUERY_VALUE, '$1' + REDACTED)
  safe = safe.replace(RELATIVE_URL_QUERY, '$1[redacted]')

  return safe
}

export const redactLocalizedText = (value: LocalizedText): LocalizedText => {
  if ('text' in value) return { text: redactReportText(value.text) }

  if (value.params === undefined) return { key: value.key }

  const params = Object.fromEntries(
    Object.entries(value.params).map(([key, item]) => [
      key,
      typeof item === 'string' ? redactReportText(item) : item,
    ]),
  )

  return { key: value.key, params }
}

const safeEvidence = (evidence: AgentEvidence): AgentEvidence => ({
  label: redactLocalizedText(evidence.label),
  value: redactReportText(evidence.value),
})

const safeFailure = (failure: RunFailure | null): RunFailure | null =>
  failure === null
    ? null
    : {
        message: redactLocalizedText(failure.message),
        detail: failure.detail === null ? null : redactReportText(failure.detail),
      }

export interface ReportSummary {
  readonly scenarios: number
  readonly steps: number
  readonly assertions: number
  readonly passedSteps: number
  readonly failedSteps: number
  readonly skippedSteps: number
  readonly passedAssertions: number
  readonly failedAssertions: number
  readonly skippedAssertions: number
}

export interface ReportStep {
  readonly id: string
  readonly index: number
  readonly kind: RunStep['kind']
  readonly description: LocalizedText
  readonly method: HttpMethod | null
  readonly path: string | null
  readonly status: RunStepStatus
  readonly durationMs: number | null
  readonly failure: RunFailure | null
  readonly evidence: readonly AgentEvidence[]
}

export interface ReportAssertion {
  readonly id: string
  readonly kind: RunAssertion['kind']
  readonly target: string
  readonly expected: string
  readonly actual: string | null
  readonly status: RunAssertion['status']
  readonly description: LocalizedText
}

export interface ReportScenario {
  readonly id: string
  readonly index: number
  readonly name: LocalizedText
  readonly status: RunStepStatus
  readonly riskLevel: RunScenarioRisk
  readonly steps: readonly ReportStep[]
  readonly assertions: readonly ReportAssertion[]
}

export type RunScenarioRisk = 'low' | 'medium' | 'high'

export interface RunReport {
  readonly generatedAt: string
  readonly runId: string
  readonly projectId: string
  readonly planId: string
  readonly planName: LocalizedText
  readonly environmentId: string
  readonly baseUrl: string
  readonly status: RunStatus
  readonly createdAt: string
  readonly startedAt: string | null
  readonly finishedAt: string | null
  readonly durationMs: number | null
  readonly failure: RunFailure | null
  /** Names are counted, never printed; values are never in RunDetail at all. */
  readonly variableCount: number
  readonly summary: ReportSummary
  readonly scenarios: readonly ReportScenario[]
}

const reportStep = (step: RunStep): ReportStep => ({
  id: step.id,
  index: step.index,
  kind: step.kind,
  description: redactLocalizedText(step.description),
  method: step.method,
  path: redactReportPath(step.path),
  status: step.status,
  durationMs: step.durationMs,
  failure: safeFailure(step.failure),
  evidence: step.evidence.map(safeEvidence),
})

const reportAssertion = (assertion: RunAssertion): ReportAssertion => ({
  id: assertion.id,
  kind: assertion.kind,
  target: redactReportText(assertion.target),
  expected: redactReportText(assertion.expected),
  // A status actual is a number. Field/header actuals can be arbitrary response
  // values, including a token, so the report never prints them.
  actual:
    assertion.kind === 'status' && assertion.actual !== null
      ? redactReportText(assertion.actual)
      : null,
  status: assertion.status,
  description: redactLocalizedText(assertion.description),
})

export const buildRunReport = (detail: RunDetail, generatedAt: string): RunReport => {
  const scenarios = detail.scenarios.map((scenario) => ({
    id: scenario.id,
    index: scenario.index,
    name: redactLocalizedText(scenario.name),
    status: scenario.status,
    riskLevel: scenario.riskLevel,
    steps: scenario.steps.map(reportStep),
    assertions: scenario.assertions.map(reportAssertion),
  }))

  const allSteps = scenarios.flatMap((scenario) => scenario.steps)
  const allAssertions = scenarios.flatMap((scenario) => scenario.assertions)

  return {
    generatedAt,
    runId: detail.run.id,
    projectId: detail.run.projectId,
    planId: detail.run.planId,
    planName: redactLocalizedText(detail.run.planName),
    environmentId: detail.run.environmentId,
    baseUrl: redactReportUrl(detail.run.baseUrl),
    status: detail.run.status,
    createdAt: detail.run.createdAt,
    startedAt: detail.run.startedAt,
    finishedAt: detail.run.finishedAt,
    durationMs: detail.run.durationMs,
    failure: safeFailure(detail.run.failure),
    variableCount: detail.run.variableKeys.length,
    summary: {
      scenarios: scenarios.length,
      steps: allSteps.length,
      assertions: allAssertions.length,
      passedSteps: allSteps.filter((step) => step.status === 'passed').length,
      failedSteps: allSteps.filter((step) => step.status === 'failed').length,
      skippedSteps: allSteps.filter((step) => step.status === 'skipped').length,
      passedAssertions: allAssertions.filter((item) => item.status === 'passed').length,
      failedAssertions: allAssertions.filter((item) => item.status === 'failed').length,
      skippedAssertions: allAssertions.filter((item) => item.status === 'skipped').length,
    },
    scenarios,
  }
}

/** A report is final only for terminal run states. */
export const isReportableRun = (status: RunStatus): boolean =>
  isTerminalRunStatus(status)

/** Safe for a browser print/save filename and for a log line. */
export const reportFilename = (runId: string): string => {
  const safe = runId.trim().replace(/[^A-Za-z0-9._-]/g, '_')

  return 'ApiPilot-Run-' + (safe === '' ? 'unknown' : safe) + '.pdf'
}
