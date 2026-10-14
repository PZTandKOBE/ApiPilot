/**
 * Mock API surface.
 *
 * This is not a stub that returns a canned object regardless of input — it is
 * a small in-memory API that *reads the request*: path params select the
 * resource, query params shape the list, and the body is validated. That
 * matters because the API Client's editors are only proven to work when
 * editing them visibly changes the response.
 *
 * Deterministic by construction: the same request always produces the same
 * reply, so a failing case can be re-run while fixing it.
 */

import type {
  ApiHeaderPair,
  ApiResponseCookie,
  HttpMethod,
} from '@/types/api'

export interface MockRequestContext {
  readonly path: string
  readonly pathParams: Readonly<Record<string, string>>
  readonly query: Readonly<Record<string, string>>
  /** Header names lower-cased. */
  readonly headers: Readonly<Record<string, string>>
  readonly body: string | null
}

export interface MockReply {
  readonly status: number
  readonly body: string
  readonly contentType?: string
  readonly headers?: readonly ApiHeaderPair[]
  readonly cookies?: readonly ApiResponseCookie[]
}

export interface MockRoute {
  readonly method: HttpMethod
  /** Segments starting with `:` capture a path parameter. */
  readonly pattern: string
  readonly respond: (context: MockRequestContext) => MockReply
}

const JSON_CONTENT_TYPE = 'application/json; charset=utf-8'

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

/** Pretty-printed on purpose: the response panel is read, not parsed. */
export const jsonReply = (
  status: number,
  payload: unknown,
  extra: Partial<MockReply> = {},
): MockReply => ({
  status,
  body: JSON.stringify(payload, null, 2),
  contentType: JSON_CONTENT_TYPE,
  ...extra,
})

const badRequest = (
  code: string,
  message: string,
  details: readonly unknown[] = [],
): MockReply =>
  jsonReply(400, {
    error: code,
    message,
    ...(details.length > 0 ? { details } : {}),
  })

/** `order_001` → `{ id, status, ... }`. Kept stable so history stays readable. */
const orderFixture = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  status: 'created',
  product_id: 'prod_001',
  quantity: 2,
  amount: 4999,
  currency: 'USD',
  created_at: '2026-09-15T09:24:00.000Z',
  ...overrides,
})

const ordersFixture = [
  orderFixture('order_001'),
  orderFixture('order_002', { status: 'paid', quantity: 1, amount: 1299 }),
  orderFixture('order_003', { status: 'shipped', quantity: 4, amount: 8800 }),
]

