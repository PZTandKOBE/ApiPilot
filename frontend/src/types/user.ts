/**
 * Account shape.
 *
 * Mirrors what a `/api/auth/me` endpoint will return, so the auth store can
 * swap its mock implementation for a real request without any component
 * changing. Everything is readonly: state lives in the store, not in objects
 * handed around the tree.
 */

export type AuthProvider = 'github' | 'google' | 'email'

export interface User {
  readonly id: string
  readonly name: string
  readonly email: string
  /** `null` renders as initials instead of an image. */
  readonly avatarUrl: string | null
  readonly provider: AuthProvider
}

const AUTH_PROVIDERS: readonly AuthProvider[] = ['github', 'google', 'email']

/**
 * Runtime guard for values restored from localStorage.
 *
 * Persisted state is user-editable and survives deploys, so it is treated as
 * untrusted input: a stale or hand-edited blob must degrade to "signed out"
 * rather than crash the first component that reads `user.name`.
 */
export const isUser = (value: unknown): value is User => {
  if (typeof value !== 'object' || value === null) return false

  const candidate = value as Record<string, unknown>
  const provider = candidate.provider

  return (
    typeof candidate.id === 'string' &&
    typeof candidate.name === 'string' &&
    typeof candidate.email === 'string' &&
    (candidate.avatarUrl === null || typeof candidate.avatarUrl === 'string') &&
    typeof provider === 'string' &&
    AUTH_PROVIDERS.includes(provider as AuthProvider)
  )
}
