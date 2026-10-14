<script setup lang="ts">
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { methodColor } from '@/utils/http'

/**
 * A request handed over from the API Client.
 *
 * The seam between the two halves of the product, made visible: the user
 * composed this request by hand over there, and the agent can now read it as a
 * one-endpoint API and propose tests for it.
 *
 * Shown as an offer rather than an action — an incoming handoff never
 * replaces the specification a user is already working on. The request type is
 * `AgentHandoff`, the same object the API Client produced; nothing is
 * re-modelled on the way in.
 */
const { t } = useI18n()
const store = useAgentStore()

const handoff = computed(() => store.pendingHandoff)

const activeHeaders = computed(
  () => handoff.value?.draft.headers.filter((row) => row.enabled && row.key.trim() !== '') ?? [],
)

const bodyText = computed(() => {
  const body = handoff.value?.draft.body
  if (body === undefined || body.mode === 'none' || body.text.trim() === '') return ''

  return body.text
})

const busy = computed(() => store.loading)
</script>

<template>
  <section
    v-if="handoff !== null"
    class="console-panel border-[var(--console-border-strong)] p-4"
  >
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="console-label">{{ t('console.aiTest.handoff.source') }}</p>
        <h2 class="mt-1 flex items-center gap-2 text-[14px] font-semibold text-[var(--console-text)]">
          <ElIcon :size="15" class="text-[var(--accent)]"><Promotion /></ElIcon>
          {{ t('console.aiTest.handoff.title') }}
        </h2>
        <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
          {{ t('console.aiTest.handoff.description') }}
        </p>
      </div>

      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <ElButton size="small" :disabled="busy" @click="store.dismissHandoff()">
          {{ t('console.aiTest.handoff.dismiss') }}
        </ElButton>

        <ElButton size="small" :disabled="busy" @click="store.loadDemoSpec()">
          <ElIcon class="mr-1.5"><MagicStick /></ElIcon>
          {{ t('console.aiTest.handoff.useDemo') }}
        </ElButton>

        <ElButton size="small" type="primary" :loading="busy" @click="store.adoptHandoff()">
          {{ t('console.aiTest.handoff.analyze') }}
        </ElButton>
      </div>
    </header>

    <!-- The request itself -->
    <div class="mt-3.5 rounded-lg border border-[var(--console-border)] bg-black/20 p-3">
      <div class="flex items-center gap-2.5">
        <span
          class="shrink-0 font-mono text-[11px] font-semibold"
          :style="{ color: methodColor(handoff.draft.method) }"
        >
          {{ handoff.draft.method }}
        </span>
        <span class="min-w-0 truncate font-mono text-[12px] text-[var(--console-text)]">
          {{ handoff.resolved.url }}
        </span>
      </div>

      <dl v-if="activeHeaders.length > 0" class="mt-2.5 flex flex-col gap-1">
        <div
          v-for="header in activeHeaders"
          :key="header.id"
          class="flex items-baseline gap-2 font-mono text-[11.5px]"
        >
          <dt class="w-[130px] shrink-0 truncate text-[var(--console-text-muted)]">
            {{ header.key }}
          </dt>
          <dd class="min-w-0 truncate text-[var(--console-text-dim)]">{{ header.value }}</dd>
        </div>
      </dl>

      <pre
        v-if="bodyText !== ''"
        class="mt-2.5 overflow-hidden rounded-md border border-[var(--console-border)] bg-black/30 p-2.5 font-mono text-[11.5px] leading-[1.55] whitespace-pre-wrap text-[var(--console-text-dim)]"
      >{{ bodyText }}</pre>
    </div>
  </section>
</template>
