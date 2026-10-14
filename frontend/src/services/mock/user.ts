/**
 * Stand-in for the backend session endpoint.
 *
 * There is no auth server yet, so `signIn` resolves this account after a short
 * delay. The delay is deliberate: the store's action is already async, which
 * is what the real `POST /api/auth/session` will be, so the UI is built
 * against the final shape from the start.
 */

import type { AuthProvider, User } from '@/types/user'

export const MOCK_USER: User = {
  id: 'usr_demo',
  name: 'Demo Engineer',
  email: 'demo@example.com',
  avatarUrl: null,
  provider: 'github',
}

/** Simulated network latency, in milliseconds. */
export const MOCK_AUTH_LATENCY_MS = 450

export const resolveMockUser = (_provider: AuthProvider): User => MOCK_USER
