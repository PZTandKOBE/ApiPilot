/**
 * The one API base URL.
 *
 * Kept in its own module so auth configuration, guest sessions and the HTTP
 * client can share it without importing each other in a cycle.
 */

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

export const apiBaseUrl = (): string => {
  const configured: unknown = import.meta.env.VITE_API_BASE_URL
  const raw =
    typeof configured === 'string' && configured.trim() !== ''
      ? configured.trim()
      : DEFAULT_BASE_URL

  return raw.endsWith('/') ? raw.slice(0, -1) : raw
}
