<script setup lang="ts">
import { EditPen, MagicStick, Plus, Promotion } from '@element-plus/icons-vue'
import {
  ElButton,
  ElIcon,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import EnvironmentCreateDialog from '@/components/console/EnvironmentCreateDialog.vue'
import EnvironmentEditDialog from '@/components/console/EnvironmentEditDialog.vue'
import ProjectEditDialog from '@/components/console/ProjectEditDialog.vue'
import ProjectSpecPanel from '@/components/console/ProjectSpecPanel.vue'
import { useI18n } from '@/i18n'
import { getProjectSpec } from '@/services/api/projects'
import { useProjectStore } from '@/stores/project'
import { formatDate } from '@/utils/time'
import type {
  EnvironmentKind,
  ProjectEnvironment,
  ProjectSpecSummary,
} from '@/types/project'

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

const projectEditOpen = ref(false)
const environmentCreateOpen = ref(false)
const environmentEditOpen = ref(false)
const editingEnvironment = ref<ProjectEnvironment | null>(null)

const spec = ref<ProjectSpecSummary | null>(null)
const specLoading = ref(false)
const specError = ref(false)
let specRequest = 0

const loadSpec = async (): Promise<void> => {
  const projectId = props.projectId
  const request = (specRequest += 1)

  spec.value = null
  specLoading.value = true
  specError.value = false

  try {
    const loaded = await getProjectSpec(projectId)

    if (request !== specRequest) return
    spec.value = loaded
  } catch {
    if (request !== specRequest) return

    spec.value = null
    specError.value = true
  } finally {
    if (request === specRequest) specLoading.value = false
  }
}

watch(
  () => props.projectId,
  () => {
    projectEditOpen.value = false
    environmentCreateOpen.value = false
    environmentEditOpen.value = false
    editingEnvironment.value = null

    void loadSpec()
  },
  { immediate: true },
)

const openProjectEdit = (): void => {
  if (project.value === null) return
  projectEditOpen.value = true
}

const openEnvironmentEdit = (row: unknown): void => {
  const environment = row as ProjectEnvironment
  editingEnvironment.value = environment
  environmentEditOpen.value = true
}

const KIND_COLOR: Readonly<Record<EnvironmentKind, string>> = {
  development: 'var(--accent)',
  testing: 'var(--status-pass)',
  staging: 'var(--status-warn)',
  production: 'var(--status-fail)',
}

const KIND_LABEL_KEY: Readonly<Record<EnvironmentKind, string>> = {
  development: 'console.environment.development',
  testing: 'console.environment.testing',
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

/** A destination is live only when its route is registered. */
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
        <ElButton size="small" @click="openProjectEdit">
          <ElIcon class="mr-1.5"><EditPen /></ElIcon>
          {{ t('console.overview.editProject') }}
        </ElButton>

        <ElButton
          size="small"
          :disabled="!apiClientAvailable"
          :title="apiClientAvailable ? undefined : t('console.nav.notBuiltYet')"
          @click="go('console-project-api', apiClientAvailable)"
        >
          <ElIcon class="mr-1.5"><Promotion /></ElIcon>
          {{ t('console.nav.apiClient') }}
        </ElButton>

        <ElButton
          size="small"
          type="primary"
          :disabled="!testLabAvailable"
          :title="testLabAvailable ? undefined : t('console.nav.notBuiltYet')"
          @click="go('console-project-ai-test', testLabAvailable)"
        >
          <ElIcon class="mr-1.5"><MagicStick /></ElIcon>
          {{ t('console.nav.aiTestLab') }}
        </ElButton>
      </template>
    </ConsolePageHeader>

    <!-- Environments -->
    <section class="console-panel mb-4">
      <header
        class="flex items-center justify-between gap-3 border-b border-[var(--console-border)] px-4 py-3"
      >
        <span class="console-label">{{ t('console.overview.environments') }}</span>
        <ElButton size="small" @click="environmentCreateOpen = true">
          <ElIcon class="mr-1.5"><Plus /></ElIcon>
          {{ t('console.overview.addEnvironment') }}
        </ElButton>
      </header>

      <ElTable :data="environments" size="small" class="console-table">
        <ElTableColumn :label="t('console.overview.environmentName')" min-width="140">
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

        <ElTableColumn
          :label="t('console.overview.actions')"
          width="90"
          align="right"
        >
          <template #default="{ row }">
            <ElButton link size="small" @click="openEnvironmentEdit(row)">
              {{ t('console.overview.edit') }}
            </ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </section>

    <!-- Specification + next step -->
    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <ProjectSpecPanel
        :spec="spec"
        :loading="specLoading"
        :error="specError"
        @retry="loadSpec"
        @open-test-lab="go('console-project-ai-test', testLabAvailable)"
      />

      <section class="console-panel p-4">
        <p class="console-label mb-2.5">{{ t('console.overview.quickStart') }}</p>
        <p class="text-[12.5px] leading-relaxed text-[var(--console-text-dim)]">
          {{ t('console.overview.quickStartBody') }}
        </p>
      </section>
    </div>

    <ProjectEditDialog
      v-if="project !== null"
      v-model="projectEditOpen"
      :project="project"
    />

    <EnvironmentEditDialog
      v-if="editingEnvironment !== null"
      v-model="environmentEditOpen"
      :project-id="projectId"
      :environment="editingEnvironment"
    />

    <EnvironmentCreateDialog
      v-model="environmentCreateOpen"
      :project-id="projectId"
    />
  </div>
</template>
