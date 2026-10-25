<script setup lang="ts">
import {
  ElButton,
  ElDialog,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
} from 'element-plus'
import { computed, ref, watch } from 'vue'

import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import type { EnvironmentKind, ProjectEnvironment } from '@/types/project'
import { isHttpUrl } from '@/utils/url'

/**
 * Edit the basic, non-secret fields of one environment.
 *
 * Variables and auth rules are not in this form and are not part of the update
 * payload.  A failed save leaves the draft in place so the user can correct it
 * without retyping the whole row.
 */
const visible = defineModel<boolean>({ required: true })

const props = defineProps<{
  projectId: string
  environment: ProjectEnvironment
}>()

const { t } = useI18n()
const store = useProjectStore()

const ENVIRONMENT_NAME_MAX = 100
const BASE_URL_MAX = 1000

const name = ref(props.environment.name)
const kind = ref<EnvironmentKind>(props.environment.kind)
const baseUrl = ref(props.environment.baseUrl)
const touched = ref(false)
const failed = ref(false)

const KIND_LABEL_KEY: Readonly<Record<EnvironmentKind, string>> = {
  development: 'console.environment.development',
  testing: 'console.environment.testing',
  staging: 'console.environment.staging',
  production: 'console.environment.production',
}

const kindOptions = computed(() =>
  (Object.keys(KIND_LABEL_KEY) as EnvironmentKind[]).map((value) => ({
    value,
    label: t(KIND_LABEL_KEY[value]),
  })),
)

const trimmedName = computed(() => name.value.trim())
const trimmedBaseUrl = computed(() => baseUrl.value.trim())
const nameValid = computed(
  () =>
    trimmedName.value !== '' && trimmedName.value.length <= ENVIRONMENT_NAME_MAX,
)
const baseUrlValid = computed(
  () =>
    trimmedBaseUrl.value !== '' &&
    trimmedBaseUrl.value.length <= BASE_URL_MAX &&
    isHttpUrl(trimmedBaseUrl.value),
)
const duplicateName = computed(
  () =>
    store
      .projectById(props.projectId)
      ?.environments.some(
        (environment) =>
          environment.id !== props.environment.id &&
          environment.name.trim() === trimmedName.value,
      ) ?? false,
)
const unchanged = computed(
  () =>
    trimmedName.value === props.environment.name.trim() &&
    kind.value === props.environment.kind &&
    trimmedBaseUrl.value === props.environment.baseUrl.trim(),
)
const canSubmit = computed(
  () =>
    nameValid.value &&
    !duplicateName.value &&
    baseUrlValid.value &&
    !unchanged.value &&
    !store.updating,
)

const reset = (): void => {
  name.value = props.environment.name
  kind.value = props.environment.kind
  baseUrl.value = props.environment.baseUrl
  touched.value = false
  failed.value = false
}

watch(visible, (open) => {
  if (open) reset()
})

watch(
  () => props.environment.id,
  () => {
    if (visible.value) reset()
  },
)

watch([name, kind, baseUrl], () => {
  failed.value = false
})

const save = async (): Promise<void> => {
  touched.value = true
  if (!canSubmit.value) return

  const updated = await store.updateEnvironment(props.projectId, props.environment.id, {
    name: trimmedName.value,
    kind: kind.value,
    baseUrl: trimmedBaseUrl.value,
  })

  if (updated === null) {
    failed.value = true
    return
  }

  visible.value = false
  ElMessage.success(t('console.overview.environmentSaved'))
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.overview.editEnvironment')"
    width="460px"
    align-center
    class="console-dialog"
    :close-on-click-modal="!store.updating"
    :close-on-press-escape="!store.updating"
  >
    <div class="flex flex-col gap-4">
      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.overview.environmentName') }}</span>
        <ElInput
          v-model="name"
          :maxlength="ENVIRONMENT_NAME_MAX"
          :disabled="store.updating"
        />
        <span
          v-if="touched && !nameValid"
          class="text-[11px] leading-relaxed text-[var(--status-fail)]"
        >
          {{ t('console.overview.invalidName') }}
        </span>
        <span
          v-else-if="touched && duplicateName"
          class="text-[11px] leading-relaxed text-[var(--status-fail)]"
        >
          {{ t('console.overview.environmentNameConflict') }}
        </span>
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.environment.label') }}</span>
        <ElSelect v-model="kind" class="w-full" :disabled="store.updating">
          <ElOption
            v-for="option in kindOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </ElSelect>
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.environment.baseUrl') }}</span>
        <ElInput
          v-model="baseUrl"
          :maxlength="BASE_URL_MAX"
          :placeholder="t('console.project.baseUrlPlaceholder')"
          :disabled="store.updating"
        />
        <span class="text-[11px] leading-relaxed text-[var(--console-text-muted)]">
          {{ t('console.overview.baseUrlHint') }}
        </span>
        <span
          v-if="touched && !baseUrlValid"
          class="text-[11px] leading-relaxed text-[var(--status-fail)]"
        >
          {{ t('console.overview.invalidBaseUrl') }}
        </span>
      </label>

      <p
        v-if="failed"
        class="text-[12px] leading-relaxed text-[var(--status-fail)]"
        role="alert"
      >
        {{ t('console.overview.saveFailed') }}
      </p>
    </div>

    <template #footer>
      <ElButton text :disabled="store.updating" @click="visible = false">
        {{ t('console.common.cancel') }}
      </ElButton>
      <ElButton
        type="primary"
        :disabled="store.updating"
        :loading="store.updating"
        @click="save"
      >
        {{ t('console.common.save') }}
      </ElButton>
    </template>
  </ElDialog>
</template>
