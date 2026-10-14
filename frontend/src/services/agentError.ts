/**
 * Agent failure vocabulary.
 *
 * Kept in its own module rather than in `agent.ts` so the mock implementation
 * can throw these without importing the module that imports it — the cycle
 * would work at runtime but reads as a trap.
 *
 * Every failure carries an i18n key rather than a sentence: the same error has
 * to read correctly in both locales, including after the user switches
 * language without retrying.
 */

export const AGENT_ERROR_CODES = [
  'parse-failed',
  'unsupported-format',
  'no-endpoints',
  'analyze-failed',
  'generate-failed',
  /**
   * The two the server added when the pipeline moved behind its own endpoint.
   *
   * Both are answers, not failures of the transport: `plan-exists` is the
   * server refusing to overwrite a plan it already holds for this document, and
   * `task-not-found` is an id that names nothing.  They are codes of their own
   * rather than a generic "generate-failed" because the console can say
   * something true about each.
   */
  'plan-exists',
  'task-not-found',
  /** The validator refused the plan the pipeline produced. */
  'plan-invalid',
  /**
   * The store refused before it asked the server anything.
   *
   * Every other code here is an answer from the agent service.  This one is the
   * opposite: the project a request would be scoped to could not be resolved, so
   * no request was made and nothing was written.  It exists as a code of its own
   * because "we could not tell which project this belongs to" is a different
   * sentence from "the analysis failed".
   */
  'project-not-ready',
] as const

export type AgentErrorCode = (typeof AGENT_ERROR_CODES)[number]

export interface AgentError {
  readonly code: AgentErrorCode
  readonly messageKey: string
  readonly params?: Readonly<Record<string, string | number>>
}

/**
 * Thrown by an `AgentService` implementation.
 *
 * Parser messages (from `JSON.parse` or js-yaml) are technical strings that
 * cannot be translated; they are passed through as a `{detail}` parameter so
 * the localized sentence stays intact and the exact cause stays visible.
 */
export class AgentServiceError extends Error {
  readonly detail: AgentError

  constructor(detail: AgentError) {
    super(detail.messageKey)
    this.name = 'AgentServiceError'
    this.detail = detail
  }
}

export const isAgentServiceError = (
  value: unknown,
): value is AgentServiceError => value instanceof AgentServiceError
