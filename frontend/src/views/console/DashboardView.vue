<script setup lang="ts">
import { MagicStick, Tickets, VideoPlay } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import ProjectCard from '@/components/console/ProjectCard.vue'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'

/**
 * Console home.
 *
 * The agent panel leads the page rather than the project list: this product's
 * differentiator is the agent's work, and a dashboard that opens on a list of
 * projects would read as a generic admin panel. Until the agent has run, that
 * panel states what would fill it and offers the action that starts it.
 */
const { t } = useI18n()
const router = useRouter()
const store = useProjectStore()

const testLabAvailable = computed(() => router.hasRoute('console-project-ai-test'))

const openTestLab = (): void => {
  if (!testLabAvailable.value || store.activeProject === null) return
  void router.push({
    name: 'console-project-ai-test',
    params: { projectId: store.activeProject.id },
  })
}
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      :title="t('console.dashboard.title')"
      :subtitle="t('console.dashboard.subtitle')"
    />

    <div class="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <!-- Projects -->
      <section class="console-panel flex flex-col">
        <header
          class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
        >
          <span class="console-label">{{ t('console.dashboard.projectsTitle') }}</span>
          <RouterLink
            :to="{ name: 'console-projects' }"
            class="text-[12px] text-[var(--accent-soft)] hover:underline"
          >
            {{ t('console.dashboard.viewAll') }}
          </RouterLink>
        </header>

        <div class="flex flex-col gap-2 p-3">
          <ProjectCard
            v-for="project in store.projects"
            :key="project.id"
            :project="project"
            variant="row"
          />
        </div>
      </section>

      <!-- Agent -->
      <section class="console-panel flex flex-col">
        <header
          class="flex items-center gap-2 border-b border-[var(--console-border)] px-4 py-3"
        >
          <ElIcon :size="14" class="text-[var(--accent)]"><MagicStick /></ElIcon>
          <span class="console-label">{{ t('console.dashboard.agentTitle') }}</span>
        </header>

        <div class="flex flex-1 items-center">
          <ConsoleEmptyState
            class="w-full"
            :body="t('console.dashboard.agentBody')"
            :title="t('console.dashboard.plansEmpty')"
          >
            <ElButton
              size="small"
              type="primary"
              :disabled="!testLabAvailable"
              :title="
                testLabAvailable ? undefined : t('console.nav.notBuiltYet')
              "
              @click="openTestLab"
            >
              {{ t('console.nav.aiTestLab') }}
            </ElButton>
          </ConsoleEmptyState>
        </div>
      </section>
    </div>

    <div class="mt-4 grid gap-4 lg:grid-cols-2">
      <!-- Awaiting approval -->
      <section class="console-panel">
        <header
          class="flex items-center gap-2 border-b border-[var(--console-border)] px-4 py-3"
        >
          <ElIcon :size="14" class="text-[var(--console-text-muted)]"><Tickets /></ElIcon>
          <span class="console-label">{{ t('console.dashboard.plansTitle') }}</span>
        </header>
        <ConsoleEmptyState :title="t('console.dashboard.plansEmpty')" />
      </section>

      <!-- Recent runs -->
      <section class="console-panel">
        <header
          class="flex items-center gap-2 border-b border-[var(--console-border)] px-4 py-3"
        >
          <ElIcon :size="14" class="text-[var(--console-text-muted)]"><VideoPlay /></ElIcon>
          <span class="console-label">{{ t('console.dashboard.runsTitle') }}</span>
        </header>
        <ConsoleEmptyState :title="t('console.dashboard.runsEmpty')" />
      </section>
    </div>
  </div>
</template>
