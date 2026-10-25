/**
 * Console-level UI types — navigation and in-app notifications.
 *
 * These are presentation concerns rather than domain data, which is why they
 * live apart from the project / test-plan types.
 */

import type { Component } from 'vue'

import type { LocalizedText } from '@/types/agent'

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
  /** The project the resource belongs to; navigation is guarded by this. */
  readonly projectId: string
  readonly kind: NotificationKind
  readonly titleKey: string
  /** Optional second line, rendered through the same i18n mechanism. */
  readonly detailKey?: string
  readonly detailParams?: Readonly<Record<string, string | number>>
  /** A dictionary-authored resource name that must follow the language switch. */
  readonly localizedName?: LocalizedText
  /** Optional in-console destination the notification links to. */
  readonly to?: string
  createdAt: number
  read: boolean
}
