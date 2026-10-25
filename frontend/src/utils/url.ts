/**
 * The one URL rule shared by the environment editor.
 *
 * The backend applies the same rule: an absolute http(s) URL with a host. A
 * relative path, a bare hostname or a javascript: URI cannot be the base for a
 * project's requests.
 */
export const isHttpUrl = (value: string): boolean => {
  const trimmed = value.trim()
  if (trimmed === '') return false

  try {
    const parsed = new URL(trimmed)
    return (
      (parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
      parsed.hostname !== ''
    )
  } catch {
    return false
  }
}
