/**
 * Date formatting helpers.
 *
 * The console shows "how long ago", not timestamps: a test run's age is the
 * only thing that matters when scanning a list, and a wall-clock time makes
 * the reader do the subtraction. Locale comes from the app, so this delegates
 * to `Intl` rather than hard-coding English units.
 */

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY
const MONTH = 30 * DAY
const YEAR = 365 * DAY

const toMillis = (value: number | string): number =>
  typeof value === 'number' ? value : Date.parse(value)

/**
 * `just now`, `3 minutes ago`, `in 2 days`, `last month` — rendered in
 * `locale`. Returns an empty string for an unparseable input rather than
 * printing `NaN`, which would be worse than showing nothing.
 */
export const formatRelativeTime = (
  value: number | string,
  locale: string,
): string => {
  const millis = toMillis(value)
  if (Number.isNaN(millis)) return ''

  const formatter = new Intl.RelativeTimeFormat(locale, {
    numeric: 'auto',
    style: 'narrow',
  })

  let seconds = (millis - Date.now()) / 1000

  for (const [threshold, unit] of STEPS) {
    if (Math.abs(seconds) < threshold) {
      return formatter.format(Math.round(seconds), unit)
    }
    seconds /= threshold
  }

  return ''
}

// Scaled from largest to smallest: the first unit the value is smaller than
// is the one it is expressed in.
const STEPS: readonly (readonly [number, Intl.RelativeTimeFormatUnit])[] = [
  [MINUTE, 'second'],
  [HOUR, 'minute'],
  [DAY, 'hour'],
  [WEEK, 'day'],
  [MONTH, 'week'],
  [YEAR, 'month'],
  [Number.POSITIVE_INFINITY, 'year'],
]

/** Absolute date, formatted for the reader's locale. */
export const formatDate = (value: number | string, locale: string): string => {
  const millis = toMillis(value)
  if (Number.isNaN(millis)) return ''

  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(millis)
}
