<script setup lang="ts">
import { ElButton } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { ProjectSpecSummary } from '@/types/project'
import { formatDate } from '@/utils/time'

/**
 * The project's real spec summary.
 *
 * This is a presentational leaf: the page owns the request and the retry,
 * while every state is explicit here.  The panel uses the project spec endpoint
 * so "not uploaded yet" is only shown after a successful null answer.
 */
const props = defineProps<{
  spec: ProjectSpecSummary | null
  loading: boolean
  error: boolean
}>()

const emit = defineEmits<{
  readonly retry: []
  readonly openTestLab: []
}>()

const { t, locale } = useI18n()

const SPEC_TYPE_LABEL: Readonly<Record<string, string>> = {
  'openapi-3': 'console.overview.specOpenapi3',
  'swagger-2': 'console.overview.specSwagger2',
}

const typeLabel = computed(() => {
  const specType = props.spec?.specType
  if (specType === undefined) return ''

  const key = SPEC_TYPE_LABEL[specType]
  return key === undefined ? t('console.overview.specUnknown') : t(key)
})

const formatLabel = computed(() => {
  const contentFormat = props.spec?.contentFormat.toUpperCase() ?? ''

  return contentFormat === ''
    ? typeLabel.value
    : typeLabel.value + ' · ' + contentFormat
})
</script>

<template>
  <section class="console-panel p-4" aria-labelledby="project-spec-title">
    <p id="project-spec-title" class="console-label mb-2.5">
      {{ t('console.overview.spec') }}
    </p>

    <div v-if="loading" class="py-2" role="status" :aria-label="t('console.common.loading')">
      <div class="h-4 w-32 animate-pulse rounded bg-white/[0.04]" />
      <div class="mt-2 h-3 w-48 animate-pulse rounded bg-white/[0.03]" />
    </div>

    <div v-else-if="error" class="py-2" role="alert">
      <p class="text-[12px] font-medium text-[var(--status-fail)]">
        {{ t('console.overview.specLoadFailed') }}
      </p>
      <p class="mt-1 text-[11.5px] leading-relaxed text-[var(--console-text-dim)]">
        {{ t('console.overview.specLoadFailedBody') }}
      </p>
      <ElButton class="mt-2" size="small" @click="emit('retry')">
        {{ t('console.common.retry') }}
      </ElButton>
    </div>

    <template v-else-if="spec">
      <p class="truncate text-[13px] font-medium text-[var(--console-text)]">
        {{ spec.name }}
      </p>
      <p
        v-if="spec.filename"
        class="mt-1 truncate font-mono text-[11px] text-[var(--console-text-dim)]"
      >
        {{ spec.filename }}
      </p>
      <p class="mt-1 font-mono text-[11px] text-[var(--console-text-dim)]">
        {{ formatLabel }}
      </p>

      <dl class="mt-4 grid grid-cols-2 gap-3">
        <div>
          <dt class="console-label">{{ t('console.overview.specEndpoints') }}</dt>
          <dd class="mt-1 font-mono text-[13px] text-[var(--console-text)]">
            {{ spec.endpointCount }}
          </dd>
        </div>
        <div>
          <dt class="console-label">{{ t('console.overview.specUpdated') }}</dt>
          <dd class="mt-1 text-[11.5px] text-[var(--console-text-dim)]">
            {{ formatDate(spec.updatedAt, locale) }}
          </dd>
        </div>
      </dl>
    </template>

    <div v-else class="py-1">
      <p class="text-[12.5px] text-[var(--console-text-dim)]">
        {{ t('console.overview.noSpec') }}
      </p>
      <ElButton class="mt-2" size="small" type="primary" @click="emit('openTestLab')">
        {{ t('console.nav.aiTestLab') }}
      </ElButton>
    </div>
  </section>
</template>
