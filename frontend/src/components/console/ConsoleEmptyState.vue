<script setup lang="ts">
import { ElIcon } from 'element-plus'
import type { Component } from 'vue'

/**
 * Empty state.
 *
 * Deliberately lighter than `el-empty`: its stock illustration is far taller
 * than the panels it would sit in, and this layout's whole point is density.
 * An empty panel here also has a job to do — explaining what would fill it and
 * offering the action that does so.
 */
defineProps<{
  title: string
  body?: string
  icon?: Component
}>()
</script>

<template>
  <div class="flex flex-col items-center gap-1.5 px-6 py-9 text-center">
    <ElIcon v-if="icon" :size="20" class="mb-1 text-[var(--console-text-muted)]">
      <component :is="icon" />
    </ElIcon>

    <p class="text-[13px] font-medium text-[var(--console-text-dim)]">
      {{ title }}
    </p>

    <p
      v-if="body"
      class="max-w-md text-[12px] leading-relaxed text-[var(--console-text-muted)]"
    >
      {{ body }}
    </p>

    <div class="mt-2.5 empty:mt-0">
      <slot />
    </div>
  </div>
</template>
