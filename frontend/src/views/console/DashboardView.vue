<script setup lang="ts">
import { Grid, MagicStick, Tickets, VideoPlay } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AgentTaskStatusTag from '@/components/console/Agent/AgentTaskStatusTag.vue'
import PlanRiskTag from '@/components/console/Agent/PlanRiskTag.vue'
import PlanStatusTag from '@/components/console/Agent/PlanStatusTag.vue'
import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import ProjectCard from '@/components/console/ProjectCard.vue'
import ProjectDeleteDialog from '@/components/console/ProjectDeleteDialog.vue'
import RunStatusTag from '@/components/console/Run/RunStatusTag.vue'
import { useNow } from '@/composables/useNow'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import type { TestPlan } from '@/types/agent'
import type { Project } from '@/types/project'
import type { TestRun } from '@/types/run'
import { formatRelativeTime } from '@/utils/time'

/**
 * Console home for the active project.
 *
 * The project list is console-wide, but every activity list the console has is
 * project-scoped. The dashboard therefore shows the selected project's latest
 * work; switching project in the top bar re-points all three cards without
 * inventing a second navigation model.
 *
 * The agent activity card reads the project's persisted agent tasks from the
 * dedicated collection endpoint, so pending, analysing, failed and completed
 * work is visible whether or not a plan was ever produced.
 */
const router = useRouter()
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const projectStore = useProjectStore()
const agentStore = useAgentStore()
const runsStore = useRunsStore()
const now = useNow()

const deleteTarget = ref<Project | null>(null)
const deleteOpen = ref(false)

const openDelete = (project: Project): void => {
  deleteTarget.value = project
  deleteOpen.value = true
}

const projectId = computed(() => projectStore.activeProjectId)
const projectReady = computed(() => projectStore.status === 'ready')
const projectLoading = computed(
  () => projectStore.status === 'idle' || projectStore.status === 'loading',
)
const projectFailed = computed(() => projectStore.status === 'error')

const recentTasks = computed(() => agentStore.projectTasks)

const hasAnyPlan = computed(() => agentStore.projectPlans.length > 0)

/**
 * Only current versions can be pending. Old versions stay in the list for
 * historical runs, but they are not what the reviewer is being asked to decide.
 */
const pendingPlans = computed<readonly TestPlan[]>(() =>
  [...agentStore.projectPlans]
    .filter(
      (plan) =>
        plan.isCurrent !== false &&
        (plan.status === 'draft' || plan.status === 'in_review'),
    )
    .sort((left, right) => right.generatedAt.localeCompare(left.generatedAt))
    .slice(0, 3),
)

const recentRuns = computed<readonly TestRun[]>(() =>
  runsStore.projectRuns.slice(0, 3),
)

const plansFailed = computed(() => agentStore.plansError !== null)
const runsFailed = computed(() => runsStore.error !== null)
const tasksFailed = computed(() => agentStore.tasksError !== null)

/**
 * All relative labels on this page share one clock and one just-now sentence.
 * The clock is also what makes the values advance while the page stays open.
 */
const timeAgo = (value: string): string => {
  const relative = formatRelativeTime(value, locale.value, {
    now: now.value,
    justNow: t('console.common.justNow'),
  })

  return relative === '' ? t('console.common.unknown') : relative
}

const planTarget = (plan: TestPlan) => ({
  name: 'console-project-plan-detail' as const,
  params: { projectId: projectId.value, planId: plan.id },
})

const runTarget = (run: TestRun) => ({
  name: 'console-project-run-detail' as const,
  params: { projectId: projectId.value, runId: run.id },
})

const openTestLab = (): void => {
  if (!projectReady.value) return
  void router.push({
    name: 'console-project-ai-test',
    params: { projectId: projectId.value },
  })
}

const openPlans = (): void => {
  if (!projectReady.value) return
  void router.push({
    name: 'console-project-plans',
    params: { projectId: projectId.value },
  })
}

const openRuns = (): void => {
  if (!projectReady.value) return
  void router.push({
    name: 'console-project-runs',
    params: { projectId: projectId.value },
  })
}

const openProjects = (): void => {
  void router.push({ name: 'console-projects' })
}

const reloadPlans = async (): Promise<void> => {
  if (!projectReady.value) return
  await agentStore.loadPlans()
}

