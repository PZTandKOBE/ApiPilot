import { computed, type ComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { ConsoleNavItem, ResolvedNavItem } from '@/types/console'

export interface ResolvedNav {
  readonly items: ComputedRef<readonly ResolvedNavItem[]>
  /** `routeName` of the deepest matching item, or `null`. */
  readonly activeKey: ComputedRef<string | null>
}

/**
 * Turns declarative nav items into renderable ones against the live router.
 *
 * Two things happen here that neither sidebar should have to think about:
 *
 * 1. **Destination resolution.** Items declare a route *name* and params; the
 *    path is resolved here, so param-bearing destinations stay correct when a
 *    project id changes. An item whose route is not registered yet — or whose
 *    params are incomplete — resolves to `available: false` and renders as a
 *    disabled entry rather than a link into a 404.
 *
 * 2. **Active detection.** Longest matching prefix wins, so
 *    `/console/projects/p1/plans/plan_7` highlights "Test Plans" without any
 *    item needing to know about nested detail routes.
 */
export const useResolvedNav = (
  source: ComputedRef<readonly ConsoleNavItem[]>,
): ResolvedNav => {
  const router = useRouter()
  const route = useRoute()

  const items = computed<readonly ResolvedNavItem[]>(() =>
    source.value.map((item) => {
      const params = item.params ?? {}
      const paramsComplete = Object.values(params).every(
        (value) => value.trim().length > 0,
      )
      const available = paramsComplete && router.hasRoute(item.routeName)

      return {
        ...item,
        available,
        to: available
          ? router.resolve({ name: item.routeName, params }).path
          : '',
      }
    }),
  )

  const activeKey = computed<string | null>(() => {
    const path = route.path
    let best: ResolvedNavItem | null = null

    for (const item of items.value) {
      if (!item.available) continue

      const matches = path === item.to || path.startsWith(`${item.to}/`)
      if (!matches) continue
      if (best === null || item.to.length > best.to.length) best = item
    }

    return best?.routeName ?? null
  })

  return { items, activeKey }
}
