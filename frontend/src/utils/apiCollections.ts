/**
 * Sanitizers for the API Client's persisted collections and history.
 *
 * Same contract as `sanitizeDraft`: storage is untrusted, so stored values are
 * rebuilt into valid shapes rather than merely checked. Entries that cannot be
 * salvaged are dropped — one corrupt saved request must not take the whole
 * collection list with it.
 */

import { isHttpMethod, type ApiCollection, type ApiCollectionFolder, type ApiHistoryItem, type ApiSavedRequest } from '@/types/api'
import { sanitizeDraft } from './apiDraft'
import { createId } from './id'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback

const asNumber = (value: unknown, fallback: number): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

const asId = (value: unknown, prefix: string): string =>
  typeof value === 'string' && value !== '' ? value : createId(prefix)

const sanitizeSavedRequest = (value: unknown): ApiSavedRequest | null => {
  if (!isRecord(value)) return null

  const draft = sanitizeDraft(value.draft)

  return {
    id: asId(value.id, 'req'),
    // An unnamed request is useless in a list; fall back to its method + path
    // so it is at least identifiable.
    name:
      asString(value.name).trim() !== ''
        ? asString(value.name)
        : `${draft.method} ${draft.url || '/'}`,
    draft,
    savedAt: asString(value.savedAt, new Date().toISOString()),
  }
}

const sanitizeRequests = (value: unknown): readonly ApiSavedRequest[] =>
  Array.isArray(value)
    ? value
        .map(sanitizeSavedRequest)
        .filter((item): item is ApiSavedRequest => item !== null)
    : []

const sanitizeFolders = (value: unknown): readonly ApiCollectionFolder[] =>
  Array.isArray(value)
    ? value.filter(isRecord).map((folder) => ({
        id: asId(folder.id, 'fld'),
        name: asString(folder.name),
        requests: sanitizeRequests(folder.requests),
      }))
    : []

export const sanitizeCollections = (value: unknown): readonly ApiCollection[] =>
  Array.isArray(value)
    ? value.filter(isRecord).map((collection) => ({
        id: asId(collection.id, 'col'),
        projectId: asString(collection.projectId),
        name: asString(collection.name),
        folders: sanitizeFolders(collection.folders),
        requests: sanitizeRequests(collection.requests),
      }))
    : []

export const sanitizeHistory = (value: unknown): readonly ApiHistoryItem[] =>
  Array.isArray(value)
    ? value.filter(isRecord).map((item) => {
        const draft = sanitizeDraft(item.draft)

        return {
          id: asId(item.id, 'his'),
          projectId: asString(item.projectId),
          method: isHttpMethod(item.method) ? item.method : draft.method,
          url: asString(item.url, draft.url),
          status: asNumber(item.status, 0),
          timeMs: asNumber(item.timeMs, 0),
          sizeBytes: asNumber(item.sizeBytes, 0),
          at: asString(item.at, new Date().toISOString()),
          draft,
        }
      })
    : []