const parseIntOr = (value: string | undefined, fallback: number): number => {
  const parsed = Number.parseInt(value ?? '', 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

/**
 * Parse a JSON request body.
 *
 * A body that is not valid JSON is a legitimate 400 rather than a transport
 * error — the server received the bytes and rejected them, and the UI should
 * show that as a response the user can inspect.
 */
const parseBody = (
  context: MockRequestContext,
): { readonly ok: true; readonly value: Record<string, unknown> } | { readonly ok: false; readonly reply: MockReply } => {
  if (context.body === null || context.body.trim() === '') {
    return { ok: false, reply: badRequest('empty_body', 'A JSON body is required.') }
  }

  try {
    const value = JSON.parse(context.body) as unknown
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return {
        ok: false,
        reply: badRequest('invalid_body', 'Body must be a JSON object.'),
      }
    }
    return { ok: true, value: value as Record<string, unknown> }
  } catch (thrown) {
    return {
      ok: false,
      reply: badRequest(
        'invalid_json',
        thrown instanceof Error ? thrown.message : 'Malformed JSON body.',
      ),
    }
  }
}

const unauthorized = (): MockReply =>
  jsonReply(401, {
    error: 'unauthorized',
    message: 'Missing or invalid credentials.',
  })

const notFound = (resource: string, id: string): MockReply =>
  jsonReply(404, {
    error: `${resource}_not_found`,
    message: `No ${resource} with id "${id}".`,
  })

/* ------------------------------------------------------------------ *
 * Routes
 * ------------------------------------------------------------------ */

export const MOCK_ROUTES: readonly MockRoute[] = [
  /* --- Orders ---------------------------------------------------- */

  {
    method: 'GET',
    pattern: '/api/orders',
    respond: (context) => {
      const page = parseIntOr(context.query.page, 1)
      const limit = parseIntOr(context.query.limit, 20)
      const status = context.query.status

      const filtered =
        status === undefined
          ? ordersFixture
          : ordersFixture.filter((order) => order.status === status)

      const start = Math.max(0, (page - 1) * limit)

      return jsonReply(200, {
        data: filtered.slice(start, start + limit),
        page,
        limit,
        total: filtered.length,
        ...(status === undefined ? {} : { filtered_by: { status } }),
      })
    },
  },

  {
    method: 'POST',
    pattern: '/api/orders',
    respond: (context) => {
      const parsed = parseBody(context)
      if (!parsed.ok) return parsed.reply

      const { product_id: productId, quantity } = parsed.value

      if (typeof productId !== 'string' || productId.trim() === '') {
        return badRequest('validation_failed', 'Request body failed validation.', [
          {
            field: 'product_id',
            issue: 'required',
            message: 'product_id is required and must be a string.',
          },
        ])
      }

      if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity < 1) {
        return badRequest('validation_failed', 'Request body failed validation.', [
          {
            field: 'quantity',
            issue: 'out_of_range',
            message: 'quantity must be an integer greater than 0.',
          },
        ])
      }

      return jsonReply(
        201,
        orderFixture('order_001', { product_id: productId, quantity }),
        {
          headers: [{ name: 'Location', value: '/api/orders/order_001' }],
        },
      )
    },
  },

  {
    method: 'GET',
    pattern: '/api/orders/:orderId',
    respond: (context) => {
      const id = context.pathParams.orderId ?? ''

      // A dedicated status route would be overkill for one case, so a reserved
      // id exercises the 500 branch without making every id unpredictable.
      if (id === 'order_500') {
        return jsonReply(500, {
          error: 'internal_error',
          message: 'The orders service failed while loading the order.',
          request_id: 'req_8f21c4',
        })
      }

      const found = ordersFixture.find((order) => order.id === id)
      return found === undefined ? notFound('order', id) : jsonReply(200, found)
    },
  },

  {
    method: 'PUT',
    pattern: '/api/orders/:orderId',
    respond: (context) => {
      const id = context.pathParams.orderId ?? ''
      const parsed = parseBody(context)
      if (!parsed.ok) return parsed.reply

      return jsonReply(200, orderFixture(id, parsed.value))
    },
  },

  {
    method: 'PATCH',
    pattern: '/api/orders/:orderId',
    respond: (context) => {
      const id = context.pathParams.orderId ?? ''
      const parsed = parseBody(context)
      if (!parsed.ok) return parsed.reply

      const existing = ordersFixture.find((order) => order.id === id)
      if (existing === undefined) return notFound('order', id)

      return jsonReply(200, { ...existing, ...parsed.value })
    },
  },

  {
    method: 'DELETE',
    pattern: '/api/orders/:orderId',
    respond: (context) => {
      const id = context.pathParams.orderId ?? ''
      const exists = ordersFixture.some((order) => order.id === id)

      if (!exists) return notFound('order', id)

      // 204 carries no body by definition — the response panel has to render
      // that as a deliberate empty state, not as a failure.
      return { status: 204, body: '' }
    },
  },

  /* --- Auth ------------------------------------------------------ */

  {
    method: 'POST',
    pattern: '/api/auth/login',
    respond: (context) => {
      const parsed = parseBody(context)
      if (!parsed.ok) return parsed.reply

      if (parsed.value.password !== 'secret') {
        return jsonReply(401, {
          error: 'invalid_credentials',
          message: 'The email or password is incorrect.',
        })
      }

      return jsonReply(
        200,
        {
          token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.demo.signature',
          token_type: 'Bearer',
          expires_in: 3600,
        },
        {
          cookies: [
            {
              name: 'session_id',
              value: 'sess_7c1a94e2',
              domain: 'api.dev.example.com',
              path: '/',
              httpOnly: true,
              secure: true,
              expires: '2026-09-15T10:24:00.000Z',
            },
            {
              name: 'csrf_token',
              value: 'csrf_5b83f0',
              domain: 'api.dev.example.com',
              path: '/',
              httpOnly: false,
              secure: false,
              expires: '',
            },
          ],
        },
      )
    },
  },

  {
    method: 'GET',
    pattern: '/api/users/me',
    respond: (context) =>
      context.headers.authorization === undefined
        ? unauthorized()
        : jsonReply(200, {
            id: 'usr_demo',
            name: 'Demo Engineer',
            email: 'demo@example.com',
            scopes: ['orders:read', 'orders:write'],
          }),
  },

  /* --- Catalogue ------------------------------------------------- */

  {
    method: 'GET',
    pattern: '/api/products/:productId',
    respond: (context) => {
      const id = context.pathParams.productId ?? ''

      return id === 'prod_001'
        ? jsonReply(200, {
            id,
            name: 'Mechanical Keyboard',
            price: 4999,
            currency: 'USD',
            in_stock: true,
          })
        : notFound('product', id)
    },
  },

  /* --- Diagnostics ----------------------------------------------- */

  {
    // One route for exercising every error branch of the response panel,
    // instead of scattering reserved ids through the resource routes.
    method: 'GET',
    pattern: '/api/status/:code',
    respond: (context) => {
      const code = parseIntOr(context.pathParams.code, 200)

      if (code === 204) return { status: 204, body: '' }

      return jsonReply(code >= 100 && code < 600 ? code : 200, {
        requested_status: code,
        message:
          code >= 500
            ? 'The upstream service failed.'
            : code >= 400
              ? 'The request was rejected.'
              : 'OK',
      })
    },
  },
]

/** 404 for anything not in the table, so a mistyped path is visible. */
export const unmatchedReply = (method: HttpMethod, path: string): MockReply =>
  jsonReply(404, {
    error: 'route_not_found',
    message: `The mock API has no ${method} ${path} route.`,
    hint: 'Try /api/orders, /api/products/prod_001, /api/users/me or /api/status/500.',
  })