const reloadRuns = async (): Promise<void> => {
  if (!projectReady.value) return
  await runsStore.loadRuns()
}

const reloadTasks = async (): Promise<void> => {
  if (!projectReady.value) return
  await agentStore.loadTasks()
}

/**
 * The lists are all project-scoped. Running them together keeps the three
 * cards on the same project even when one of them fails.
 */
const reloadProjectData = async (): Promise<void> => {
  if (!projectReady.value) return
  await Promise.all([reloadPlans(), reloadRuns(), reloadTasks()])
}

const retryProject = async (): Promise<void> => {
  await projectStore.initialize()
}

onMounted(() => {
  if (projectReady.value) void reloadProjectData()
})

// ConsoleLayout may still be initialising the project list when this page
// mounts. Loading the project-scoped lists before the id is known would request
// a project the guest has not been shown to own.
watch(
  () => projectStore.status,
  (status) => {
    if (status === 'ready') void reloadProjectData()
  },
)

watch(
  () => projectStore.activeProjectId,
  (id, previous) => {
    if (id === previous || !projectReady.value) return
    void reloadProjectData()
  },
)
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      :title="t('console.dashboard.title')"
      :subtitle="t('console.dashboard.subtitle')"
    />

    <!-- The project list itself is still loading. Do not show "no projects"
         for a question that has not been answered yet. -->
    <div
      v-if="projectLoading"
      class="console-panel p-4"
      role="status"
      :aria-label="t('console.common.loading')"
    >
      <div class="h-4 w-36 animate-pulse rounded bg-white/[0.06]" />
      <div class="mt-4 grid gap-2 sm:grid-cols-2">
        <div
          v-for="index in 4"
          :key="index"
          class="h-24 animate-pulse rounded-lg bg-white/[0.035]"
        />
      </div>
    </div>

    <!-- The project bootstrap failed: this is a page-level failure, not three
         independent empty lists. -->
    <div v-else-if="projectFailed" class="console-panel p-5" role="alert">
      <p class="text-[13px] font-medium text-[var(--console-text)]">
        {{ t('console.dashboard.projectErrorTitle') }}
      </p>
      <p class="mt-1.5 text-[12px] leading-relaxed text-[var(--console-text-dim)]">
        {{ t('console.dashboard.projectErrorBody') }}
      </p>
      <ElButton class="mt-3" size="small" @click="retryProject">
        {{ t('console.common.retry') }}
      </ElButton>
    </div>

    <template v-else>
      <div class="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <!-- Projects -->
        <section class="console-panel flex flex-col overflow-hidden">
          <header
            class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
          >
            <div class="flex min-w-0 items-center gap-2.5">
              <ElIcon :size="14" class="shrink-0 text-[var(--console-text-muted)]">
                <Grid />
              </ElIcon>
              <h2 class="truncate text-[12.5px] font-semibold text-[var(--console-text)]">
                {{ t('console.dashboard.projectsTitle') }}
              </h2>
            </div>
            <RouterLink
              :to="{ name: 'console-projects' }"
              class="text-[11.5px] text-[var(--accent-soft)] hover:underline"
            >
              {{ t('console.dashboard.viewAll') }}
            </RouterLink>
          </header>

          <div v-if="projectStore.projects.length === 0" class="p-3">
            <ConsoleEmptyState
              :title="t('console.project.noProjects')"
              :body="t('console.project.createBody')"
            >
              <ElButton size="small" @click="openProjects">
                {{ t('console.nav.projects') }}
              </ElButton>
            </ConsoleEmptyState>
          </div>

          <div v-else class="flex flex-col gap-2 p-3">
            <ProjectCard
              v-for="project in projectStore.projects"
              :key="project.id"
              :project="project"
              variant="row"
              @delete="openDelete(project)"
            />
          </div>
        </section>

        <!-- Agent activity -->
        <section class="console-panel flex flex-col overflow-hidden">
          <header class="flex items-center gap-3 border-b border-[var(--console-border)] px-4 py-3">
            <div class="flex min-w-0 items-center gap-2.5">
              <ElIcon :size="14" class="shrink-0 text-[var(--accent)]">
                <MagicStick />
              </ElIcon>
              <h2 class="truncate text-[12.5px] font-semibold text-[var(--console-text)]">
                {{ t('console.dashboard.agentTitle') }}
              </h2>
            </div>
          </header>

          <div
            v-if="tasksFailed"
            class="border-b border-[var(--console-border)] px-4 py-3"
            role="alert"
          >
            <p class="text-[12px] font-medium text-[var(--status-fail)]">
              {{ t('console.dashboard.tasksLoadFailed') }}
            </p>
            <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-dim)]">
              {{ t('console.dashboard.tasksLoadFailedBody') }}
            </p>
            <ElButton class="mt-2" size="small" @click="reloadTasks">
              {{ t('console.common.retry') }}
            </ElButton>
          </div>

          <div
            v-if="agentStore.tasksLoading && recentTasks.length === 0"
            class="space-y-2 p-3"
            role="status"
            :aria-label="t('console.common.loading')"
          >
            <div
              v-for="index in 3"
              :key="index"
              class="h-11 animate-pulse rounded-md bg-white/[0.035]"
            />
          </div>

          <div
            v-else-if="recentTasks.length === 0 && !tasksFailed"
            class="p-3"
          >
            <ConsoleEmptyState
              :icon="MagicStick"
              :title="t('console.dashboard.agentEmpty')"
              :body="t('console.dashboard.agentEmptyBody')"
            >
              <ElButton size="small" type="primary" @click="openTestLab">
                {{ t('console.nav.aiTestLab') }}
              </ElButton>
            </ConsoleEmptyState>
          </div>

          <ul v-else-if="recentTasks.length > 0" class="divide-y divide-[var(--console-border)]">
            <li
              v-for="task in recentTasks"
              :key="task.id"
              class="flex items-start gap-3 px-4 py-3"
            >
              <span class="min-w-0 flex-1">
                <span class="line-clamp-2 text-[12.5px] font-medium leading-relaxed text-[var(--console-text)]">
                  {{ task.prompt }}
                </span>
                <span class="mt-1 block text-[11px] text-[var(--console-text-dim)]">
                  {{ timeAgo(task.createdAt) }}
                </span>
              </span>
              <AgentTaskStatusTag :status="task.status" />
            </li>
          </ul>
        </section>
      </div>

      <div class="mt-4 grid gap-4 lg:grid-cols-2">
        <!-- Plans awaiting approval -->
        <section class="console-panel flex flex-col overflow-hidden">
          <header
            class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
          >
            <div class="flex min-w-0 items-center gap-2.5">
              <ElIcon :size="14" class="shrink-0 text-[var(--console-text-muted)]">
                <Tickets />
              </ElIcon>
              <h2 class="truncate text-[12.5px] font-semibold text-[var(--console-text)]">
                {{ t('console.dashboard.plansTitle') }}
              </h2>
            </div>
            <RouterLink
              :to="{ name: 'console-project-plans', params: { projectId } }"
              class="shrink-0 text-[11.5px] text-[var(--accent-soft)] hover:underline"
            >
              {{ t('console.dashboard.viewAll') }}
            </RouterLink>
          </header>

          <div
            v-if="plansFailed"
            class="border-b border-[var(--console-border)] px-4 py-3"
            role="alert"
          >
            <p class="text-[12px] font-medium text-[var(--status-fail)]">
              {{ t('console.dashboard.plansLoadFailed') }}
            </p>
            <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-dim)]">
              {{ t('console.dashboard.plansLoadFailedBody') }}
            </p>
            <ElButton class="mt-2" size="small" @click="reloadPlans">
              {{ t('console.common.retry') }}
            </ElButton>
          </div>

          <div
            v-if="agentStore.plansLoading && pendingPlans.length === 0"
            class="space-y-2 p-3"
            role="status"
            :aria-label="t('console.common.loading')"
          >
            <div
              v-for="index in 2"
              :key="index"
              class="h-11 animate-pulse rounded-md bg-white/[0.035]"
            />
          </div>

          <div
            v-else-if="pendingPlans.length === 0 && !plansFailed"
            class="p-3"
          >
            <ConsoleEmptyState
              :icon="Tickets"
              :title="t('console.dashboard.plansEmpty')"
              :body="t('console.dashboard.plansEmptyBody')"
            >
              <ElButton
                v-if="hasAnyPlan"
                size="small"
                @click="openPlans"
              >
                {{ t('console.dashboard.openPlans') }}
              </ElButton>
              <ElButton v-else size="small" type="primary" @click="openTestLab">
                {{ t('console.nav.aiTestLab') }}
              </ElButton>
            </ConsoleEmptyState>
          </div>

          <ul v-else-if="pendingPlans.length > 0" class="divide-y divide-[var(--console-border)]">
            <li v-for="plan in pendingPlans" :key="plan.id">
              <RouterLink
                :to="planTarget(plan)"
                class="flex items-start gap-3 px-4 py-3 transition-colors duration-150 hover:bg-[var(--console-surface-hover)]"
              >
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] font-medium text-[var(--console-text)]">
                    {{ localize(plan.name) }}
                  </span>
                  <span class="mt-1 flex items-center gap-1.5 text-[11px] text-[var(--console-text-dim)]">
                    <span class="font-mono">v{{ plan.version ?? 1 }}</span>
                    <span aria-hidden="true">·</span>
                    <span>{{ timeAgo(plan.generatedAt) }}</span>
                  </span>
                </span>
                <span class="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                  <PlanRiskTag :level="plan.riskLevel" />
                  <PlanStatusTag :status="plan.status" />
                </span>
              </RouterLink>
            </li>
          </ul>
        </section>

        <!-- Recent runs -->
        <section class="console-panel flex flex-col overflow-hidden">
          <header
            class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
          >
            <div class="flex min-w-0 items-center gap-2.5">
              <ElIcon :size="14" class="shrink-0 text-[var(--console-text-muted)]">
                <VideoPlay />
              </ElIcon>
              <h2 class="truncate text-[12.5px] font-semibold text-[var(--console-text)]">
                {{ t('console.dashboard.runsTitle') }}
              </h2>
            </div>
            <RouterLink
              :to="{ name: 'console-project-runs', params: { projectId } }"
              class="shrink-0 text-[11.5px] text-[var(--accent-soft)] hover:underline"
            >
              {{ t('console.dashboard.viewAll') }}
            </RouterLink>
          </header>

          <div
            v-if="runsFailed"
            class="border-b border-[var(--console-border)] px-4 py-3"
            role="alert"
          >
            <p class="text-[12px] font-medium text-[var(--status-fail)]">
              {{ t('console.dashboard.runsLoadFailed') }}
            </p>
            <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-dim)]">
              {{ t('console.dashboard.runsLoadFailedBody') }}
            </p>
            <ElButton class="mt-2" size="small" @click="reloadRuns">
              {{ t('console.common.retry') }}
            </ElButton>
          </div>

          <div
            v-if="runsStore.listing && recentRuns.length === 0"
            class="space-y-2 p-3"
            role="status"
            :aria-label="t('console.common.loading')"
          >
            <div
              v-for="index in 2"
              :key="index"
              class="h-11 animate-pulse rounded-md bg-white/[0.035]"
            />
          </div>

          <div
            v-else-if="recentRuns.length === 0 && !runsFailed"
            class="p-3"
          >
            <ConsoleEmptyState
              :icon="VideoPlay"
              :title="t('console.dashboard.runsEmpty')"
              :body="t('console.dashboard.runsEmptyBody')"
            >
              <ElButton
                v-if="runsStore.canCreateRun"
                size="small"
                type="primary"
                @click="openRuns"
              >
                {{ t('console.runs.newRun') }}
              </ElButton>
              <ElButton v-else size="small" type="primary" @click="openTestLab">
                {{ t('console.nav.aiTestLab') }}
              </ElButton>
            </ConsoleEmptyState>
          </div>

          <ul v-else-if="recentRuns.length > 0" class="divide-y divide-[var(--console-border)]">
            <li v-for="run in recentRuns" :key="run.id">
              <RouterLink
                :to="runTarget(run)"
                class="flex items-center gap-3 px-4 py-3 transition-colors duration-150 hover:bg-[var(--console-surface-hover)]"
              >
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[12.5px] font-medium text-[var(--console-text)]">
                    {{ localize(run.planName) }}
                  </span>
                  <span class="mt-1 block text-[11px] text-[var(--console-text-dim)]">
                    {{ timeAgo(run.createdAt) }}
                  </span>
                </span>
                <RunStatusTag :status="run.status" />
              </RouterLink>
            </li>
          </ul>
        </section>
      </div>

      <ProjectDeleteDialog
        v-if="deleteTarget !== null"
        v-model="deleteOpen"
        :project="deleteTarget"
      />
    </template>
  </div>
</template>
