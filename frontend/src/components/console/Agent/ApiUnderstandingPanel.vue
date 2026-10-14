<script setup lang="ts">
import { Lock } from '@element-plus/icons-vue'
import { ElIcon, ElTooltip } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useAgentStore } from '@/stores/agent'
import { methodColor } from '@/utils/http'

/**
 * What the agent read out of the document.
 *
 * Shapes and counts only — the endpoints it found, how they group, and what
 * stands in front of them. Everything shown comes from the parser, including
 * each endpoint's summary, which is the document's own words and is therefore
 * displayed as written rather than translated.
 */
const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()

const understanding = computed(() => store.understanding)

const stats = computed(() => {
  const current = understanding.value
  if (current === null) return []

  return [
    { key: 'endpoints', label: t('console.aiTest.understanding.endpoints'), value: current.endpoints.length },
    { key: 'resources', label: t('console.aiTest.understanding.resources'), value: current.resources.length },
    { key: 'dependencies', label: t('console.aiTest.understanding.dependencies'), value: current.dependencies.length },
    { key: 'risks', label: t('console.aiTest.understanding.risks'), value: current.risks.length },
  ]
})

const endpointCountByResource = computed<ReadonlyMap<string, number>>(() => {
  const counts = new Map<string, number>()
  for (const endpoint of understanding.value?.endpoints ?? []) {
    counts.set(endpoint.resourceId, (counts.get(endpoint.resourceId) ?? 0) + 1)
  }
  return counts
})

const authFacts = computed(() => {
  const auth = understanding.value?.authentication
  if (auth === undefined) return []

  const rows = [
    { label: t('console.aiTest.understanding.scheme'), value: auth.scheme },
    {
      label: t('console.aiTest.understanding.protectedEndpoints'),
      value: String(auth.protectedEndpointCount),
    },
  ]

  if (auth.tokenSourceEndpointId !== null) {
    const source = understanding.value?.endpoints.find(
      (endpoint) => endpoint.id === auth.tokenSourceEndpointId,
    )
    if (source !== undefined) {
      rows.push({
        label: t('console.aiTest.understanding.tokenSource'),
        value: `${source.method} ${source.path}`,
      })
    }
  }

  if (auth.tokenField !== null) {
    rows.push({ label: t('console.aiTest.understanding.tokenField'), value: auth.tokenField })
  }

  return rows
})

</script>

<template>
  <section v-if="understanding !== null" class="console-panel">
    <header class="border-b border-[var(--console-border)] px-4 py-3">
      <h2 class="text-[13px] font-semibold text-[var(--console-text)]">
        {{ t('console.aiTest.understanding.title') }}
      </h2>
      <p class="mt-0.5 text-[11.5px] text-[var(--console-text-muted)]">
        {{ t('console.aiTest.understanding.subtitle') }}
      </p>
    </header>

    <!-- Counts -->
    <dl class="grid grid-cols-2 gap-px bg-[var(--console-border)] sm:grid-cols-4">
      <div
        v-for="stat in stats"
        :key="stat.key"
        class="flex flex-col gap-1 bg-[var(--console-surface)] px-4 py-3"
      >
        <dt class="console-label">{{ stat.label }}</dt>
        <dd class="font-mono text-[19px] leading-none text-[var(--console-text)]">
          {{ stat.value }}
        </dd>
      </div>
    </dl>

    <div class="grid gap-px bg-[var(--console-border)] lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)]">
      <!-- Resources -->
      <div class="bg-[var(--console-surface)] p-4">
        <p class="console-label mb-2.5">
          {{ t('console.aiTest.understanding.resources') }}
        </p>
        <ul class="flex flex-col gap-1.5">
          <li
            v-for="resource in understanding.resources"
            :key="resource.id"
            class="flex items-center justify-between gap-3"
          >
            <span class="min-w-0 truncate text-[12.5px] text-[var(--console-text)]">
              {{ resource.name }}
            </span>
            <span class="shrink-0 font-mono text-[11px] text-[var(--console-text-muted)]">
              {{ endpointCountByResource.get(resource.id) ?? 0 }}
            </span>
          </li>
        </ul>
      </div>

      <!-- Authentication -->
      <div class="bg-[var(--console-surface)] p-4">
        <p class="console-label mb-2.5">
          {{ t('console.aiTest.understanding.authentication') }}
        </p>

        <p
          v-if="understanding.authentication.scheme === 'none'"
          class="text-[12px] text-[var(--console-text-muted)]"
        >
          {{ t('console.aiTest.understanding.noAuthentication') }}
        </p>

        <dl v-else class="flex flex-col gap-2">
          <div
            v-for="fact in authFacts"
            :key="fact.label"
            class="flex items-baseline justify-between gap-4"
          >
            <dt class="shrink-0 text-[11.5px] text-[var(--console-text-muted)]">
              {{ fact.label }}
            </dt>
            <dd class="min-w-0 truncate font-mono text-[12px] text-[var(--console-text-dim)]">
              {{ fact.value }}
            </dd>
          </div>
        </dl>
      </div>
    </div>

    <!-- Endpoints -->
    <div class="border-t border-[var(--console-border)] p-4">
      <p class="console-label mb-2.5">
        {{ t('console.aiTest.understanding.endpoints') }}
      </p>

      <ul class="flex flex-col">
        <li
          v-for="endpoint in understanding.endpoints"
          :key="endpoint.id"
          data-testid="understanding-endpoint"
          class="flex items-baseline gap-3 border-b border-[var(--console-border)] py-2 last:border-b-0"
        >
          <span
            class="w-[46px] shrink-0 font-mono text-[10.5px] font-semibold"
            :style="{ color: methodColor(endpoint.method) }"
          >
            {{ endpoint.method }}
          </span>

          <span class="min-w-0 flex-1">
            <span class="block truncate font-mono text-[12.5px] text-[var(--console-text)]">
              {{ endpoint.path }}
            </span>
            <span class="mt-0.5 block truncate text-[11px] text-[var(--console-text-muted)]">
              {{ localize(endpoint.summary) }}
            </span>
          </span>

          <ElTooltip
            v-if="endpoint.requiresAuth"
            :content="t('console.aiTest.understanding.requiresAuth')"
            placement="top"
            :show-after="300"
          >
            <ElIcon
              :size="12"
              class="shrink-0 self-center text-[var(--console-text-muted)]"
            >
              <Lock />
            </ElIcon>
          </ElTooltip>
        </li>
      </ul>
    </div>
  </section>
</template>
