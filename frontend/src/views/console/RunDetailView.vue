<script setup lang="ts">
import { Back, Tickets } from '@element-plus/icons-vue'
import { ElButton, ElIcon, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import RunErrorNote from '@/components/console/Run/RunErrorNote.vue'
import RunFailureNote from '@/components/console/Run/RunFailureNote.vue'
import RunScenarioCard from '@/components/console/Run/RunScenarioCard.vue'
import RunStatusTag from '@/components/console/Run/RunStatusTag.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useRunsStore } from '@/stores/runs'
import { isTerminalRunStatus, type RunDetail } from '@/types/run'
import { formatRelativeTime } from '@/utils/time'

/**
 * One run, followed while it happens.
 *
 * The page owns nothing: the snapshot, the stream and the high-water mark all
 * live in the run store, so navigating away and back resumes the same run
 * rather than starting a second one. Everything drawn here comes from the
 * loaded detail — the run's own scenarios, its own summary — because a plan
 * can be regenerated under the same id while this run is in flight.
 *
 * The load happens on mount rather than during setup: rendering is not a
 * reason to talk to the server, and the store's guards are not a substitute
 * for not asking in the first place. Moving between two runs is the same
 * question asked again, so the param is watched as well as mounted.
 */
const { t, locale } = useI18n()
const { localize } = useLocalizedText()
const store = useRunsStore()
const route = useRoute()
const router = useRouter()

const runId = computed<string | null>(() => {
  const value = route.params.runId
  return typeof value === 'string' && value !== '' ? value : null
})

const open = (): void => {
  if (runId.value !== null) void store.openRun(runId.value)
}

onMounted(open)
// Router reuses this component when only the param changes, so the mount hook
// does not fire again — the param is what has to be watched.
watch(runId, open)

/**
 * Leaving the page releases the stream.
 *
 * The connection is the store's — a run is not a component's property, and
 * navigating away must not stop one — but *watching* it is this page's, and a
 * page that is gone has nobody to deliver events to. Closing here is safe
 * precisely because the store keeps the high-water mark: coming back subscribes
 * again, the server replays from the beginning, and every event at or below the
 * mark is dropped on arrival.
 */
onUnmounted(() => {
  if (runId.value !== null) store.unsubscribe(runId.value)
})

/**
 * The run the url names — not `activeDetail`, which is whichever run was
 * opened last. A page whose subject comes from the address bar has to read it
 * from there: two runs can both be loaded, and only one of them is this page.
 */
const detail = computed<RunDetail | null>(() =>
  runId.value === null
    ? null
    : (store.details.find((candidate) => candidate.run.id === runId.value) ?? null),
)

/**
 * A run the server does not know about, or a url without an id at all.
 *
 * A detail that has not arrived yet is not a missing run: `loading` is what
 * separates "not loaded" from "not there", and without it the page would
 * accuse the server of having lost a run for as long as the snapshot takes.
 * The store's `run-not-found` error lands here too — a null detail is the
 * same answer whichever way it was reached.
 */
const notFound = computed(
  () => runId.value === null || (detail.value === null && !store.loading),
)

/**
 * Variables the run itself produced, from the successful Extract steps.
 *
 * The run history deliberately stores names, never values.  The extract step's
 * evidence is the name it lifted, so this is the same fact the executor wrote
 * without adding a second persistence path or exposing a value.
 */
const runtimeVariables = computed<readonly string[]>(() => {
  const names = new Set<string>()

  for (const scenario of detail.value?.scenarios ?? []) {
    for (const step of scenario.steps) {
      if (step.kind !== 'extract' || step.status !== 'passed') continue

      for (const evidence of step.evidence) {
        if (
          'key' in evidence.label &&
          evidence.label.key === 'console.runs.evidence.extracted' &&
          evidence.value !== ''
        ) {
          names.add(evidence.value)
        }
      }
    }
  }

  return [...names].sort()
})

const cancelling = computed(() => store.cancelling)

/** A report is final only once the server says the run is finished. */
const canReport = computed(
  () => detail.value !== null && isTerminalRunStatus(detail.value.run.status),
)

const openReport = (): void => {
  if (!canReport.value || runId.value === null) return

  const projectId = route.params.projectId
  if (typeof projectId !== 'string' || projectId === '') return

  void router.push({
    name: 'console-project-run-report',
    params: { projectId, runId: runId.value },
  })
}

/** Settled: passed, failed and cancelled are the three states nothing leaves. */
const cancelDisabled = computed(
  () => cancelling.value || detail.value === null || isTerminalRunStatus(detail.value.run.status),
)

const following = computed(
  () => detail.value !== null && store.subscribedRunIds.includes(detail.value.run.id),
)

/** `842 ms`, `4.2 s` — a run is measured in one unit or the other, never both. */
const durationOf = (millis: number): string =>
  millis < 1000 ? `${Math.round(millis)} ms` : `${(millis / 1000).toFixed(1)} s`

/**
 * Confirming is the decision, not the dialog. `ElMessageBox` rejects when it
 * is dismissed, and a rejection is what a dismissal is — so it is caught and
 * read as "no", never left to surface as an unhandled one.
 */
const cancelRun = async (): Promise<void> => {
  const current = detail.value
  if (current === null) return

  const confirmed = await ElMessageBox.confirm(
    t('console.runs.cancelConfirm'),
    t('console.runs.cancel'),
    {
      confirmButtonText: t('console.runs.cancel'),
      cancelButtonText: t('console.common.cancel'),
      type: 'warning',
    },
  ).catch(() => undefined)

  if (confirmed === undefined) return

  await store.cancelRun(current.run.id)
}
</script>

<template>
  <div class="console-page">
    <!-- The run the url points at is not one this project has -->
    <div v-if="notFound" class="console-panel">
      <ConsoleEmptyState
        :icon="Tickets"
        :title="t('console.runs.notFound')"
        :body="t('console.runs.notFoundBody')"
      >
        <div class="flex flex-wrap items-center justify-center gap-2">
          <RouterLink
            :to="{ name: 'console-project-runs' }"
            class="rounded-md border border-[var(--console-border)] px-3 py-1.5 text-[12px] text-[var(--console-text-dim)] hover:border-[var(--console-border-strong)]"
          >
            {{ t('console.runs.backToList') }}
          </RouterLink>

          <RouterLink
            :to="{ name: 'console-project-plans' }"
            class="inline-flex items-center gap-1.5 rounded-md border border-[var(--console-border-strong)] px-3 py-1.5 text-[12px] text-[var(--accent-soft)]"
          >
            <ElIcon :size="13"><Tickets /></ElIcon>
            {{ t('console.runs.openPlan') }}
          </RouterLink>
        </div>
      </ConsoleEmptyState>
    </div>

    <template v-else-if="detail !== null">
      <ConsolePageHeader
        :title="localize(detail.run.planName)"
        :eyebrow="t('console.runs.title')"
      >
        <template #meta>
          <RouterLink
            :to="{ name: 'console-project-runs' }"
            class="mt-2 flex items-center gap-1.5 text-[11.5px] text-[var(--accent-soft)] hover:underline"
          >
            <ElIcon :size="11"><Back /></ElIcon>
            {{ t('console.runs.backToList') }}
          </RouterLink>
        </template>

        <template #actions>
          <RunStatusTag :status="detail.run.status" />

          <ElButton
            size="small"
            :disabled="!canReport"
            :title="canReport ? t('console.report.open') : t('console.report.unavailable')"
            @click="openReport"
          >
            {{ t('console.report.open') }}
          </ElButton>

          <ElButton size="small" :disabled="cancelDisabled" @click="cancelRun">
            {{ cancelling ? t('console.runs.cancelling') : t('console.runs.cancel') }}
          </ElButton>
        </template>
      </ConsolePageHeader>

      <div class="flex flex-col gap-4">
        <!-- The stream is open on this run right now -->
        <p
          v-if="!canReport && detail !== null"
          class="text-[11.5px] text-[var(--console-text-muted)]"
        >
          {{ t('console.report.unavailableBody') }}
        </p>

        <p
          v-if="following"
          class="flex flex-wrap items-center gap-2 text-[11.5px] text-[var(--console-text-dim)]"
        >
          <span
            class="rounded border px-1.5 py-px text-[10px] whitespace-nowrap"
            :style="{
              color: 'var(--accent-soft)',
              borderColor: 'color-mix(in srgb, var(--accent) 34%, transparent)',
            }"
          >
            {{ t('console.runs.live') }}
          </span>
          {{ t('console.runs.following') }}
        </p>

        <RunErrorNote
          v-if="store.error !== null"
          :error="store.error"
          @dismiss="store.clearError()"
        />

        <section class="console-panel p-4">
          <dl class="flex flex-wrap gap-x-8 gap-y-3">
            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.plan') }}</dt>
              <dd class="truncate text-[12px] text-[var(--console-text-dim)]">
                {{ localize(detail.run.planName) }}
              </dd>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.planId') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ detail.run.planId }}
              </dd>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.environment') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ detail.run.environmentId }}
              </dd>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.baseUrl') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ detail.run.baseUrl }}
              </dd>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.variables') }}</dt>
              <!-- Names only: a run history is not the place to accumulate secrets. -->
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{
                  detail.run.variableKeys.length === 0
                    ? t('console.common.none')
                    : detail.run.variableKeys.join(', ')
                }}
              </dd>
              <p class="text-[10.5px] leading-4 text-[var(--console-text-muted)]">
                {{ t('console.runs.variablesHint') }}
              </p>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.runtimeVariables') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{
                  runtimeVariables.length === 0
                    ? t('console.runs.noRuntimeVariables')
                    : runtimeVariables.join(', ')
                }}
              </dd>
              <p class="text-[10.5px] leading-4 text-[var(--console-text-muted)]">
                {{ t('console.runs.runtimeVariablesHint') }}
              </p>
            </div>

            <div class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.createdAt') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ formatRelativeTime(detail.run.createdAt, locale) }}
              </dd>
            </div>

            <div v-if="detail.run.finishedAt !== null" class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.finishedAt') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ formatRelativeTime(detail.run.finishedAt, locale) }}
              </dd>
            </div>

            <div v-if="detail.run.durationMs !== null" class="flex min-w-0 flex-col gap-0.5">
              <dt class="console-label">{{ t('console.runs.duration') }}</dt>
              <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
                {{ durationOf(detail.run.durationMs) }}
              </dd>
            </div>
          </dl>
        </section>

        <section v-if="detail.run.failure !== null" class="console-panel p-4">
          <p class="console-label">{{ t('console.runs.failure.heading') }}</p>
          <RunFailureNote class="mt-2" :failure="detail.run.failure" />
        </section>

        <RunScenarioCard
          v-for="scenario in detail.scenarios"
          :key="scenario.id"
          :scenario="scenario"
        />
      </div>
    </template>
  </div>
</template>
