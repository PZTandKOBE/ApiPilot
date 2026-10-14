<script setup lang="ts">
/**
 * Page title block.
 *
 * Every console page opens with the same rhythm — eyebrow, title, one line of
 * orientation, actions on the right — so the reader always knows where the
 * page starts without hunting for it.
 */
defineProps<{
  title: string
  subtitle?: string
  /** Small uppercase label above the title. */
  eyebrow?: string
}>()
</script>

<template>
  <header class="flex flex-wrap items-start justify-between gap-4 pb-5">
    <div class="min-w-0">
      <p v-if="eyebrow" class="console-label mb-1.5">{{ eyebrow }}</p>
      <h1
        class="text-[19px] font-semibold tracking-[-0.01em] text-[var(--console-text)]"
      >
        {{ title }}
      </h1>
      <p
        v-if="subtitle"
        class="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-[var(--console-text-dim)]"
      >
        {{ subtitle }}
      </p>
      <slot name="meta" />
    </div>

    <div class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
