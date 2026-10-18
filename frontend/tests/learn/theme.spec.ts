import { afterEach, describe, expect, it } from 'vitest'

import {
  detectDocsTheme,
  useDocsTheme,
} from '@/composables/useDocsTheme'

const originalWindow = (globalThis as { window?: unknown }).window

afterEach(() => {
  if (originalWindow === undefined) {
    delete (globalThis as { window?: unknown }).window
  } else {
    ;(globalThis as { window?: unknown }).window = originalWindow
  }
})

describe('Learn Us theme', () => {
  it('honours saved choice before the system preference', () => {
    expect(detectDocsTheme('light', true)).toBe('light')
    expect(detectDocsTheme('dark', false)).toBe('dark')
    expect(detectDocsTheme(null, true)).toBe('dark')
    expect(detectDocsTheme(null, false)).toBe('light')
    expect(detectDocsTheme('invalid', false)).toBe('light')
  })

  it('toggles theme and persists only an explicit choice', () => {
    const values = new Map<string, string>()
    const fakeWindow = {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
      matchMedia: () => ({ matches: true }),
    }
    ;(globalThis as { window?: unknown }).window = fakeWindow

    const { theme, toggleTheme } = useDocsTheme()
    expect(theme.value).toBe('dark')
    expect(values.size).toBe(0)

    toggleTheme()
    expect(theme.value).toBe('light')
    expect(values.get('aiata.learn.theme')).toBe('light')

    toggleTheme()
    expect(theme.value).toBe('dark')
    expect(values.get('aiata.learn.theme')).toBe('dark')
  })
})
