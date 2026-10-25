import { onScopeDispose, readonly, ref, type Ref } from 'vue'

/**
 * A shared clock for relative timestamps.
 *
 * Relative labels are computed from the current time, so a page left open
 * would otherwise keep saying "刚刚" long after the moment passed. The timer
 * lives here rather than in each card: every subscriber shares one 30-second
 * tick, and the interval stops as soon as the last subscriber unmounts.
 *
 * Server rendering has no window and no long-lived page, so it returns a
 * snapshot for this render instead of scheduling anything.
 */
const TICK_MS = 30_000

const sharedNow = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null
let subscribers = 0

export const useNow = (): Readonly<Ref<number>> => {
  if (typeof window === 'undefined') {
    return readonly(ref(Date.now()))
  }

  subscribers += 1

  if (timer === null) {
    sharedNow.value = Date.now()
    timer = setInterval(() => {
      sharedNow.value = Date.now()
    }, TICK_MS)
  }

  onScopeDispose(() => {
    subscribers = Math.max(0, subscribers - 1)

    if (subscribers === 0 && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  })

  return readonly(sharedNow)
}
