import { describe, expect, it } from 'vitest'

import { formatRelativeTime } from '@/utils/time'

const NOW = Date.parse('2026-10-21T12:00:00.000Z')

const at = (deltaMs: number): string => new Date(NOW + deltaMs).toISOString()

const zh = (deltaMs: number): string =>
  formatRelativeTime(at(deltaMs), 'zh-CN', { now: NOW, justNow: '刚刚' })

const en = (deltaMs: number): string =>
  formatRelativeTime(at(deltaMs), 'en-US', { now: NOW, justNow: 'Just now' })

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

describe('formatRelativeTime', () => {
  it('uses just now below one minute in both locales', () => {
    expect(zh(-30 * SECOND)).toBe('刚刚')
    expect(zh(-59 * SECOND)).toBe('刚刚')
    expect(en(-30 * SECOND)).toBe('Just now')
    expect(en(-59 * SECOND)).toBe('Just now')
  })

  it('escalates from minutes to hours to days', () => {
    expect(zh(-MINUTE)).toBe('1分钟前')
    expect(zh(-12 * MINUTE)).toBe('12分钟前')
    expect(zh(-59 * MINUTE)).toBe('59分钟前')
    expect(zh(-HOUR)).toBe('1小时前')
    expect(zh(-21 * HOUR)).toBe('21小时前')
    expect(zh(-24 * HOUR)).toBe('1天前')
    expect(zh(-48 * HOUR)).toBe('2天前')
  })

  it('uses hours instead of the old 1309 minutes text', () => {
    expect(zh(-1309 * MINUTE)).toBe('21小时前')
  })

  it('keeps English natural rather than narrow abbreviations', () => {
    expect(en(-MINUTE)).toBe('1 minute ago')
    expect(en(-12 * MINUTE)).toBe('12 minutes ago')
    expect(en(-21 * HOUR)).toBe('21 hours ago')
    expect(en(-2 * DAY)).toBe('2 days ago')
  })

  it('handles future timestamps without negative output', () => {
    expect(zh(30 * SECOND)).toBe('刚刚')
    expect(zh(90 * SECOND)).toBe('1分钟后')
    expect(en(90 * SECOND)).toBe('in 1 minute')
  })

  it('parses UTC ISO strings across a calendar and timezone boundary', () => {
    const value = '2026-10-20T14:15:40.220247Z'
    const now = Date.parse('2026-10-21T20:00:00.000Z')

    expect(formatRelativeTime(value, 'zh-CN', { now, justNow: '刚刚' })).toBe('1天前')
    expect(formatRelativeTime(value, 'en-US', { now, justNow: 'Just now' })).toBe(
      '1 day ago',
    )
  })

  it('returns an empty string for invalid values instead of NaN', () => {
    expect(formatRelativeTime('not-a-date', 'zh-CN', { now: NOW })).toBe('')
    expect(formatRelativeTime('', 'en-US', { now: NOW })).toBe('')
  })

  it('keeps second-level wording when no just-now label is supplied', () => {
    expect(formatRelativeTime(at(-14 * SECOND), 'en-US', { now: NOW })).toBe(
      '14 seconds ago',
    )
  })
})
