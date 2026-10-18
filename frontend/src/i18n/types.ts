/**
 * Translation dictionaries.
 *
 * `MessageSchema` is derived from the source locale (en-US). Every other
 * locale is typed against it, so a missing or misspelled key is a compile
 * error rather than a string that silently renders as a raw key at runtime.
 */

import type { ConsoleMessageSchema } from './console-schema'

export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const

export type AppLocale = (typeof SUPPORTED_LOCALES)[number]

export interface MessageSchema {
  /**
   * Console vocabulary. Sectioned off from the marketing copy above so the
   * application surface can grow without bloating the landing-page dictionary.
   */
  readonly console: ConsoleMessageSchema

  /** Learn Us documentation portal. */
  readonly learn: {
    readonly brand: string
    readonly docsLabel: string
    readonly tryUs: string
    readonly search: string
    readonly searchTitle: string
    readonly searchPlaceholder: string
    readonly searchHint: string
    readonly searchEmpty: string
    readonly searchNoResults: string
    readonly close: string
    readonly menu: string
    readonly closeMenu: string
    readonly theme: string
    readonly light: string
    readonly dark: string
    readonly switchToLight: string
    readonly switchToDark: string
    readonly onThisPage: string
    readonly previous: string
    readonly next: string
    readonly copy: string
    readonly copied: string
    readonly copyFailed: string
    readonly linkCopied: string
    readonly backToDocs: string
    readonly notFound: string
    readonly notFoundBody: string
    readonly breadcrumbHome: string
    readonly groups: {
      readonly start: string
      readonly use: string
      readonly reference: string
    }
  }

  /** Public account/login surface. Never contains provider credentials. */
  readonly auth: {
    readonly title: string
    readonly subtitle: string
    readonly selfHostedTitle: string
    readonly selfHostedBody: string
    readonly officialTitle: string
    readonly firstTime: string
    readonly continueWithGithub: string
    readonly continueWithGoogle: string
    readonly continueAsGuest: string
    readonly or: string
    readonly loading: string
    readonly providerUnavailable: string
    readonly noProviders: string
    readonly signedInAs: string
    readonly noEmail: string
    readonly continueToConsole: string
    readonly logout: string
    readonly logoutFailed: string
    readonly errorTitle: string
    readonly backHome: string
    readonly privacyNote: string
    readonly signInRequired: string
    readonly errors: {
      readonly unavailable: string
      readonly required: string
      readonly providerUnavailable: string
      readonly guestSessionsDisabled: string
      readonly forbiddenOrigin: string
      readonly logoutFailed: string
      readonly oauthCancelled: string
      readonly oauthFailed: string
      readonly stateInvalid: string
      readonly oidcInvalid: string
      readonly providerProfileFailed: string
      readonly accountUnavailable: string
      readonly authDisabled: string
      readonly guestDisabled: string
      readonly guestStartFailed: string
      readonly guestLimitReached: string
    }
  }

  readonly nav: {
    readonly github: string
    readonly language: string
    readonly home: string
  }
  readonly hero: {
    /** Display title, one array entry per rendered SVG line. */
    readonly titleLines: readonly string[]
    readonly subtitleLine1: string
    readonly subtitleLine2: string
    readonly tryUs: string
    readonly learnUs: string
    readonly badge: string
    readonly ctaHint: string
  }
  readonly showcase: {
    readonly eyebrow: string
    readonly title: string
    readonly description: string
    readonly cardLabel: string
    readonly steps: readonly string[]
  }
  readonly apiTesting: {
    readonly kicker: string
    readonly method: string
    readonly path: string
    readonly headers: string
    readonly authKey: string
    readonly authValue: string
    readonly contentTypeKey: string
    readonly contentTypeValue: string
    readonly body: string
    readonly send: string
    readonly timeLabel: string
    readonly timeValue: string
    readonly responseTitle: string
    readonly responseStatusValue: string
  }
  readonly plan: {
    readonly kicker: string
    readonly generatedBy: string
    readonly cases: readonly string[]
    readonly riskLabel: string
    readonly riskValue: string
    readonly countLabel: string
    readonly countValue: string
    readonly reject: string
    readonly approve: string
    readonly note: string
  }
  readonly workflow: {
    readonly kicker: string
    readonly nodes: readonly string[]
    readonly edges: readonly string[]
    readonly passed: string
    readonly evidence: string
    readonly evidenceValue: string
  }
}
