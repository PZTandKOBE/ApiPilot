<script setup lang="ts">
import type { ConsoleTab } from '@/types/console'

/**
 * Tab strip.
 *
 * Hand-rolled rather than `el-tabs`: the console's tab bars are navigation
 * *within a pane* — a count badge, sometimes a "has content" dot, no sliding
 * ink bar — and re-theming el-tabs's header to reach that costs more than the
 * twenty lines it takes to write it.
 */
defineProps<{
  tabs: readonly ConsoleTab[]
  ariaLabel?: string
}>()

const model = defineModel<string>({ required: true })
</script>

<template>
  <div class="flex items-center gap-0.5" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      role="tab"
      :aria-selected="model === tab.key"
      class="flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2.5 py-1.5 text-[12px] font-medium transition-colors duration-150"
      :class="
        model === tab.key
          ? 'bg-[color-mix(in_srgb,var(--accent)_14%,transparent)] text-[var(--accent-soft)]'
          : 'text-[var(--console-text-dim)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]'
      "
      @click="model = tab.key"
    >
      {{ tab.label }}

      <span
        v-if="tab.badge !== undefined && tab.badge > 0"
        class="rounded-full bg-white/8 px-1.5 py-px font-mono text-[10px] leading-[1.4] text-[var(--console-text-muted)]"
      >
        {{ tab.badge }}
      </span>

      <span
        v-else-if="tab.dot"
        class="size-1.5 rounded-full bg-[var(--accent)]"
        aria-hidden="true"
      />
    </button>
  </div>
</template>
