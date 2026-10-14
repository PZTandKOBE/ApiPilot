import { storeToRefs } from 'pinia'

import { useLocaleStore } from '@/stores/locale'

export type { AppLocale, MessageSchema } from './types'
export type { MessageParams } from '@/stores/locale'
export { SUPPORTED_LOCALES } from './types'

/**
 * Component-facing i18n entry point.
 *
 * Intentionally a thin composable over the Pinia store rather than a full
 * i18n plugin: the dictionaries are compile-time typed, so we need no
 * runtime message compiler — just reactive lookups that re-render on switch.
 */
export const useI18n = () => {
  const store = useLocaleStore()
  const { locale, messages } = storeToRefs(store)

  return {
    locale,
    messages,
    /**
     * Translate a dot-delimited key, e.g. `t('hero.tryUs')`, optionally with
     * interpolation: `t('console.project.updated', { time: '2h ago' })`.
     */
    t: store.t,
    setLocale: store.setLocale,
    toggleLocale: store.toggleLocale,
  }
}
