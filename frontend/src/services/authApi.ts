import { apiBaseUrl } from '@/services/baseUrl'
import type { User } from '@/types/user'

export class AuthApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = 'AuthApiError'
    this.status = status
    this.code = code
  }
}

export const safeNextPath = (value: unknown, fallback = '/console'): string => {
  if (typeof value !== 'string') return fallback
  const candidate = value.trim()
  if (candidate === '' || !candidate.startsWith('/')) return fallback
  if (candidate.startsWith('//') || candidate.includes('\\')) return fallback
  return candidate.length <= 500 ? candidate : fallback
}

export const loginUrl = (provider: 'github' | 'google', next: string): string =>
  apiBaseUrl() +
  '/api/auth/login/' +
  provider +
  '?next=' +
  encodeURIComponent(safeNextPath(next))

const errorFrom = async (response: Response): Promise<AuthApiError> => {
  let code = 'auth-request-failed'
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null) {
      const candidate = (body as Record<string, unknown>).code
      if (typeof candidate === 'string' && candidate !== '') code = candidate
    }
  } catch {
    // Keep the status-only fallback.
  }
  return new AuthApiError(response.status, code)
}

export const fetchCurrentUser = async (): Promise<User | null> => {
  const response = await fetch(apiBaseUrl() + '/api/auth/me', {
    credentials: 'include',
  })
  if (response.status === 401) return null
  if (!response.ok) throw await errorFrom(response)

  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null) {
    throw new AuthApiError(500, 'auth-invalid-response')
  }
  const item = body as Record<string, unknown>
  if (
    typeof item.id !== 'string' ||
    typeof item.name !== 'string' ||
    (item.email !== null && typeof item.email !== 'string') ||
    (item.avatarUrl !== null && typeof item.avatarUrl !== 'string') ||
    (item.provider !== 'github' && item.provider !== 'google')
  ) {
    throw new AuthApiError(500, 'auth-invalid-response')
  }

  return {
    id: item.id,
    name: item.name,
    email: item.email as string | null,
    avatarUrl: item.avatarUrl as string | null,
    provider: item.provider,
  }
}

export const logoutAccount = async (): Promise<void> => {
  const response = await fetch(apiBaseUrl() + '/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
  })
  if (response.status !== 204 && !response.ok) {
    throw await errorFrom(response)
  }
}
