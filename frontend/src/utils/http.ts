/**
 * HTTP vocabulary shared by the response panel, the history list and the
 * transports.
 */

import type { HttpMethod } from '@/types/api'

const STATUS_TEXT: Readonly<Record<number, string>> = {
  200: 'OK',
  201: 'Created',
  202: 'Accepted',
  204: 'No Content',
  301: 'Moved Permanently',
  302: 'Found',
  304: 'Not Modified',
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  405: 'Method Not Allowed',
  409: 'Conflict',
  415: 'Unsupported Media Type',
  422: 'Unprocessable Entity',
  429: 'Too Many Requests',
  500: 'Internal Server Error',
  502: 'Bad Gateway',
  503: 'Service Unavailable',
  504: 'Gateway Timeout',
}

export const statusText = (status: number): string => STATUS_TEXT[status] ?? ''

/** `201 Created` — the form shown next to a response. */
export const formatStatus = (status: number): string => {
  const text = statusText(status)
  return text === '' ? String(status) : `${status} ${text}`
}

export const HTTP_STATUS_KINDS = [
  'success',
  'redirect',
  'client-error',
  'server-error',
  'unknown',
] as const

export type HttpStatusKind = (typeof HTTP_STATUS_KINDS)[number]

/**
 * Coarse class of a status code.
 *
 * Exposed as a token name rather than a colour so the caller decides how to
 * paint it — the same value is a tag in one place and a 3px rail in another.
 */
export const statusKind = (status: number): HttpStatusKind => {
  if (status >= 200 && status < 300) return 'success'
  if (status >= 300 && status < 400) return 'redirect'
  if (status >= 400 && status < 500) return 'client-error'
  if (status >= 500 && status < 600) return 'server-error'
  return 'unknown'
}

/** CSS colour token for a status code. */
export const statusColor = (status: number): string => {
  switch (statusKind(status)) {
    case 'success':
      return 'var(--status-pass)'
    case 'redirect':
      return 'var(--accent)'
    case 'client-error':
      return 'var(--status-warn)'
    case 'server-error':
      return 'var(--status-fail)'
    default:
      return 'var(--console-text-muted)'
  }
}

/**
 * Method colours.
 *
 * Restrained on purpose: these are 10px labels, so the colour is a hint at the
 * edge of perception, not a block of ink. GET reads as safe, POST as "this
 * changes something", DELETE as destructive — the same instinct the status
 * colours already establish.
 */
export const methodColor = (method: HttpMethod): string => {
  switch (method) {
    case 'GET':
      return 'var(--status-pass)'
    case 'POST':
      return 'var(--status-warn)'
    case 'PUT':
      return 'var(--accent)'
    case 'PATCH':
      return 'var(--accent-soft)'
    case 'DELETE':
      return 'var(--status-fail)'
  }
}
