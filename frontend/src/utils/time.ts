/**
 * Date formatting helpers.
 *
 * The console shows "how long ago", not timestamps: a test run's age is the
 * only thing that matters when scanning a list, and a wall-clock time makes
 * the reader do the subtraction. Locale comes from the app, so this delegates
 * to `Intl` rather than hard-coding English units.
 */

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

const toMillis = (value: number | string): number =>
  typeof value === 'number' ? value : Date.parse(value)

export interface RelativeTimeOptions {
  /**
   * The instant to compare against. Supplied by callers that own a ticking
   * clock, so a page can refresh without every card inventing its own timer.
   */
  readonly now?: number
  /**
   * Locale-specific wording for the under-one-minute bucket.
   *
   * The utility has no i18n dependency, so the owner of the language chooses
   * whether this reads as "just now", "刚刚", or something else. Callers that
   * omit it keep the existing second-level "14 seconds ago" behaviour.
   */
  readonly justNow?: string
}

/**
 * A natural relative time in the reader's locale.
 *
 * The escalation thresholds are minutes, hours and days. Days continue to be
 * used for older timestamps rather than turning into hundreds of minutes. A
 * future timestamp is expressed as an amount of time ahead, never as a
 * negative number. An invalid date returns an empty string so a caller can
 * render its own fallback instead of showing NaN.
 */
export const formatRelativeTime = (
  value: number | string,
  locale: string,
  options: RelativeTimeOptions = {},
): string => {
  const millis = toMillis(value)
  const now = options.now ?? Date.now()

  if (Number.isNaN(millis) || Number.isNaN(now)) return ''

  const formatter = new Intl.RelativeTimeFormat(locale, {
    numeric: 'always',
    style: 'long',
  })

  const diffMs = millis - now
  const absMs = Math.abs(diffMs)

  if (absMs < MINUTE_MS) {
    if (options.justNow !== undefined) return options.justNow

    // Keep the previous behaviour for callers that do not supply a just-now
    // sentence: a fresh record reads as "14 seconds ago", not as 0 minutes.
    const secondsFormatter = new Intl.RelativeTimeFormat(locale, {
      numeric: 'auto',
      style: 'long',
    })

    return secondsFormatter.format(Math.round(diffMs / 1000), 'second')
  }

  const past = diffMs < 0
  const amount = (unitMs: number): number =>
    Math.max(1, Math.floor(absMs / unitMs))

  if (absMs < HOUR_MS) {
    return formatter.format(past ? -amount(MINUTE_MS) : amount(MINUTE_MS), 'minute')
  }

  if (absMs < DAY_MS) {
    return formatter.format(past ? -amount(HOUR_MS) : amount(HOUR_MS), 'hour')
  }

  return formatter.format(past ? -amount(DAY_MS) : amount(DAY_MS), 'day')
}

/** Absolute date, formatted for the reader's locale. */
export const formatDate = (value: number | string, locale: string): string => {
  const millis = toMillis(value)
  if (Number.isNaN(millis)) return ''

  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(millis)
}
