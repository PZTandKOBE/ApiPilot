/**
 * The built-in demo specification.
 *
 * A complete, ordinary OpenAPI 3.0.3 document — not a fixture with the answers
 * baked in. Everything the console shows about it (resources, authentication,
 * dependencies, risks, the test plan) is derived from this document by the
 * same rules that run on an uploaded file.
 *
 * It describes the same API the MockTransport serves, so a request composed in
 * the API Client and a scenario generated here refer to the same endpoints.
 */

export const DEMO_SPEC_FILENAME = 'orders-api.openapi.json'

export const DEMO_OPENAPI_DOCUMENT: Readonly<Record<string, unknown>> = {
  openapi: '3.0.3',

  info: {
    title: 'Orders Platform API',
    version: '1.4.0',
    description:
      'Accounts, catalogue, orders and payments for the checkout flow.',
  },

  servers: [{ url: 'https://api.example.com' }],

  security: [{ bearerAuth: [] }],

  tags: [
    { name: 'Auth', description: 'Session and credential issuance' },
    { name: 'Users', description: 'Account and identity' },
    { name: 'Products', description: 'Catalogue' },
    { name: 'Orders', description: 'Order lifecycle' },
    { name: 'Payments', description: 'Payment capture and refunds' },
  ],

  paths: {
    '/api/auth/login': {
      post: {
        tags: ['Auth'],
        summary: 'Exchange credentials for a bearer token',
        security: [],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                required: ['email', 'password'],
                properties: {
                  email: { type: 'string', format: 'email' },
                  password: { type: 'string', format: 'password' },
                },
              },
            },
          },
        },
        responses: {
          '200': {
            description: 'Token issued',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    token: { type: 'string' },
                    token_type: { type: 'string' },
                    expires_in: { type: 'integer' },
                  },
                },
              },
            },
          },
          '401': {
            description: 'Invalid credentials',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
    },

    '/api/auth/refresh': {
      post: {
        tags: ['Auth'],
        summary: 'Rotate an expiring token',
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                required: ['refresh_token'],
                properties: { refresh_token: { type: 'string' } },
              },
            },
          },
        },
        responses: {
          '200': {
            description: 'Token rotated',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: { token: { type: 'string' }, expires_in: { type: 'integer' } },
                },
              },
            },
          },
        },
      },
    },

    '/api/auth/logout': {
      post: {
        tags: ['Auth'],
        summary: 'Invalidate the current session',
        responses: { '204': { description: 'Session invalidated' } },
      },
    },

    '/api/users/me': {
      get: {
        tags: ['Users'],
        summary: 'Read the authenticated account',
        responses: {
          '200': {
            description: 'The current account',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/User' } },
            },
          },
          '401': {
            description: 'Missing or invalid credentials',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
    },

    '/api/users/{userId}': {
      get: {
        tags: ['Users'],
        summary: 'Read an account by id',
        parameters: [
          { name: 'userId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'The account',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/User' } },
            },
          },
          '404': {
            description: 'No such account',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
      patch: {
        tags: ['Users'],
        summary: 'Update an account',
        parameters: [
          { name: 'userId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                properties: { name: { type: 'string' } },
              },
            },
          },
        },
        responses: {
          '200': {
            description: 'The updated account',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/User' } },
            },
          },
        },
      },
    },

    '/api/products': {
      get: {
        tags: ['Products'],
        summary: 'List catalogue products',
        parameters: [
          { name: 'page', in: 'query', schema: { type: 'integer', minimum: 1 } },
          { name: 'limit', in: 'query', schema: { type: 'integer', minimum: 1, maximum: 100 } },
        ],
        responses: {
          '200': {
            description: 'A page of products',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    data: { type: 'array', items: { $ref: '#/components/schemas/Product' } },
                    total: { type: 'integer' },
                  },
                },
              },
            },
          },
        },
      },
    },

    '/api/products/{productId}': {
      get: {
        tags: ['Products'],
        summary: 'Read a product by id',
        parameters: [
          { name: 'productId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'The product',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Product' } },
            },
          },
          '404': {
            description: 'No such product',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
      patch: {
        tags: ['Products'],
        summary: 'Update a product',
        parameters: [
          { name: 'productId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                properties: {
                  price: { type: 'integer', minimum: 1 },
                  in_stock: { type: 'boolean' },
                },
              },
            },
          },
        },
        responses: {
          '200': {
            description: 'The updated product',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Product' } },
            },
          },
        },
      },
      delete: {
        tags: ['Products'],
        summary: 'Remove a product from the catalogue',
        parameters: [
          { name: 'productId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '204': { description: 'Product removed' },
          '404': {
            description: 'No such product',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
    },

    '/api/orders': {
      get: {
        tags: ['Orders'],
        summary: 'List orders for the current account',
        parameters: [
          { name: 'page', in: 'query', schema: { type: 'integer', minimum: 1 } },
          { name: 'limit', in: 'query', schema: { type: 'integer', minimum: 1, maximum: 100 } },
          { name: 'status', in: 'query', schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'A page of orders',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    data: { type: 'array', items: { $ref: '#/components/schemas/Order' } },
                    total: { type: 'integer' },
                  },
                },
              },
            },
          },
        },
      },
      post: {
        tags: ['Orders'],
        summary: 'Create an order',
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                required: ['product_id', 'quantity', 'user_id'],
                properties: {
                  product_id: { type: 'string' },
                  quantity: { type: 'integer', minimum: 1, maximum: 99 },
                  user_id: { type: 'string' },
                },
              },
            },
          },
        },
        responses: {
          '201': {
            description: 'Order created',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Order' } },
            },
          },
        },
      },
    },

    '/api/orders/{orderId}': {
      get: {
        tags: ['Orders'],
        summary: 'Read an order by id',
        parameters: [
          { name: 'orderId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'The order',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Order' } },
            },
          },
          '404': {
            description: 'No such order',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
      patch: {
        tags: ['Orders'],
        summary: 'Amend an order',
        parameters: [
          { name: 'orderId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                properties: { quantity: { type: 'integer', minimum: 1, maximum: 99 } },
              },
            },
          },
        },
        responses: {
          '200': {
            description: 'The amended order',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Order' } },
            },
          },
        },
      },
      delete: {
        tags: ['Orders'],
        summary: 'Cancel an order',
        parameters: [
          { name: 'orderId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '204': { description: 'Order cancelled' },
          '404': {
            description: 'No such order',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
    },

    '/api/orders/{orderId}/payment': {
      get: {
        tags: ['Payments'],
        summary: 'Read the payment attached to an order',
        parameters: [
          { name: 'orderId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'The payment',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Payment' } },
            },
          },
          '404': {
            description: 'No payment for this order',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
      post: {
        tags: ['Payments'],
        summary: 'Capture payment for an order',
        parameters: [
          { name: 'orderId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                required: ['method', 'amount'],
                properties: {
                  method: { type: 'string', enum: ['card', 'transfer'] },
                  amount: { type: 'integer', minimum: 1 },
                },
              },
            },
          },
        },
        responses: {
          '201': {
            description: 'Payment captured',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Payment' } },
            },
          },
          '409': {
            description: 'The order is not in a payable state',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Error' } },
            },
          },
        },
      },
    },

    '/api/payments/{paymentId}/refund': {
      post: {
        tags: ['Payments'],
        summary: 'Refund a captured payment',
        parameters: [
          { name: 'paymentId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                required: ['reason'],
                properties: { reason: { type: 'string' } },
              },
            },
          },
        },
        responses: {
          '201': {
            description: 'Refund issued',
            content: {
              'application/json': { schema: { $ref: '#/components/schemas/Payment' } },
            },
          },
        },
      },
    },
  },

  components: {
    securitySchemes: {
      bearerAuth: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' },
    },
    schemas: {
      User: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          name: { type: 'string' },
          email: { type: 'string', format: 'email' },
          scopes: { type: 'array', items: { type: 'string' } },
        },
      },
      Product: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          name: { type: 'string' },
          price: { type: 'integer' },
          currency: { type: 'string' },
          in_stock: { type: 'boolean' },
        },
      },
      Order: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          status: { type: 'string' },
          product_id: { type: 'string' },
          quantity: { type: 'integer' },
          amount: { type: 'integer' },
          currency: { type: 'string' },
          created_at: { type: 'string', format: 'date-time' },
        },
      },
      Payment: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          order_id: { type: 'string' },
          status: { type: 'string' },
          amount: { type: 'integer' },
        },
      },
      Error: {
        type: 'object',
        properties: {
          error: { type: 'string' },
          message: { type: 'string' },
        },
      },
    },
  },
}
