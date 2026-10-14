/**
 * Display formatting for response metrics.
 */

/**
 * `892 B`, `1.2 KB`, `3.4 MB`.
 *
 * Binary units are used deliberately: a developer comparing this against a
 * `Content-Length` header should not have to wonder which convention the UI
 * picked.
 */
export const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${Math.round(bytes)} B`

  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`

  return `${(kb / 1024).toFixed(1)} MB`
}

/** `142 ms`, `1.42 s`. */
export const formatDuration = (millis: number): string => {
  if (!Number.isFinite(millis) || millis < 0) return '—'
  if (millis < 1000) return `${Math.round(millis)} ms`

  return `${(millis / 1000).toFixed(2)} s`
}

/** Byte length of a string as UTF-8 — what actually goes over the wire. */
export const byteLength = (text: string): number =>
  new TextEncoder().encode(text).length
