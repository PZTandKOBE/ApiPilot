/**
 * Seed collections.
 *
 * Ships a working set of requests so the API Client is usable the moment it
 * opens, and — more importantly — so the mock API's surface is discoverable
 * without reading its source. Every seeded request resolves against the routes
 * in `./responses`.
 *
 * Saved against `prj_orders` (and one other) rather than every project: an
 * empty collection list is a real state the UI has to handle, and leaving some
 * projects unseeded is how that state stays exercised.
 */

import type {
  ApiAuth,
  ApiBodyMode,
  ApiCollection,
  ApiRequestDraft,
  ApiSavedRequest,
  HttpMethod,
} from '@/types/api'
import { createEmptyAuth, createKeyValueRow } from '@/utils/apiDraft'

/** `[key, value, description?]` — compact enough to read as a table. */
type RowSeed = readonly [string, string, string?]

interface DraftSeed {
  readonly method: HttpMethod
  readonly url: string
  readonly params?: readonly RowSeed[]
  readonly headers?: readonly RowSeed[]
  readonly auth?: Partial<ApiAuth>
  readonly bodyMode?: ApiBodyMode
  readonly body?: string
}

const SEEDED_AT = '2026-09-15T09:24:00.000Z'

const toRows = (seeds: readonly RowSeed[] | undefined) =>
  (seeds ?? []).map(([key, value, description]) =>
    createKeyValueRow({ enabled: true, key, value, description: description ?? '' }),
  )

const buildDraft = (seed: DraftSeed): ApiRequestDraft => ({
  method: seed.method,
  url: seed.url,
  params: toRows(seed.params),
  headers: toRows(seed.headers),
  auth: { ...createEmptyAuth(), ...seed.auth },
  body: { mode: seed.bodyMode ?? 'none', text: seed.body ?? '' },
})

const savedRequest = (
  id: string,
  name: string,
  seed: DraftSeed,
): ApiSavedRequest => ({
  id,
  name,
  draft: buildDraft(seed),
  savedAt: SEEDED_AT,
})

const BEARER_TOKEN: Partial<ApiAuth> = {
  type: 'bearer',
  bearerToken: '{{token}}',
}

const CREATE_ORDER_BODY = `{
  "product_id": "prod_001",
  "quantity": 2
}`

export const LIST_ORDERS = savedRequest('req_orders_list', 'List orders', {
  method: 'GET',
  url: '/api/orders',
  params: [
    ['page', '1', 'page number'],
    ['limit', '20', 'page size'],
  ],
  headers: [['Accept', 'application/json']],
})

export const CREATE_ORDER = savedRequest('req_orders_create', 'Create order', {
  method: 'POST',
  url: '/api/orders',
  headers: [['Content-Type', 'application/json']],
  auth: BEARER_TOKEN,
  bodyMode: 'json',
  body: CREATE_ORDER_BODY,
})

export const GET_ORDER = savedRequest('req_orders_get', 'Get order', {
  method: 'GET',
  url: '/api/orders/{{order_id}}',
  auth: BEARER_TOKEN,
})

const DELETE_ORDER = savedRequest('req_orders_delete', 'Delete order', {
  method: 'DELETE',
  url: '/api/orders/{{order_id}}',
  auth: BEARER_TOKEN,
})

const LOGIN = savedRequest('req_auth_login', 'Sign in', {
  method: 'POST',
  url: '/api/auth/login',
  headers: [['Content-Type', 'application/json']],
  bodyMode: 'json',
  body: `{
  "email": "demo@example.com",
  "password": "secret"
}`,
})

const CURRENT_USER = savedRequest('req_auth_me', 'Current user', {
  method: 'GET',
  url: '/api/users/me',
  auth: BEARER_TOKEN,
})

const GET_PRODUCT = savedRequest('req_catalog_product', 'Get product', {
  method: 'GET',
  url: '/api/products/{{product_id}}',
})

export const MOCK_COLLECTIONS: readonly ApiCollection[] = [
  {
    id: 'col_orders',
    projectId: 'prj_orders',
    name: 'Orders',
    folders: [],
    requests: [LIST_ORDERS, CREATE_ORDER, GET_ORDER, DELETE_ORDER],
  },
  {
    id: 'col_auth',
    projectId: 'prj_orders',
    name: 'Auth',
    // A folder level, so the panel's nesting is exercised by the seed data
    // rather than only by collections the user creates.
    folders: [
      { id: 'fld_sessions', name: 'Sessions', requests: [LOGIN, CURRENT_USER] },
    ],
    requests: [],
  },
  {
    id: 'col_diagnostics',
    projectId: 'prj_orders',
    name: 'Diagnostics',
    folders: [],
    requests: [
      // The error branches the response panel has to render correctly.
      savedRequest('req_diag_401', '401 Unauthorized', {
        method: 'GET',
        url: '/api/status/401',
      }),
      savedRequest('req_diag_500', '500 Server error', {
        method: 'GET',
        url: '/api/status/500',
      }),
      savedRequest('req_diag_204', '204 No content', {
        method: 'GET',
        url: '/api/status/204',
      }),
    ],
  },
  {
    id: 'col_catalogue',
    projectId: 'prj_catalog',
    name: 'Catalogue',
    folders: [],
    requests: [GET_PRODUCT],
  },
]

/** A one-off request used only by the history seed. */
export const MISSING_ORDER = savedRequest('his_req_missing', 'Get order', {
  method: 'GET',
  url: '/api/orders/order_999',
})
