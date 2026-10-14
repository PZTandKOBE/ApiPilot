/**
 * Console-level UI types — navigation and in-app notifications.
 *
 * These are presentation concerns rather than domain data, which is why they
 * live apart from the project / test-plan types.
 */

import type { Component } from 'vue'

/**
 * One entry in a console navigation list.
 *
 * `routeName` rather than a literal path: the item is resolved through the
 * router at render time, which keeps param-bearing destinations correct and
 * lets the sidebar tell whether a destination is routable *yet*. Items whose
 * route is not registered render as disabled instead of linking to a 404.
 */
export interface ConsoleNavItem {
  /** Full i18n key for the label, e.g. `console.nav.apiClient`. */
  readonly labelKey: string
  readonly icon: Component
  readonly routeName: string
  readonly params?: Readonly<Record<string, string>>
  /** Optional trailing chip, already formatted (a count, a status word). */
  readonly badge?: string
  /**
   * Optional i18n key for a short second line under the label.
   *
   * Used where two entries sit in the same group doing similar-looking things
   * and the difference has to be legible without clicking: "API Client" and
   * "AI Test Lab" are both "test the API", one by hand and one through the
   * agent. Hidden in the collapsed rail, exactly like the label.
   */
  readonly hintKey?: string
  /** Optional i18n key for a group heading this item introduces. */
  readonly groupKey?: string
}

/** A nav item with its destination resolved against the live router. */
export interface ResolvedNavItem extends ConsoleNavItem {
  /** Resolved absolute path, or `''` when the destination is not routable. */
  readonly to: string
  readonly available: boolean
}

/** One entry in a console tab strip. */
export interface ConsoleTab {
  readonly key: string
  readonly label: string
  /** Trailing count; hidden when `undefined` or `0`. */
  readonly badge?: number
  /** Small dot marking the tab as carrying content. */
  readonly dot?: boolean
}

export type NotificationKind = 'info' | 'success' | 'warning' | 'error'

/**
 * In-app notification.
 *
 * Carries an i18n key plus interpolation params rather than a finished
 * sentence: the same notification has to read correctly after the user
 * switches language, and a pre-rendered string could not.
 */
export interface ConsoleNotification {
  readonly id: string
  readonly kind: NotificationKind
  readonly titleKey: string
  readonly params?: Readonly<Record<string, string | number>>
  /** Optional in-console destination the notification links to. */
  readonly to?: string
  readonly createdAt: number
  readonly read: boolean
}
