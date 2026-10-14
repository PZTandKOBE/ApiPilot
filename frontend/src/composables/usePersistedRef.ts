import { ref, watch, type Ref } from 'vue'

/**
 * How to treat a value read back from storage.
 *
 * Storage is user-editable and outlives any single deploy, so a restored value
 * is untrusted: without one of these, a stale blob from an older schema would
 * propagate into the app and surface as a crash far from here.
 *
 * Simple values take `validate`; complex structures take `parse`, because
 * rebuilding a valid object from unknown input is both safer and shorter than
 * an exhaustive recursive guard. `parse` wins if both are supplied.
 */
interface PersistedOptions<T> {
  /** Accepts a value read back from storage. */
  readonly validate?: (value: unknown) => value is T
  /** Rebuilds a valid value from whatever storage held. */
  readonly parse?: (value: unknown) => T
}

/**
 * A `ref` mirrored into localStorage.
 *
 * Every read and write is best-effort — private browsing and blocked storage
 * must not break the app, they only cost persistence. Same contract as the
 * locale store's own persistence.
 */
export const usePersistedRef = <T>(
  key: string,
  fallback: T,
  options: PersistedOptions<T>,
): Ref<T> => {
  const state = ref(fallback) as Ref<T>

  if (typeof window !== 'undefined') {
    try {
      const raw = window.localStorage.getItem(key)
      if (raw !== null) {
        const parsed: unknown = JSON.parse(raw)
        const { parse, validate } = options

        if (parse !== undefined) {
          state.value = parse(parsed)
        } else if (validate !== undefined && validate(parsed)) {
          state.value = parsed
        }
      }
    } catch {
      // Unreadable or malformed — keep the fallback.
    }
  }

  watch(state, (value) => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Persistence is best-effort.
    }
  })

  return state
}

/**
 * Guard factory for `usePersistedRef` when the value is simply a string from a
 * known set — the common case for "which project / environment is active".
 */
export const oneOf =
  <T extends string>(allowed: readonly T[]) =>
  (value: unknown): value is T =>
    typeof value === 'string' && (allowed as readonly string[]).includes(value)

/** Guard for a persisted id that may legitimately be absent. */
export const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === 'string'
