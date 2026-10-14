/**
 * Draft factories and sanitizers.
 *
 * Sanitizers exist because drafts round-trip through localStorage: the stored
 * blob is user-editable, may come from an older schema, and must degrade to a
 * usable draft rather than crash the editor that reads it. Rebuilding a valid
 * object is both safer and shorter than an exhaustive type guard.
 */

import {
  API_AUTH_TYPES,
  API_BODY_MODES,
  API_KEY_LOCATIONS,
  isHttpMethod,
  type ApiAuth,
  type ApiAuthType,
  type ApiBody,
  type ApiBodyMode,
  type ApiKeyLocation,
  type ApiKeyValue,
  type ApiRequestDraft,
} from '@/types/api'
import { createId } from './id'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback

const asBoolean = (value: unknown, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback

const oneOf = <T extends string>(
  allowed: readonly T[],
  value: unknown,
  fallback: T,
): T =>
  typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback

export const createKeyValueRow = (
  partial: Partial<Omit<ApiKeyValue, 'id'>> = {},
): ApiKeyValue => ({
  id: createId('row'),
  enabled: partial.enabled ?? true,
  key: partial.key ?? '',
  value: partial.value ?? '',
  description: partial.description ?? '',
})

export const createEmptyAuth = (): ApiAuth => ({
  type: 'none',
  bearerToken: '',
  username: '',
  password: '',
  apiKeyName: '',
  apiKeyValue: '',
  apiKeyIn: 'header',
})

export const createEmptyBody = (): ApiBody => ({ mode: 'none', text: '' })

export const createEmptyDraft = (): ApiRequestDraft => ({
  method: 'GET',
  url: '',
  params: [],
  headers: [],
  auth: createEmptyAuth(),
  body: createEmptyBody(),
})

export const sanitizeKeyValueRows = (value: unknown): readonly ApiKeyValue[] => {
  if (!Array.isArray(value)) return []

  return value.filter(isRecord).map((row) => ({
    id: typeof row.id === 'string' && row.id !== '' ? row.id : createId('row'),
    enabled: asBoolean(row.enabled, true),
    key: asString(row.key),
    value: asString(row.value),
    description: asString(row.description),
  }))
}

export const sanitizeAuth = (value: unknown): ApiAuth => {
  if (!isRecord(value)) return createEmptyAuth()

  return {
    type: oneOf<ApiAuthType>(API_AUTH_TYPES, value.type, 'none'),
    bearerToken: asString(value.bearerToken),
    username: asString(value.username),
    password: asString(value.password),
    apiKeyName: asString(value.apiKeyName),
    apiKeyValue: asString(value.apiKeyValue),
    apiKeyIn: oneOf<ApiKeyLocation>(API_KEY_LOCATIONS, value.apiKeyIn, 'header'),
  }
}

export const sanitizeBody = (value: unknown): ApiBody => {
  if (!isRecord(value)) return createEmptyBody()

  return {
    mode: oneOf<ApiBodyMode>(API_BODY_MODES, value.mode, 'none'),
    text: asString(value.text),
  }
}

export const sanitizeDraft = (value: unknown): ApiRequestDraft => {
  if (!isRecord(value)) return createEmptyDraft()

  return {
    method: isHttpMethod(value.method) ? value.method : 'GET',
    url: asString(value.url),
    params: sanitizeKeyValueRows(value.params),
    headers: sanitizeKeyValueRows(value.headers),
    auth: sanitizeAuth(value.auth),
    body: sanitizeBody(value.body),
  }
}

/**
 * Rows that will actually be sent: enabled, with a non-empty key. A blank
 * trailing row is the editor's affordance for "add another", not data.
 */
export const activeRows = (
  rows: readonly ApiKeyValue[],
): readonly ApiKeyValue[] =>
  rows.filter((row) => row.enabled && row.key.trim() !== '')

const isBlankRow = (row: ApiKeyValue | undefined): boolean =>
  row !== undefined && row.key.trim() === '' && row.value.trim() === ''

/**
 * A copy of `rows` ending in exactly one blank row.
 *
 * The trailing row is the editor's "type here to add another" affordance, so
 * the editor always has somewhere to put the caret. Two details matter:
 *
 * - The existing blank row is *kept* rather than replaced. Regenerating it on
 *   every update would swap its `id`, remounting the input and dropping the
 *   caret mid-keystroke.
 * - Only surplus blank rows are removed, so clicking "add" repeatedly cannot
 *   pile up empty rows.
 */
export const withTrailingBlank = (
  rows: readonly ApiKeyValue[],
): readonly ApiKeyValue[] => {
  const next = [...rows]

  while (
    next.length > 1 &&
    isBlankRow(next[next.length - 1]) &&
    isBlankRow(next[next.length - 2])
  ) {
    next.pop()
  }

  if (!isBlankRow(next[next.length - 1])) {
    next.push(createKeyValueRow({ enabled: false }))
  }

  return next
}
