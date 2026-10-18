import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '@/utils/markdown'

const labels = { copy: 'Copy', copied: 'Copied', anchor: 'Copy section link' }

const source = [
  '## First section',
  '',
  'Some **bold** text and [a guide](/learn/quickstart).',
  '',
  '~~~ts',
  'const answer = 42',
  '~~~',
  '',
  '### Child section',
  '',
  '<script>window.__leak = true</script>',
].join('\n')

describe('Learn Us markdown renderer', () => {
  it('renders headings, anchors, code copy markup and TOC metadata', () => {
    const result = renderMarkdown(source, labels)

    expect(result.headings).toEqual([
      { id: 'first-section', text: 'First section', level: 2 },
      { id: 'child-section', text: 'Child section', level: 3 },
    ])
    expect(result.html).toContain('id="first-section"')
    expect(result.html).toContain('data-heading-anchor="first-section"')
    expect(result.html).toContain('data-copy-code')
    expect(result.html).toContain('language-ts')
    expect(result.html).toContain('hljs-keyword')
    expect(result.html).toContain('href="/learn/quickstart"')
  })

  it('escapes raw HTML instead of executing it', () => {
    const result = renderMarkdown(source, labels)

    expect(result.html).not.toContain('<script>')
    expect(result.html).toContain('&lt;script&gt;window.__leak = true&lt;/script&gt;')
  })

  it('rejects unsafe link schemes and makes duplicate heading ids unique', () => {
    const result = renderMarkdown(
      ['## Same', '', '[bad](javascript:alert(1))', '', '## Same'].join('\n'),
      labels,
    )

    expect(result.html).toContain('href="#"')
    expect(result.html).not.toContain('javascript:')
    expect(result.headings.map((heading) => heading.id)).toEqual(['same', 'same-1'])
  })
})
