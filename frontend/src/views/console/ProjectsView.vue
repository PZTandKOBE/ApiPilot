<script setup lang="ts">
import { Folder, Plus } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import ProjectCard from '@/components/console/ProjectCard.vue'
import ProjectCreateDialog from '@/components/console/ProjectCreateDialog.vue'
import ProjectDeleteDialog from '@/components/console/ProjectDeleteDialog.vue'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types/project'

/**
 * Project index.
 *
 * The hub of the console's central concept: everything the agent produces —
 * plans, runs, reports — hangs off a project, so this is the page that has to
 * make picking one obvious, and the page that has to make *making* one possible.
 *
 * The creation entry is here in both states of the list. An empty list is the
 * moment a new guest most needs it, so it sits inside the empty state rather than
 * only in the header — a page whose whole content says "no projects" and offers
 * no way to make one is a dead end.
 *
 * The dialog creates; this page navigates. The store's action has already made the
 * new project active by the time the dialog reports success, so the push carries
 * the address bar to the project the console is already showing — the two cannot
 * disagree, which is the failure this page would otherwise be free to commit.
 */
const { t } = useI18n()
const router = useRouter()
const store = useProjectStore()

const createOpen = ref(false)
const deleteTarget = ref<Project | null>(null)
const deleteOpen = ref(false)

const openDelete = (project: Project): void => {
  deleteTarget.value = project
  deleteOpen.value = true
}

const onCreated = (projectId: string): void => {
  void router.push({ name: 'console-project-overview', params: { projectId } })
}
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      :title="t('console.nav.projects')"
      :subtitle="t('console.dashboard.subtitle')"
    >
      <template #actions>
        <ElButton type="primary" size="small" @click="createOpen = true">
          <ElIcon class="mr-1"><Plus /></ElIcon>
          {{ t('console.project.create') }}
        </ElButton>
      </template>
    </ConsolePageHeader>

    <div
      v-if="store.projects.length > 0"
      class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      <ProjectCard
        v-for="project in store.projects"
        :key="project.id"
        :project="project"
        @delete="openDelete(project)"
      />
    </div>

    <div v-else class="console-panel">
      <ConsoleEmptyState
        :icon="Folder"
        :title="t('console.project.noProjects')"
        :body="t('console.project.createBody')"
      >
        <ElButton type="primary" size="small" @click="createOpen = true">
          {{ t('console.project.create') }}
        </ElButton>
      </ConsoleEmptyState>
    </div>

    <ProjectCreateDialog v-model="createOpen" @created="onCreated" />

    <ProjectDeleteDialog
      v-if="deleteTarget !== null"
      v-model="deleteOpen"
      :project="deleteTarget"
    />
  </div>
</template>
