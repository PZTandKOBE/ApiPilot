/**
 * Seed projects.
 *
 * Stands in for `GET /api/projects` until FastAPI is wired up. The shapes come
 * from `@/types/project`, so swapping this file for a real request is a
 * service-layer change with no UI impact.
 */

import type { Project } from '@/types/project'

export const MOCK_PROJECTS: readonly Project[] = [
  {
    id: 'prj_orders',
    name: 'My Project',
    description: 'Order lifecycle API behind the checkout flow.',
    specName: 'orders-openapi.json',
    updatedAt: '2026-09-15T09:24:00.000Z',
    environments: [
      {
        id: 'env_orders_dev',
        name: 'Development',
        kind: 'development',
        baseUrl: 'https://api.dev.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://api.dev.example.com', secret: false },
          { key: 'token', value: 'dev_2f9c41ab7e', secret: true },
          { key: 'order_id', value: 'order_001', secret: false },
        ],
      },
      {
        id: 'env_orders_staging',
        name: 'Staging',
        kind: 'staging',
        baseUrl: 'https://api.stg.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://api.stg.example.com', secret: false },
          { key: 'token', value: 'stg_88d0fe13c4', secret: true },
          { key: 'order_id', value: 'order_90021', secret: false },
        ],
      },
      {
        id: 'env_orders_prod',
        name: 'Production',
        kind: 'production',
        baseUrl: 'https://api.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://api.example.com', secret: false },
          { key: 'token', value: 'prod_5ba71c90', secret: true },
        ],
      },
    ],
  },
  {
    id: 'prj_payments',
    name: 'Payment API',
    description: 'Charges, refunds and payment-method tokenisation.',
    specName: 'payments-openapi.yaml',
    updatedAt: '2026-09-12T14:05:00.000Z',
    environments: [
      {
        id: 'env_payments_dev',
        name: 'Development',
        kind: 'development',
        baseUrl: 'https://pay.dev.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://pay.dev.example.com', secret: false },
          { key: 'api_key', value: 'sk_test_51H8x', secret: true },
        ],
      },
      {
        id: 'env_payments_prod',
        name: 'Production',
        kind: 'production',
        baseUrl: 'https://pay.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://pay.example.com', secret: false },
          { key: 'api_key', value: 'sk_live_51H8x', secret: true },
        ],
      },
    ],
  },
  {
    id: 'prj_catalog',
    name: 'E-commerce API',
    description: 'Catalogue, inventory and pricing services.',
    specName: 'catalog-openapi.json',
    updatedAt: '2026-09-08T11:30:00.000Z',
    environments: [
      {
        id: 'env_catalog_dev',
        name: 'Development',
        kind: 'development',
        baseUrl: 'https://catalog.dev.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://catalog.dev.example.com', secret: false },
          { key: 'product_id', value: 'prod_001', secret: false },
        ],
      },
    ],
  },
  {
    id: 'prj_users',
    name: 'User Service',
    description: 'Accounts, sessions and permission checks.',
    specName: null,
    updatedAt: '2026-08-29T08:10:00.000Z',
    environments: [
      {
        id: 'env_users_dev',
        name: 'Development',
        kind: 'development',
        baseUrl: 'https://users.dev.example.com',
        variables: [
          { key: 'baseUrl', value: 'https://users.dev.example.com', secret: false },
        ],
      },
    ],
  },
]

/** The project a fresh console session opens on. */
export const DEFAULT_PROJECT_ID = MOCK_PROJECTS[0].id
