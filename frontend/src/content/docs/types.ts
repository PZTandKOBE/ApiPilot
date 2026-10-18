import type { AppLocale } from '@/i18n/types'

export type DocGroupId = 'start' | 'use' | 'reference'

export interface DocGroup {
  readonly id: DocGroupId
}

export const DOC_GROUP_TITLE_KEYS: Readonly<Record<DocGroupId, string>> = {
  start: 'learn.groups.start',
  use: 'learn.groups.use',
  reference: 'learn.groups.reference',
}

export interface DocEntry {
  readonly slug: string
  readonly group: DocGroupId
  readonly title: Readonly<Record<AppLocale, string>>
  readonly summary: Readonly<Record<AppLocale, string>>
  readonly body: Readonly<Record<AppLocale, string>>
}

export interface MarkdownHeading {
  readonly id: string
  readonly text: string
  readonly level: 2 | 3
}

export interface SearchResult {
  readonly doc: DocEntry
  readonly title: string
  readonly summary: string
}
