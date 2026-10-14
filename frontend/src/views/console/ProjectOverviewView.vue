<script setup lang="ts">
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import {
  ElButton,
  ElIcon,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import { formatDate } from '@/utils/time'
import type { EnvironmentKind, ProjectEnvironment } from '@/types/project'

/**
 * Project landing page.
 *
 * Answers the three questions a workspace has to answer on arrival: what is
 * this project, what environments can I fire requests at, and where do I go
 * next. The environment table leads because that is the fact most likely to
 * cause damage if it is wrong.
 */
const props = defineProps<{ projectId: string }>()

const { t, locale } = useI18n()
const router = useRouter()
const store = useProjectStore()

const project = computed(() => store.projectById(props.projectId))

const KIND_COLOR: Readonly<Record<EnvironmentKind, string>> = {
  development: 'var(--accent)',
  staging: 'var(--status-warn)',
  production: 'var(--status-fail)',
}

const KIND_LABEL_KEY: Readonly<Record<EnvironmentKind, string>> = {
  development: 'console.environment.development',
  staging: 'console.environment.staging',
  production: 'console.environment.production',
}

/**
 * `Project.environments` is readonly — domain data is not ours to mutate — but
 * `ElTable` types its `data` prop as a mutable array. The copy is what bridges
 * the two without weakening the model.
 */
const environments = computed<ProjectEnvironment[]>(() => [
  ...(project.value?.environments ?? []),
])

const kindLabel = (kind: EnvironmentKind): string => t(KIND_LABEL_KEY[kind])

const kindColor = (kind: EnvironmentKind): string => KIND_COLOR[kind]

const updatedLabel = computed(() => {
  const value = project.value?.updatedAt
  return value === undefined ? '' : formatDate(value, locale.value)
})

/** Both destinations arrive in later phases; until then the buttons are inert. */
const apiClientAvailable = computed(() => router.hasRoute('console-project-api'))
const testLabAvailable = computed(() => router.hasRoute('console-project-ai-test'))

const go = (name: string, available: boolean): void => {
  if (!available) return
  void router.push({ name, params: { projectId: props.projectId } })
}
</script>

<template>
  <div v-if="project" class="console-page">
    <ConsolePageHeader
      :title="project.name"
      :subtitle="project.description"
      :eyebrow="t('console.nav.overview')"
    >
      <template #meta>
        <p class="mt-2 font-mono text-[11.5px] text-[var(--console-text-muted)]">
          {{ t('console.overview.updated') }} · {{ updatedLabel }}
        </p>
      </template>

      <template #actions>
        <ElButton
          size="small"
          :disabled="!apiClientAvailable"
          :title="apiClientAvailable ? undefined : t('console.nav.notBuiltYet')"
          @click="go('console-project-api', apiClientAvailable)"
        >
          <ElIcon class="mr-1.5"><Promotion /></ElIcon>
          {{ t('console.overview.openApiClient') }}
        </ElButton>

        <ElButton
          size="small"
          type="primary"
          :disabled="!testLabAvailable"
          :title="testLabAvailable ? undefined : t('console.nav.notBuiltYet')"
          @click="go('console-project-ai-test', testLabAvailable)"
        >
          <ElIcon class="mr-1.5"><MagicStick /></ElIcon>
          {{ t('console.overview.openTestLab') }}
        </ElButton>
      </template>
    </ConsolePageHeader>

    <!-- Environments -->
    <section class="console-panel mb-4">
      <header class="border-b border-[var(--console-border)] px-4 py-3">
        <span class="console-label">{{ t('console.overview.environments') }}</span>
      </header>

      <ElTable :data="environments" size="small" class="console-table">
        <ElTableColumn :label="t('console.project.switcherLabel')" min-width="140">
          <template #default="{ row }">
            <span class="text-[12.5px] text-[var(--console-text)]">
              {{ row.name }}
            </span>
          </template>
        </ElTableColumn>

        <ElTableColumn :label="t('console.environment.label')" min-width="140">
          <template #default="{ row }">
            <ElTag
              size="small"
              effect="plain"
              :style="{
                color: kindColor(row.kind),
                borderColor: `color-mix(in srgb, ${kindColor(row.kind)} 34%, transparent)`,
              }"
            >
              {{ kindLabel(row.kind) }}
            </ElTag>
          </template>
        </ElTableColumn>

        <ElTableColumn :label="t('console.environment.baseUrl')" min-width="260">
          <template #default="{ row }">
            <span class="font-mono text-[12px] text-[var(--console-text-dim)]">
              {{ row.baseUrl }}
            </span>
          </template>
        </ElTableColumn>

        <ElTableColumn
          :label="t('console.environment.variables')"
          width="120"
          align="right"
        >
          <template #default="{ row }">
            <span class="font-mono text-[12px] text-[var(--console-text-muted)]">
              {{ row.variables.length }}
            </span>
          </template>
        </ElTableColumn>
      </ElTable>
    </section>

    <!-- Specification + next step -->
    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section class="console-panel p-4">
        <p class="console-label mb-2.5">{{ t('console.overview.spec') }}</p>
        <p class="font-mono text-[12.5px] text-[var(--console-text)]">
          {{ project.specName ?? t('console.overview.noSpec') }}
        </p>
      </section>

      <section class="console-panel p-4">
        <p class="console-label mb-2.5">{{ t('console.overview.quickStart') }}</p>
        <p class="text-[12.5px] leading-relaxed text-[var(--console-text-dim)]">
          {{ t('console.overview.quickStartBody') }}
        </p>
      </section>
    </div>
  </div>
</template>
