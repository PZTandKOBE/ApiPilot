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
