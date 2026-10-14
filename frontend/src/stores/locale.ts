import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import type { AppLocale, MessageSchema } from '@/i18n/types'
import { SUPPORTED_LOCALES } from '@/i18n/types'
import { enUS } from '@/locales/en-US'
import { zhCN } from '@/locales/zh-CN'

const STORAGE_KEY = 'aiata.locale'

const DICTIONARIES: Record<AppLocale, MessageSchema> = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

const isSupported = (value: string): value is AppLocale =>
  (SUPPORTED_LOCALES as readonly string[]).includes(value)

/** Values a message can be interpolated with, e.g. `{ count: 3 }`. */
export type MessageParams = Readonly<Record<string, string | number>>

/** `{name}` placeholders in a message body. */
const PLACEHOLDER = /\{(\w+)\}/g

const interpolate = (template: string, params: MessageParams): string =>
  template.replace(PLACEHOLDER, (placeholder, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name)
      ? String(params[name])
      : placeholder,
  )

/** Saved choice wins; otherwise follow the browser, defaulting to English. */
const detectInitialLocale = (): AppLocale => {
  if (typeof window === 'undefined') return 'en-US'

  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved && isSupported(saved)) return saved
  } catch {
    // Private mode / blocked storage — fall through to detection.
  }

  const candidates = [navigator.language, ...(navigator.languages ?? [])]
  for (const candidate of candidates) {
    if (!candidate) continue
    if (isSupported(candidate)) return candidate
    // zh-Hans-CN, zh-TW, ... all collapse onto the simplified dictionary.
    if (candidate.toLowerCase().startsWith('zh')) return 'zh-CN'
    if (candidate.toLowerCase().startsWith('en')) return 'en-US'
  }

  return 'en-US'
}

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<AppLocale>(detectInitialLocale())

  const messages = computed<MessageSchema>(() => DICTIONARIES[locale.value])

  /**
   * Look up a dot-delimited key, optionally interpolating `{name}`
   * placeholders. Kept deliberately small — the dictionaries are compile-time
   * checked, so this only has to survive genuinely dynamic lookups and returns
   * the key itself as a visible fallback.
   *
   * An unmatched placeholder is left in place rather than blanked: a literal
   * `{count}` in the UI is an obvious bug report, a silently missing number is
   * not.
   */
  const t = (key: string, params?: MessageParams): string => {
    const segments = key.split('.')
    let node: unknown = messages.value

    for (const segment of segments) {
      if (typeof node !== 'object' || node === null) return key
      node = (node as Record<string, unknown>)[segment]
    }

    if (typeof node !== 'string') return key
    return params === undefined ? node : interpolate(node, params)
  }

  const setLocale = (next: AppLocale): void => {
    locale.value = next
  }

  const toggleLocale = (): void => {
    locale.value = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
  }

  watch(
    locale,
    (value) => {
      if (typeof document !== 'undefined') {
        document.documentElement.lang = value
      }
      try {
        window.localStorage.setItem(STORAGE_KEY, value)
      } catch {
        // Persistence is best-effort; the switcher still works without it.
      }
    },
    { immediate: true }
  )

  return { locale, messages, t, setLocale, toggleLocale }
})
