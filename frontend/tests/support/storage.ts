/**
 * A `window` with just enough `localStorage` to seed persisted state.
 *
 * Tests run in the `node` environment on purpose — nothing here needs a DOM —
 * so `usePersistedRef` short-circuits and every store starts from its fallback.
 * That is the right default, but it leaves one question unaskable: *what does
 * the app do with state it did not just write?* Storage is user-editable and
 * outlives a deploy, so that is exactly the case worth covering.
 *
 * The stub is installed, the stores are built (they read once, at setup), and
 * then it is removed — the render that follows runs in the same window-less
 * environment as every other test, and nothing downstream can tell the
 * difference. Writes after removal are already swallowed by the stores' own
 * `try`/`catch`, which is what makes this safe rather than merely tidy.
 *
 * The locale is seeded too, and not incidentally: `detectInitialLocale` reads
 * `navigator.language` the moment a `window` exists, and Node reports the
 * machine's own locale. Without the seed, every English assertion in a seeding
 * test would fail on a Chinese machine and pass on an English one.
 */
const cells = new Map<string, string>()

/**
 * `globalThis` as a bag of globals.
 *
 * Not `globalThis & { window?: unknown }`: the DOM lib declares `window` as a
 * required property, and an intersection cannot make it optional. Nothing here
 * is meant to satisfy the DOM's `Window` — the stub is deliberately four
 * properties wide, and widening it would be a jsdom dependency in disguise.
 */
const globals = globalThis as unknown as Record<string, unknown>

/**
 * Seeds storage under `window.localStorage`, replacing anything a previous
 * test left behind.
 *
 * Values are serialised here, so callers pass the objects they would have
 * seen in storage rather than strings they would have to remember to escape.
 */
export const installStorage = (seed: Readonly<Record<string, unknown>>): void => {
  cells.clear()
  // A bare string, not JSON: the locale store writes the language code on its
  // own, and `usePersistedRef` is what JSON-encodes everything else.
  cells.set('aiata.locale', 'en-US')

  for (const [key, value] of Object.entries(seed)) {
    cells.set(key, JSON.stringify(value))
  }

  globals.window = {
    localStorage: {
      getItem: (key: string): string | null => cells.get(key) ?? null,
      setItem: (key: string, value: string): void => {
        cells.set(key, String(value))
      },
      removeItem: (key: string): void => {
        cells.delete(key)
      },
      clear: (): void => {
        cells.clear()
      },
      key: (index: number): string | null => [...cells.keys()][index] ?? null,
      get length(): number {
        return cells.size
      },
    },
  }
}

/** Puts the environment back the way every other test expects to find it. */
export const removeStorage = (): void => {
  delete globals.window
  cells.clear()
}
