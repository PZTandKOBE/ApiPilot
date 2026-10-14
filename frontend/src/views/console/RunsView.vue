<script setup lang="ts">
import { VideoPlay } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import RunErrorNote from '@/components/console/Run/RunErrorNote.vue'
import RunStatusTag from '@/components/console/Run/RunStatusTag.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import { useRunsStore } from '@/stores/runs'
import type { TestRun } from '@/types/run'
import { formatRelativeTime } from '@/utils/time'

/**
 * Every run this project has started.
 *
 * Reads `store.projectRuns` directly, for the same reason the plan list reads
 * the plan store: a page that kept its own copy would be a second answer to
 * "what has run here". The counts come from the run's own summary rather than
 * from counting its scenarios — the list never loads a detail it will not
 * draw, so the summary is the only thing it has and the only thing it needs.
 *
 * Starting a run is deliberately the only action on this page. Cancelling,
 * following and reading belong to a run's own page, where the thing being
 * acted on is in front of the user.
 */
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const store = useRunsStore()
const projectStore = useProjectStore()
const router = useRouter()

const counts = (run: TestRun): string =>
  `${run.summary.scenarios} ${t('console.aiTest.plan.scenarios')} · ${run.summary.steps} ${t('console.aiTest.plan.steps')} · ${run.summary.assertions} ${t('console.aiTest.plan.assertions')}`

/**
 * A run is created from the approved plan and then opened, so the user lands
 * on the thing that is now happening rather than on a list that will change
 * under them. A refusal leaves the reason in `store.error`, which the note
 * above the list already shows — there is nothing to add here.
 */
const startRun = async (): Promise<void> => {
  const run = await store.createRun()
  if (run === null) return

  await router.push({ name: 'console-project-run-detail', params: { runId: run.id } })
}

const detailTarget = (run: TestRun) => ({
  name: 'console-project-run-detail',
  params: { runId: run.id },
})

/**
 * The list is read from the server.
 *
 * On mount, and again whenever the project changes: a run list is server state
 * that outlives the tab, so there is nothing here to reconstruct — the page's
 * first paint has to ask. The watch lives in the view rather than in the store
 * on purpose, so that importing the store does not start issuing requests.
 */
onMounted(() => {
  void store.loadRuns()
})

watch(
  () => projectStore.activeProjectId,
  () => {
    void store.loadRuns()
  },
)
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader :title="t('console.runs.title')" :subtitle="t('console.runs.subtitle')">
      <template #actions>
        <ElButton
          size="small"
          type="primary"
          :disabled="!store.canCreateRun || store.creating"
          @click="startRun"
        >
          <ElIcon class="mr-1.5"><VideoPlay /></ElIcon>
          {{ store.creating ? t('console.runs.creating') : t('console.runs.newRun') }}
        </ElButton>
      </template>
    </ConsolePageHeader>

    <!-- Run is gated on an approved plan; the reason is stated, not implied. -->
    <p v-if="!store.canCreateRun" class="pb-3 text-[11.5px] text-[var(--console-text-muted)]">
      {{ t('console.runs.blocked') }}
    </p>

    <RunErrorNote v-if="store.error !== null" :error="store.error" @dismiss="store.clearError()" />

    <!-- Nothing is claimed until the server has answered: an empty state that
         appears while the request is still out says "no runs" about a page that
         does not know yet. -->
    <div v-if="!store.listing && store.projectRuns.length === 0" class="console-panel">
      <ConsoleEmptyState
        :icon="VideoPlay"
        :title="t('console.runs.empty')"
        :body="t('console.runs.emptyHint')"
      >
        <ElButton size="small" @click="$router.push({ name: 'console-project-ai-test' })">
          {{ t('console.runs.openLab') }}
        </ElButton>
      </ConsoleEmptyState>
    </div>

    <ul v-else class="flex flex-col gap-2.5">
      <li v-for="run in store.projectRuns" :key="run.id">
        <RouterLink
          :to="detailTarget(run)"
          class="console-panel block p-4 transition-colors duration-150 hover:border-[var(--console-border-strong)]"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <h2 class="min-w-0 truncate text-[13.5px] font-medium text-[var(--console-text)]">
              {{ localize(run.planName) }}
            </h2>

            <div class="flex shrink-0 items-center gap-2">
              <RunStatusTag :status="run.status" />
            </div>
          </div>

          <p class="mt-2.5 font-mono text-[11px] text-[var(--console-text-muted)]">
            {{ counts(run) }}
          </p>

          <dl class="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            <div class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.runs.createdAt') }}
              </dt>
              <dd class="font-mono text-[var(--console-text-dim)]">
                {{ formatRelativeTime(run.createdAt, locale) }}
              </dd>
            </div>

            <div class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.runs.environment') }}
              </dt>
              <dd class="text-[var(--console-text-dim)]">
                {{ run.environmentId }}
              </dd>
            </div>

            <div v-if="run.finishedAt !== null" class="flex items-baseline gap-1.5">
              <dt class="text-[var(--console-text-muted)]">
                {{ t('console.runs.finishedAt') }}
              </dt>
              <dd class="font-mono text-[var(--console-text-dim)]">
                {{ formatRelativeTime(run.finishedAt, locale) }}
              </dd>
            </div>
          </dl>
        </RouterLink>
      </li>
    </ul>
  </div>
</template>
