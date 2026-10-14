<script setup lang="ts">
import { Folder } from '@element-plus/icons-vue'
import { computed } from 'vue'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'

/**
 * Project workspace frame.
 *
 * Two jobs: guard the project id, and give the page inside a full-height
 * column to size itself against — the API Client fills, and this is the box
 * that answers.
 *
 * It claims that height by growing (`flex-1`) inside the shell's now-flex
 * column, not with `h-full`/`min-h-full`. The difference is the whole point
 * and it is not cosmetic: `min-h-full` leaves this element's `height` computed
 * as `auto`, and `height: 100%` against an auto-height parent computes to
 * `auto` — so the API Client silently collapsed to its content height, its two
 * columns stretched to match each other, and the rest of the viewport stayed
 * empty. A percentage needs a *definite* height on the containing block, and
 * `min-height` is not one.
 *
 * Content-height pages are untouched: as flex items they keep their own height
 * and overflow into the shell's scrolling pane, exactly as they did before.
 *
 * Navigation is deliberately not a job here. The console rail lists the
 * project destinations at every breakpoint, so a strip of them inside the page
 * would be the same list drawn twice.
 */
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const store = useProjectStore()

const project = computed(() => store.projectById(props.projectId))
</script>

<template>
  <div v-if="project" class="flex min-h-0 flex-1 flex-col">
    <RouterView />
  </div>

  <div v-else class="console-page">
    <div class="console-panel">
      <ConsoleEmptyState
        :icon="Folder"
        :title="t('console.project.notFound')"
        :body="t('console.project.notFoundBody')"
      >
        <RouterLink
          :to="{ name: 'console-projects' }"
          class="text-[12.5px] text-[var(--accent-soft)] hover:underline"
        >
          {{ t('console.project.backToProjects') }}
        </RouterLink>
      </ConsoleEmptyState>
    </div>
  </div>
</template>
