import { computed, ref } from 'vue'

export type DocsTheme = 'light' | 'dark'

export const DOCS_THEME_STORAGE_KEY = 'aiata.learn.theme'

export const detectDocsTheme = (
  saved: string | null,
  prefersDark: boolean,
): DocsTheme => {
  if (saved === 'light' || saved === 'dark') return saved
  return prefersDark ? 'dark' : 'light'
}

export const systemPrefersDark = (): boolean => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return true
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export const readSavedDocsTheme = (): string | null => {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(DOCS_THEME_STORAGE_KEY)
  } catch {
    return null
  }
}

export const useDocsTheme = () => {
  const theme = ref<DocsTheme>(detectDocsTheme(readSavedDocsTheme(), systemPrefersDark()))
  const isDark = computed(() => theme.value === 'dark')

  const setTheme = (next: DocsTheme): void => {
    theme.value = next
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(DOCS_THEME_STORAGE_KEY, next)
    } catch {
      // The toggle still works in private mode; only persistence is best effort.
    }
  }

  const toggleTheme = (): void => {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, isDark, setTheme, toggleTheme }
}
