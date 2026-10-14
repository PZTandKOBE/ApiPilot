/**
 * Seed history.
 *
 * Three past sends against `prj_orders`, one of them a 404 — a history list
 * where everything succeeded would not exercise the status colouring or the
 * "this endpoint fails" signal that makes history worth keeping.
 *
 * Timestamps are relative to load time so the list reads naturally on a fresh
 * profile; they are only used until the store's first real send replaces them.
 */

import type { ApiHistoryItem } from '@/types/api'
import { CREATE_ORDER, GET_ORDER, MISSING_ORDER } from './collections'

interface HistorySeed {
  readonly id: string
  readonly status: number
  readonly timeMs: number
  readonly sizeBytes: number
  /** How long ago the send happened. */
  readonly ageMs: number
  readonly request: (typeof CREATE_ORDER)
}

const SEEDS: readonly HistorySeed[] = [
  {
    id: 'his_seed_created',
    status: 201,
    timeMs: 142,
    sizeBytes: 168,
    ageMs: 12 * 60 * 1000,
    request: CREATE_ORDER,
  },
  {
    id: 'his_seed_fetched',
    status: 200,
    timeMs: 89,
    sizeBytes: 1_240,
    ageMs: 47 * 60 * 1000,
    request: GET_ORDER,
  },
  {
    id: 'his_seed_missing',
    status: 404,
    timeMs: 73,
    sizeBytes: 96,
    ageMs: 3 * 60 * 60 * 1000,
    request: MISSING_ORDER,
  },
]

export const MOCK_HISTORY: readonly ApiHistoryItem[] = SEEDS.map((seed) => ({
  id: seed.id,
  projectId: 'prj_orders',
  method: seed.request.draft.method,
  url: seed.request.draft.url,
  status: seed.status,
  timeMs: seed.timeMs,
  sizeBytes: seed.sizeBytes,
  at: new Date(Date.now() - seed.ageMs).toISOString(),
  draft: seed.request.draft,
}))
