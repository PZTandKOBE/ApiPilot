import { watchEffect } from 'vue'
import { useRoute } from 'vue-router'

import { PROJECT_NAME } from '@/config/project'
import { useI18n } from '@/i18n'

/**
 * Keeps `document.title` in sync with the active route *and* the locale.
 *
 * Route records declare `meta.titleKey` (an i18n key) when their title is
 * translatable, and `meta.title` (a literal) when it is a product name that
 * should not be translated. Watching the locale as well as the route matters:
 * a title rendered once at navigation time would stay in the previous language
 * after the user flips the switcher.
 */
export const useDocumentTitle = (): void => {
  const route = useRoute()
  const { locale, t } = useI18n()

  watchEffect(() => {
    // Touch the locale so the effect re-runs on switch.
    const activeLocale = locale.value
    void activeLocale

    const { titleKey, title } = route.meta
    const suffix = ` · ${PROJECT_NAME}`

    if (typeof titleKey === 'string') {
      document.title = `${t(titleKey)}${suffix}`
      return
    }

    document.title = typeof title === 'string' ? title : PROJECT_NAME
  })
}
