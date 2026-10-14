<script setup lang="ts">
import { computed } from 'vue'

import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { ApiDependency, ApiEndpoint } from '@/types/agent'
import { methodColor } from '@/utils/http'

/**
 * The path the agent would drive a test through.
 *
 * Grouped by source endpoint rather than rendered as a chain. A chain has to
 * repeat a node whenever it branches, which made `GET /orders/{id}` read as
 * three separate steps; here each endpoint appears once as a source and lists
 * what it unlocks, with every binding and its explanation still on screen.
 *
 * Deliberately not a graph canvas. This is a reading aid over seven edges, and
 * a layout engine would add a dependency, a bundle and a class of bugs to
 * render the same information.
 */
const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

interface Branch {
  readonly edge: ApiDependency
  readonly target: ApiEndpoint
  /** `↓` for a single edge, `├` / `└` when a source fans out. */
  readonly glyph: string
}

interface SourceGroup {
  readonly source: ApiEndpoint
  readonly branches: readonly Branch[]
}

const groups = computed<readonly SourceGroup[]>(() => {
  const understanding = store.understanding
  if (understanding === null) return []

  const byId = new Map(
    understanding.endpoints.map((endpoint) => [endpoint.id, endpoint]),
  )

  // Bucket by source, remembering first-seen order so the reading order is the
  // order the rules discovered the edges in.
  const order: string[] = []
  const buckets = new Map<string, ApiDependency[]>()

  for (const dependency of understanding.dependencies) {
    const bucket = buckets.get(dependency.fromEndpointId)

    if (bucket === undefined) {
      buckets.set(dependency.fromEndpointId, [dependency])
      order.push(dependency.fromEndpointId)
      continue
    }

    bucket.push(dependency)
  }

  const collected: SourceGroup[] = []

  for (const sourceId of order) {
    const source = byId.get(sourceId)
    const edges = buckets.get(sourceId)
    if (source === undefined || edges === undefined) continue

    const branches: Branch[] = []

    edges.forEach((edge, index) => {
      const target = byId.get(edge.toEndpointId)
      if (target === undefined) return

      branches.push({
        edge,
        target,
        glyph:
          edges.length === 1 ? '↓' : index === edges.length - 1 ? '└' : '├',
      })
    })

    if (branches.length > 0) collected.push({ source, branches })
  }

  return collected
})

const resourceNameOf = (endpoint: ApiEndpoint): string =>
  store.understanding?.resources.find(
    (resource) => resource.id === endpoint.resourceId,
  )?.name ?? ''
</script>

<template>
  <section class="console-panel">
    <header class="border-b border-[var(--console-border)] px-4 py-3">
      <h2 class="text-[13px] font-semibold text-[var(--console-text)]">
        {{ t('console.aiTest.understanding.dependencies') }}
      </h2>
    </header>

    <p
      v-if="groups.length === 0"
      class="px-4 py-6 text-center text-[12px] text-[var(--console-text-muted)]"
    >
      {{ t('console.aiTest.dependencies.empty') }}
    </p>

    <div v-else class="flex flex-col gap-3 px-4 py-4">
      <div v-for="group in groups" :key="group.source.id" class="flex flex-col">
        <!-- Source: the endpoint every branch below starts from -->
        <div
          data-testid="dependency-group"
          class="flex items-center gap-3 rounded-lg border border-[var(--console-border-strong)] bg-[var(--console-surface-raised)] px-3 py-2"
        >
          <span
            class="w-[46px] shrink-0 font-mono text-[10.5px] font-semibold"
            :style="{ color: methodColor(group.source.method) }"
          >
            {{ group.source.method }}
          </span>
          <span class="min-w-0 flex-1 truncate font-mono text-[12.5px] text-[var(--console-text)]">
            {{ group.source.path }}
          </span>
          <span
            v-if="resourceNameOf(group.source) !== ''"
            class="shrink-0 rounded-md bg-white/6 px-1.5 py-0.5 text-[10.5px] text-[var(--console-text-muted)]"
          >
            {{ resourceNameOf(group.source) }}
          </span>
        </div>

        <!-- Branches -->
        <ul class="ms-3 flex flex-col border-s border-[var(--console-border)] ps-3">
          <li
            v-for="branch in group.branches"
            :key="branch.edge.id"
            data-testid="dependency-branch"
            class="flex gap-2 py-1.5"
          >
            <span
              class="shrink-0 select-none pt-px font-mono text-[12px] text-[var(--console-text-muted)]"
              aria-hidden="true"
            >
              {{ branch.glyph }}
            </span>

            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <span class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span
                  class="shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10.5px]"
                  :style="{
                    color: 'var(--accent-soft)',
                    backgroundColor: 'color-mix(in srgb, var(--accent) 14%, transparent)',
                  }"
                >
                  {{ branch.edge.binding }}
                </span>
                <span
                  data-testid="dependency-rationale"
                  class="min-w-0 text-[11px] leading-snug text-[var(--console-text-muted)]"
                >
                  {{ localize(branch.edge.rationale) }}
                </span>
              </span>

              <span class="flex items-center gap-2.5">
                <span
                  class="w-[46px] shrink-0 font-mono text-[10px] font-semibold"
                  :style="{ color: methodColor(branch.target.method) }"
                >
                  {{ branch.target.method }}
                </span>
                <span class="min-w-0 flex-1 truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                  {{ branch.target.path }}
                </span>
              </span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
