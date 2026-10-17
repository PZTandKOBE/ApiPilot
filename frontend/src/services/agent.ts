/**
 * Agent service boundary.
 *
 * The single place that decides whether the agent runs in the browser or on the
 * server. Nothing above this line — store or component — knows which.
 *
 *   now:   Browser → FastAPI → the deterministic pipeline → a draft plan
 *   later: the same endpoint, with a model behind it instead of rules
 *
 * **The shape is a task, not three calls.** The server runs parse, analyze,
 * generate, validate and persist inside one request and answers with the task
 * the result was written into (`POST /api/projects/{id}/agent/tasks`). There
 * is no `/parse` and no `/analyze` endpoint to map the old three operations
 * onto, and inventing one in the adapter would be inventing an API -- so the
 * interface is the task, and the store adapts *that* to the screen's
 * specification → understanding → plan → approval sequence.
 *
 * The one exception is the document decoder. It is not an agent decision: it
 * turns the text the user pasted into the metadata the page draws before any
 * task exists, the backend exposes no decode endpoint, and a second decoder
 * would be a second source of truth for the slug every id is derived from.
 */

import type { AgentHandoff } from '@/types/api'
import type {
  AnalysisProgress,
  ApiAuthentication,
  ApiEndpoint,
  ApiResource,
  ApiSpec,
  ApiUnderstanding,
  SpecSource,
  TestPlan,
} from '@/types/agent'
import { AGENT_TASK_STATUSES, type AgentTaskStatus } from '@/types/agent'
import { createHttpAgentService } from './api/agent'
import { createMockAgentService } from './mock/agent'

export type { AgentError, AgentErrorCode } from './agentError'
export { AgentServiceError, isAgentServiceError } from './agentError'

/** A specification document to parse. */
export interface SpecInput {
  readonly projectId: string
  readonly filename: string
  readonly content: string
  readonly source: SpecSource
}

/**
 * A parsed document.
 *
 * Structural content is kept separate from `ApiSpec` because `ApiSpec` is what
 * gets persisted: endpoints and resources are re-derived from the document
 * text on load, so they can never drift from the file they came from.
 */
export interface ParsedSpec {
  readonly spec: ApiSpec
  readonly endpoints: readonly ApiEndpoint[]
  readonly resources: readonly ApiResource[]
  readonly authentication: ApiAuthentication
}

export interface AnalyzeOptions {
  /**
   * Called as each stage completes — the seam a future SSE stream drives
   * instead of a timer. Omit for a silent run.
   */
  readonly onProgress?: (progress: AnalysisProgress) => void
  /**
   * Skip simulated latency.
   *
   * Set when replaying a persisted document on load, where the user has
   * already watched the analysis happen and should not watch it again.
   */
  readonly immediate?: boolean
}

/**
 * A parsed document together with the text it was parsed from.
 *
 * The caller needs both: metadata to display, and the source text to persist
 * so the understanding can be recomputed on the next load.
 */
export interface LoadedSpec {
  readonly parsed: ParsedSpec
  readonly content: string
}

/**
 * Everything the server needs to run one agent task.
 *
 * The frozen `AgentTaskInput`. `variables` are write-only: the server scans
 * them for leaks and drops them, and nothing on this side persists them either.
 */
export interface AgentTaskInput {
  readonly projectId: string
  readonly specId: string
  /** The OpenAPI document's original text, not a summary of it. */
  readonly specDocument: string
  readonly environmentId: string | null
  readonly prompt: string
  readonly variables: Readonly<Record<string, string>>
  /**
   * False is the ordinary first-generation request. True asks the server to
   * create the next version of the same document's plan instead of refusing an
   * existing plan with `plan-exists`.
   */
  readonly regenerate?: boolean
}

/** Mirrors `AgentTaskStatus` in the backend's `schemas/agent.py`. */
export { AGENT_TASK_STATUSES }
export type { AgentTaskStatus }

/**
 * What one task produced.
 *
 * `understanding` is present only on the response that produced it: it is a
 * pure function of the document and the server persists none of it. `plan` is
 * read back out of the database, so a task loaded later still carries it.
 */
export interface AgentTaskResult {
  readonly taskId: string
  readonly status: AgentTaskStatus
  readonly understanding: ApiUnderstanding | null
  readonly plan: TestPlan | null
}

export interface AgentTaskOptions {
  /**
   * Called as stages complete — but only by an implementation that runs them
   * one at a time. The server answers in a single request and reports nothing,
   * so a real task shows no per-stage ticks rather than invented ones.
   */
  readonly onProgress?: (progress: AnalysisProgress) => void
  /** Skip simulated latency. The server has none to skip. */
  readonly immediate?: boolean
}

export interface AgentService {
  /** The built-in Orders API, parsed through the same path as an upload. */
  loadDemoSpec(projectId: string): Promise<LoadedSpec>

  /** Decodes and structurally parses an OpenAPI 3.x / Swagger 2.x document. */
  parseSpec(input: SpecInput): Promise<ParsedSpec>

