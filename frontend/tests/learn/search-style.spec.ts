import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync(
  new URL('../../src/styles/learn.css', import.meta.url),
  'utf8',
)

describe('Learn Us search field boundaries', () => {
  it('uses the field container for the only focus boundary', () => {
    expect(css).toContain('.learn-search-field:focus-within')
    expect(css).toContain('border-color: var(--learn-focus)')
    expect(css).toContain('box-shadow: 0 0 0 3px')
  })

  it('suppresses the global focus outline only on the inner input', () => {
    expect(css).toContain('.learn-search-field input:focus,')
    expect(css).toContain('.learn-search-field input:focus-visible')
    expect(css).toMatch(
      /\.learn-search-field input:focus-visible\s*\{[^}]*outline:\s*none;/s,
    )
    expect(css).toMatch(
      /\.learn-search-field input\s*\{[^}]*appearance:\s*none;[^}]*-webkit-appearance:\s*none;/s,
    )
    expect(css).not.toMatch(
      /\.learn-search-field input\s*\{[^}]*outline:\s*0;/s,
    )
  })

  it('does not remove the global Learn Us focus-visible rule', () => {
    expect(css).toContain('.learn-app :focus-visible')
    expect(css).toContain('outline: 2px solid var(--learn-focus)')
  })
})
