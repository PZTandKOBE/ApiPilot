<script setup lang="ts">
import { useLocalizedText } from '@/composables/useLocalizedText'
import type { RunFailure } from '@/types/run'

/**
 * Why something failed, in both registers.
 *
 * The authored sentence comes first and is what a reader acts on; the
 * machine's own words sit under it in monospace for the person who has to
 * tell a 401 from a timeout. The detail never replaces the sentence — it is
 * the sentence that survives a language switch, and a raw exception message
 * on its own would leave the reader translating it themselves.
 */
defineProps<{ failure: RunFailure }>()

const { localize } = useLocalizedText()
</script>

<template>
  <div
    class="rounded-lg border px-3 py-2 text-[11.5px] leading-relaxed"
    :style="{
      borderColor: 'color-mix(in srgb, var(--status-fail) 30%, transparent)',
      color: 'var(--console-text-dim)',
    }"
  >
    <p>
      <span class="font-medium text-[var(--status-fail)]">
        {{ localize(failure.message) }}
      </span>
    </p>

    <p v-if="failure.detail !== null" class="mt-1 font-mono text-[10.5px] text-[var(--console-text-muted)]">
      {{ failure.detail }}
    </p>
  </div>
</template>
