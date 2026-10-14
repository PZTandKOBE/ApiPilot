import { useI18n } from '@/i18n'
import { isLocalizedMessage, type LocalizedText } from '@/types/agent'

export interface LocalizedTextResolver {
  /**
   * Renders a `LocalizedText`.
   *
   * Authored values resolve through the dictionary, so they follow the
   * language switcher. Values that came out of a document or a model are
   * shown exactly as received — translating someone else's prose is not this
   * function's job.
   */
  readonly localize: (value: LocalizedText) => string
}

export const useLocalizedText = (): LocalizedTextResolver => {
  const { t } = useI18n()

  const localize = (value: LocalizedText): string =>
    isLocalizedMessage(value) ? t(value.key, value.params) : value.text

  return { localize }
}
