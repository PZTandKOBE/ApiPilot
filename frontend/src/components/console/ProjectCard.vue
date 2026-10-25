<script setup lang="ts">
import { Clock, Delete, Document, Grid } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useNow } from '@/composables/useNow'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import { formatRelativeTime } from '@/utils/time'
import type { Project } from '@/types/project'

/**
 * Project entry, in two densities.
 *
 * `grid` is the projects page; `row` is the dashboard strip. Same component so
 * the two never drift into showing different facts about a project.
 */
const props = withDefaults(
  defineProps<{
    project: Project
    variant?: 'grid' | 'row'
  }>(),
  { variant: 'grid' },
)

const emit = defineEmits<{ readonly delete: [] }>()

const { t, locale } = useI18n()
const store = useProjectStore()
const now = useNow()

const isActive = computed(() => store.activeProjectId === props.project.id)

const to = computed(() => ({
  name: 'console-project-overview',
  params: { projectId: props.project.id },
}))

const updatedLabel = computed(() => {
  const relative = formatRelativeTime(props.project.updatedAt, locale.value, {
    now: now.value,
    justNow: t('console.common.justNow'),
  })

  return t('console.project.updated', {
    time: relative === '' ? t('console.common.unknown') : relative,
  })
})

const specLabel = computed(
  () => props.project.specName ?? t('console.overview.noSpec'),
)

const environmentCount = computed(() => props.project.environments.length)
</script>

<template>
  <div
    class="group console-panel relative block transition-colors duration-150 hover:border-[var(--console-border-strong)]"
    :class="[
      variant === 'grid' ? 'h-full' : '',
      isActive ? 'border-[var(--console-border-strong)]' : '',
    ]"
  >
    <RouterLink
      :to="to"
      class="flex min-w-0"
      :class="
        variant === 'grid'
          ? 'h-full flex-col gap-3 p-4 pr-10'
          : 'items-center gap-4 px-3.5 py-2.5 pr-10'
      "
    >
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <h3
          class="truncate text-[13.5px] font-medium text-[var(--console-text)] group-hover:text-[var(--accent-soft)]"
        >
          {{ project.name }}
        </h3>
        <span
          v-if="isActive"
          class="shrink-0 rounded-full bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent-soft)]"
        >
          {{ t('console.project.switcherLabel') }}
        </span>
      </div>

      <p
        class="mt-1 text-[12px] leading-relaxed text-[var(--console-text-dim)]"
        :class="variant === 'row' ? 'truncate' : 'line-clamp-2'"
      >
        {{ project.description }}
      </p>
    </div>

    <div
      class="flex items-center gap-3 text-[11px] text-[var(--console-text-muted)]"
      :class="variant === 'grid' ? 'mt-auto flex-wrap gap-x-4 pt-1' : 'shrink-0'"
    >
      <span class="flex items-center gap-1.5">
        <ElIcon :size="13"><Document /></ElIcon>
        <span class="max-w-[160px] truncate font-mono">{{ specLabel }}</span>
      </span>

      <span class="flex items-center gap-1.5" :title="t('console.environment.label')">
        <ElIcon :size="13"><Grid /></ElIcon>
        <span>{{ environmentCount }}</span>
      </span>

      <span class="flex items-center gap-1.5">
        <ElIcon :size="13"><Clock /></ElIcon>
        <span>{{ updatedLabel }}</span>
      </span>
    </div>
    </RouterLink>

    <ElButton
      link
      type="danger"
      size="small"
      class="absolute right-1.5"
      :class="variant === 'row' ? 'top-1/2 -translate-y-1/2' : 'top-1.5'"
      :aria-label="t('console.project.delete')"
      :title="t('console.project.delete')"
      @click.stop="emit('delete')"
    >
      <ElIcon :size="14"><Delete /></ElIcon>
    </ElButton>
  </div>
</template>
