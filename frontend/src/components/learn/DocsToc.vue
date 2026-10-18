<script setup lang="ts">
import type { MarkdownHeading } from '@/content/docs/types'
import { useI18n } from '@/i18n'

defineProps<{
  headings: readonly MarkdownHeading[]
  activeId: string
}>()

const { t } = useI18n()
</script>

<template>
  <aside v-if="headings.length > 0" class="learn-toc" :aria-label="t('learn.onThisPage')">
    <p class="learn-toc-title">{{ t('learn.onThisPage') }}</p>
    <nav>
      <a
        v-for="heading in headings"
        :key="heading.id"
        :href="'#' + heading.id"
        class="learn-toc-link"
        :class="{
          'is-active': heading.id === activeId,
          'is-nested': heading.level === 3,
        }"
      >
        {{ heading.text }}
      </a>
    </nav>
  </aside>
</template>