  /**
   * Asks the agent for a plan: one task, run to completion by the server.
   *
   * Returns the task rather than a plan because that is what the endpoint
   * answers with — the plan, the understanding, and the status they were
   * written under.
   */
  runTask(input: AgentTaskInput, options?: AgentTaskOptions): Promise<AgentTaskResult>

  /** A task that already ran, as stored. */
  getTask(taskId: string): Promise<AgentTaskResult>

  /**
   * Every live plan version in a project, read from the server.
   *
   * The plan list is server-backed so version history survives a reload and a
   * different browser; the local store still owns this browser's approval
   * choices and merges them over the server's draft state.
   */
  listPlans(projectId: string): Promise<readonly TestPlan[]>
}

/** Which implementation the console gets. */
const AGENT_SERVICE_HTTP = 'http'
const AGENT_SERVICE_MOCK = 'mock'

/**
 * The agent service the console talks to.
 *
 * The real one, unless something says otherwise — the same three lines the run
 * service uses, for the same reason: `VITE_AGENT_SERVICE=mock` picks the local
 * rule engine explicitly, and the test suite gets it by default because those
 * specs drive the pipeline through known documents.
 */
const agentServiceMode = (): string => {
  const configured: unknown = import.meta.env.VITE_AGENT_SERVICE

  if (configured === AGENT_SERVICE_MOCK || configured === AGENT_SERVICE_HTTP) {
    return configured
  }

  return import.meta.env.MODE === 'test' ? AGENT_SERVICE_MOCK : AGENT_SERVICE_HTTP
}

/**
 * The agent the console talks to today: the server.
 *
 * The browser implementation is not gone — it is the mock, kept for tests, for
 * development without a backend, and as the fallback this switch names.
 */
export const createAgentService = (): AgentService =>
  agentServiceMode() === AGENT_SERVICE_MOCK ? createMockAgentService() : createHttpAgentService()

/* ------------------------------------------------------------------ *
 * API Client handoff
 * ------------------------------------------------------------------ */

const parseUrl = (value: string): URL | null => {
  try {
    return new URL(value)
  } catch {
    return null
  }
}

/** JSON type keyword for a sample value. */
const typeOfSample = (value: unknown): string => {
  if (Array.isArray(value)) return 'array'
  if (value === null) return 'string'
  switch (typeof value) {
    case 'number':
      return Number.isInteger(value) ? 'integer' : 'number'
    case 'boolean':
      return 'boolean'
    default:
      return 'string'
  }
}

/**
 * Builds a one-endpoint OpenAPI document from a request composed in the API
 * Client.
 *
 * The sample body is taken as the contract: every property it sends is
 * documented as required. That is a deliberate simplification — a bare request
 * carries no schema — and it is the assumption that makes "analyse this
 * request" produce a useful negative case rather than nothing at all.
 *
 * `title` is supplied by the caller rather than hard-coded here, so the
 * generated specification is named in the reader's language.
 */
export const documentFromHandoff = (
  handoff: AgentHandoff,
  title: string,
): string => {
  const url = parseUrl(handoff.resolved.url)
  const path = url?.pathname ?? '/request'
  const method = handoff.resolved.method.toLowerCase()

  const sample: unknown =
    handoff.resolved.body === null ? null : tryParseJson(handoff.resolved.body)

  const properties: Record<string, { type: string }> = {}
  if (typeof sample === 'object' && sample !== null && !Array.isArray(sample)) {
    for (const [key, value] of Object.entries(sample as Record<string, unknown>)) {
      properties[key] = { type: typeOfSample(value) }
    }
  }

  const hasBody = Object.keys(properties).length > 0

  const operation: Record<string, unknown> = {
    tags: ['API Client'],
    summary: title,
    responses: {
      '200': {
        description: 'Success',
        content: {
          'application/json': {
            schema: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      },
    },
  }

  if (hasBody) {
    operation.requestBody = {
      required: true,
      content: {
        'application/json': {
          schema: {
            type: 'object',
            required: Object.keys(properties),
            properties,
          },
        },
      },
    }
  }

  const auth = handoff.draft.auth
  const document: Record<string, unknown> = {
    openapi: '3.0.3',
    info: { title, version: '1.0.0' },
    paths: { [path]: { [method]: operation } },
  }

  if (auth.type === 'bearer' || auth.type === 'basic') {
    operation.security = [{ handoffAuth: [] }]
    document.components = {
      securitySchemes: {
        handoffAuth: {
          type: 'http',
          scheme: auth.type === 'bearer' ? 'bearer' : 'basic',
        },
      },
    }
  } else if (auth.type === 'apiKey' && auth.apiKeyName.trim() !== '') {
    operation.security = [{ handoffAuth: [] }]
    document.components = {
      securitySchemes: {
        handoffAuth: {
          type: 'apiKey',
          name: auth.apiKeyName,
          in: auth.apiKeyIn,
        },
      },
    }
  }

  return JSON.stringify(document, null, 2)
}

const tryParseJson = (text: string): unknown => {
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}
