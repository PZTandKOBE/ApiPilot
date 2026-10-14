<script setup lang="ts">
import { ArrowDown, Folder } from '@element-plus/icons-vue'
import { ElDropdown, ElDropdownItem, ElDropdownMenu, ElIcon } from 'element-plus'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'

/**
 * Project picker in the top bar.
 *
 * Selecting a project while inside a workspace keeps you on the *same page* of
 * the project you just switched to — landing back on a generic overview after
 * every switch would lose the user's place, which is exactly the context they
 * were trying to change.
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useProjectStore()

/**
 * What the button says.
 *
 * Three states, and the middle one is why this is not a two-way fallback: while
 * the list is on its way, "No projects yet" would be a claim the console cannot
 * make yet — and before this store stopped seeding itself, the button instead
 * named a project the visitor had not been shown to own.  Loading says what is
 * true: the answer has not arrived.
 */
const activeName = computed(() => {
  const active = store.activeProject
  if (active !== null) return active.name

  return store.status === 'loading' || store.status === 'idle'
    ? t('console.common.loading')
    : t('console.project.noProjects')
})

const isWorkspaceRoute = computed(
  () => typeof route.name === 'string' && route.name.startsWith('console-project-'),
)

/** Element Plus emits `string | number | object`; only ids ever come through. */
const onCommand = (command: unknown): void => {
  if (typeof command !== 'string') return

  if (command === 'all-projects') {
    void router.push({ name: 'console-projects' })
    return
  }

  store.selectProject(command)

  if (isWorkspaceRoute.value) {
    void router.push({
      name: route.name as string,
      params: { ...route.params, projectId: command },
    })
  }
}
</script>

<template>
  <ElDropdown trigger="click" placement="bottom-start" @command="onCommand">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-[13px] font-medium text-[var(--console-text)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)]"
    >
      <ElIcon :size="15" class="text-[var(--accent-soft)]">
        <Folder />
      </ElIcon>
      <span class="max-w-[180px] truncate">{{ activeName }}</span>
      <ElIcon :size="12" class="text-[var(--console-text-muted)]">
        <ArrowDown />
      </ElIcon>
    </button>

    <template #dropdown>
      <ElDropdownMenu class="min-w-[220px]">
        <ElDropdownItem
          v-for="project in store.projects"
          :key="project.id"
          :command="project.id"
        >
          <span class="flex w-full items-center justify-between gap-4">
            <span
              :class="
                project.id === store.activeProjectId
                  ? 'text-[var(--accent-soft)]'
                  : ''
              "
            >
              {{ project.name }}
            </span>
            <span class="font-mono text-[11px] opacity-45">
              {{ project.environments.length }}
            </span>
          </span>
        </ElDropdownItem>

        <ElDropdownItem divided command="all-projects">
          {{ t('console.nav.projects') }}
        </ElDropdownItem>
      </ElDropdownMenu>
    </template>
  </ElDropdown>
</template>
