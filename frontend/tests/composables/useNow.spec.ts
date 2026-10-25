import { effectScope, type Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useNow } from '@/composables/useNow'

/**
 * The shared relative-time clock.
 *
 * A page left open must not keep saying "just now" forever. This covers the
 * timer itself; the formatting thresholds are covered in tests/utils/time.spec.ts.
 */
describe('useNow', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-21T12:00:00.000Z'))
    vi.stubGlobal('window', {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('refreshes its value every thirty seconds and stops on scope dispose', () => {
    const scope = effectScope()
    let now: Readonly<Ref<number>> | undefined

    scope.run(() => {
      now = useNow()
    })

    expect(now?.value).toBe(Date.now())

    vi.advanceTimersByTime(30_000)
    expect(now?.value).toBe(Date.now())

    const stoppedAt = now?.value
    scope.stop()
    vi.advanceTimersByTime(30_000)

    expect(now?.value).toBe(stoppedAt)
  })
})
