/**
 * Run failure vocabulary.
 *
 * Its own module for the same reason `agentError.ts` is: the mock
 * implementation throws these, and importing them from `run.ts` would make the
 * service and its implementation import each other — a cycle that works at
 * runtime and reads as a trap.
 *
 * Every failure carries an i18n key rather than a sentence, so the same error
 * reads correctly in both locales — including after the user switches language
 * without retrying.
 */

export const RUN_ERROR_CODES = [
  'create-failed',
  'run-not-found',
  'not-approved',
  'cancel-failed',
  'stream-failed',
] as const

export type RunErrorCode = (typeof RUN_ERROR_CODES)[number]

export interface RunError {
  readonly code: RunErrorCode
  readonly messageKey: string
  readonly params?: Readonly<Record<string, string | number>>
}

/**
 * Thrown by a `RunService` implementation, and delivered to a subscriber's
 * `onError` when the stream itself fails.
 */
export class RunServiceError extends Error {
  readonly detail: RunError

  constructor(detail: RunError) {
    super(detail.messageKey)
    this.name = 'RunServiceError'
    this.detail = detail
  }
}

export const isRunServiceError = (value: unknown): value is RunServiceError =>
  value instanceof RunServiceError
