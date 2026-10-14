import { MOCK_COLLECTIONS } from '@/services/mock/collections'
import { MOCK_HISTORY } from '@/services/mock/history'
import type { ApiCollection, ApiHistoryItem } from '@/types/api'
import { createEmptyDraft } from '@/utils/apiDraft'

/**
 * API Client data for tests that need some.
 *
 * The store no longer starts with these: a console that opened with sample
 * collections and a sample history would be showing a new user somebody else's
 * requests — saved against a project the guest does not own — as though they
 * were theirs.  So a test that wants a non-empty list states it, which is the
 * point: the data an assertion is about is visible in the test rather than
 * implied by the store's defaults.
 *
 * The values are the old seeds, still the handiest set of well-formed fixtures in
 * the repository (a collection named "Orders", requests across several methods,
 * history with a 404 in it so status colouring has something to colour).  They
 * are *fixtures* now: nothing in \`src/\` reads them as a starting state.
 */
export const COLLECTION_FIXTURES: readonly ApiCollection[] = MOCK_COLLECTIONS

export const HISTORY_FIXTURES: readonly ApiHistoryItem[] = MOCK_HISTORY

/** One collection with one request, belonging to \`projectId\`. */
export const buildCollection = (
  id: string,
  projectId: string,
  name = 'Saved',
): ApiCollection => ({
  id,
  projectId,
  name,
  folders: [],
  requests: [
    {
      id: id + '_req',
      name: name + ' request',
      draft: { ...createEmptyDraft(), method: 'GET', url: '/api/' + id },
      savedAt: '2026-10-09T00:00:00.000Z',
    },
  ],
})

/** One history row belonging to \`projectId\`. */
export const buildHistoryItem = (
  id: string,
  projectId: string,
  url = '/api/orders',
): ApiHistoryItem => ({
  id,
  projectId,
  method: 'GET',
  url,
  status: 200,
  timeMs: 10,
  sizeBytes: 20,
  at: '2026-10-09T00:00:00.000Z',
  draft: { ...createEmptyDraft(), method: 'GET', url },
})
