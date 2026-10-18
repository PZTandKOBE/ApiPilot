import { describe, expect, it } from 'vitest'

import {
  DEFAULT_DOC_SLUG,
  DOCS,
  DOC_GROUPS,
  findDoc,
  neighborDocs,
  searchDocs,
} from '@/content/docs/registry'
import { renderMarkdown } from '@/utils/markdown'

const locales = ['zh-CN', 'en-US'] as const

describe('Learn Us documentation registry', () => {
  it('contains the complete first-version journey in both locales', () => {
    expect(DOCS).toHaveLength(13)
    expect(new Set(DOCS.map((doc) => doc.slug)).size).toBe(DOCS.length)
    expect(DOC_GROUPS.map((group) => group.id)).toEqual(['start', 'use', 'reference'])

    for (const locale of locales) {
      for (const doc of DOCS) {
        expect(doc.title[locale].trim()).not.toBe('')
        expect(doc.summary[locale].trim()).not.toBe('')
        expect(doc.body[locale].trim()).not.toBe('')
      }
    }

    expect(findDoc(DEFAULT_DOC_SLUG)?.slug).toBe('overview')
    expect(findDoc('missing')).toBeUndefined()
  })

  it('links every internal documentation reference to a real slug', () => {
    const slugs = new Set(DOCS.map((doc) => doc.slug))

    for (const doc of DOCS) {
      for (const locale of locales) {
        const links = [...doc.body[locale].matchAll(/\]\(\/learn\/([a-z0-9-]+)\)/g)]
        for (const match of links) {
          expect(slugs.has(match[1] ?? '')).toBe(true)
        }
      }
    }
  })

  it('renders every article with unique heading ids and no executable raw HTML', () => {
    const labels = { copy: 'Copy', copied: 'Copied', anchor: 'Copy link' }

    for (const doc of DOCS) {
      for (const locale of locales) {
        const rendered = renderMarkdown(doc.body[locale], labels)
        const ids = rendered.headings.map((heading) => heading.id)
        expect(new Set(ids).size).toBe(ids.length)
        expect(rendered.headings.length).toBeGreaterThan(0)
        expect(rendered.html).not.toContain('<script')
      }
    }
  })

  it('searches title, summary, and body text and returns neighbours in order', () => {
    const titleResult = searchDocs('en-US', 'Quickstart')
    expect(titleResult.some((result) => result.doc.slug === 'quickstart')).toBe(true)

    const bodyResult = searchDocs('zh-CN', 'run_reports')
    expect(bodyResult.some((result) => result.doc.slug === 'pdf-reports')).toBe(true)

    const quickstart = findDoc('quickstart')
    expect(quickstart).toBeDefined()
    if (quickstart !== undefined) {
      expect(neighborDocs(quickstart).previous?.slug).toBe('overview')
      expect(neighborDocs(quickstart).next?.slug).toBe('self-hosting')
    }

    expect(searchDocs('en-US', '   ')).toEqual([])
    expect(searchDocs('en-US', 'not-a-real-topic-xyz')).toEqual([])
  })
})
