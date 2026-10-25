import { describe, expect, it } from 'vitest'

import { isHttpUrl } from '@/utils/url'

describe('isHttpUrl', () => {
  it('accepts absolute http and https URLs with a host', () => {
    expect(isHttpUrl('http://127.0.0.1:8000')).toBe(true)
    expect(isHttpUrl('https://api.example.com/v1')).toBe(true)
    expect(isHttpUrl('  https://staging.example.com  ')).toBe(true)
  })

  it('rejects relative, hostless and non-http values', () => {
    expect(isHttpUrl('')).toBe(false)
    expect(isHttpUrl('   ')).toBe(false)
    expect(isHttpUrl('/v1/orders')).toBe(false)
    expect(isHttpUrl('api.example.com')).toBe(false)
    expect(isHttpUrl('ftp://api.example.com')).toBe(false)
    expect(isHttpUrl('javascript:alert(1)')).toBe(false)
  })
})
