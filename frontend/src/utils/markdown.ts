import hljs from 'highlight.js/lib/common'
import { Marked, type RendererThis, type Tokens } from 'marked'

import type { MarkdownHeading } from '@/content/docs/types'

export interface MarkdownRenderResult {
  readonly html: string
  readonly headings: readonly MarkdownHeading[]
}

export interface MarkdownLabels {
  readonly copy: string
  readonly copied: string
  readonly anchor: string
}

const escapeHtml = (value: string): string =>
  value.replace(/[&<>"']/g, (character) => {
    switch (character) {
      case '&':
        return '&amp;'
      case '<':
        return '&lt;'
      case '>':
        return '&gt;'
      case '"':
        return '&quot;'
      default:
        return '&#39;'
    }
  })

const escapeAttribute = (value: string): string => escapeHtml(value)

const plainHeading = (value: string): string =>
  value.replace(/[*_~#\[\]]/g, '').replace(/\s+/g, ' ').trim()

const slugify = (value: string): string =>
  plainHeading(value)
    .toLocaleLowerCase()
    .normalize('NFKC')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .trim()
    .replace(/\s+/g, '-') || 'section'

const safeHref = (value: string): string => {
  if (/^(https?:|mailto:|#)/i.test(value)) return value
  if (value.startsWith('/') && !value.startsWith('//')) return value
  return '#'
}

const renderCode = (token: Tokens.Code, labels: MarkdownLabels): string => {
  const requested = (token.lang ?? '').trim().split(/\s+/)[0] ?? ''
  const language = /^[a-z0-9-]+$/i.test(requested) ? requested : ''
  let highlighted = escapeHtml(token.text)

  if (language !== '' && hljs.getLanguage(language)) {
    try {
      highlighted = hljs.highlight(token.text, {
        language,
        ignoreIllegals: true,
      }).value
    } catch {
      highlighted = escapeHtml(token.text)
    }
  }

  const languageLabel = language === '' ? 'text' : language
  const languageClass = language === '' ? '' : ' language-' + language

  return (
    '<div class="docs-code">' +
    '<div class="docs-code-bar">' +
    '<span class="docs-code-language">' +
    escapeHtml(languageLabel) +
    '</span>' +
    '<button type="button" class="docs-copy" data-copy-code aria-label="' +
    escapeAttribute(labels.copy) +
    '">' +
    escapeHtml(labels.copy) +
    '</button>' +
    '</div>' +
    '<pre><code class="hljs' +
    languageClass +
    '">' +
    highlighted +
    '</code></pre>' +
    '</div>'
  )
}

export const renderMarkdown = (
  source: string,
  labels: MarkdownLabels,
): MarkdownRenderResult => {
  const headings: MarkdownHeading[] = []
  const slugCounts = new Map<string, number>()
  const marked = new Marked({ gfm: true, breaks: false })

  marked.use({
    renderer: {
      heading(this: RendererThis, token: Tokens.Heading): string {
        const text = plainHeading(token.text)
        const base = slugify(text)
        const count = slugCounts.get(base) ?? 0
        slugCounts.set(base, count + 1)
        const id = count === 0 ? base : base + '-' + count
        const level = token.depth

        if (level === 2 || level === 3) {
          headings.push({ id, text: text || id, level })
        }

        return (
          '<h' +
          level +
          ' id="' +
          escapeAttribute(id) +
          '">' +
          this.parser.parseInline(token.tokens) +
          '<a class="docs-heading-anchor" href="#' +
          escapeAttribute(id) +
          '" data-heading-anchor="' +
          escapeAttribute(id) +
          '" aria-label="' +
          escapeAttribute(labels.anchor) +
          '" title="' +
          escapeAttribute(labels.anchor) +
          '">#</a>' +
          '</h' +
          level +
          '>'
        )
      },
      code(token: Tokens.Code): string {
        return renderCode(token, labels)
      },
      html(token: Tokens.HTML | Tokens.Tag): string {
        return escapeHtml(token.text)
      },
      image(token: Tokens.Image): string {
        return '<span class="docs-image-alt">' + escapeHtml(token.text) + '</span>'
      },
      link(this: RendererThis, token: Tokens.Link): string {
        const href = safeHref(token.href)
        const external = /^https?:/i.test(href)
        const title =
          token.title === null || token.title === undefined
            ? ''
            : ' title="' + escapeAttribute(token.title) + '"'
        const target = external ? ' target="_blank" rel="noopener noreferrer"' : ''
        return (
          '<a href="' +
          escapeAttribute(href) +
          '"' +
          title +
          target +
          '>' +
          this.parser.parseInline(token.tokens) +
          '</a>'
        )
      },
    },
  })

  const html = marked.parse(source) as string
  return { html, headings }
}
