<script setup lang="ts">
import { MagicStick, Refresh } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { SpecFormat, SpecSource } from '@/types/agent'

/**
 * What the lab is currently holding.
 *
 * Every number is read from the parsed specification, never from the
 * document's own `info` block and never hard-coded — the trustworthiness of
 * the count is the whole point of showing it.
 */
const emit = defineEmits<{ replace: [] }>()

const { t } = useI18n()
const store = useAgentStore()

const FORMAT_KEY: Readonly<Record<SpecFormat, string>> = {
  'openapi-3': 'console.aiTest.format.openapi3',
  'swagger-2': 'console.aiTest.format.swagger2',
}

const SOURCE_KEY: Readonly<Record<SpecSource, string>> = {
  demo: 'console.aiTest.spec.sourceDemo',
  upload: 'console.aiTest.spec.sourceUpload',
  paste: 'console.aiTest.spec.sourcePaste',
  handoff: 'console.aiTest.spec.sourceHandoff',
}

const spec = computed(() => store.currentSpec)

const facts = computed(() => {
  const current = spec.value
  if (current === null) return []

  const rows = [
    { label: t('console.aiTest.spec.version'), value: current.version },
    { label: t('console.aiTest.spec.format'), value: t(FORMAT_KEY[current.format]) },
    { label: t('console.aiTest.spec.source'), value: t(SOURCE_KEY[current.source]) },
  ]

  // A pasted document has no file behind it; an empty row would be noise.
  if (current.filename.trim() !== '') {
    rows.push({ label: t('console.aiTest.spec.filename'), value: current.filename })
  }

  return rows
})

const analyzing = computed(() => store.analyzing)
const hasUnderstanding = computed(() => store.understanding !== null)
</script>

<template>
  <section v-if="spec !== null" class="console-panel p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="console-label">{{ t('console.aiTest.spec.title') }}</p>
        <h2
          class="mt-1 truncate text-[15px] font-semibold text-[var(--console-text)]"
        >
          {{ spec.title }}
        </h2>
        <p class="mt-1 font-mono text-[11.5px] text-[var(--console-text-muted)]">
          {{ spec.endpointCount }} {{ t('console.aiTest.spec.endpoints') }}
        </p>
      </div>

      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <ElButton size="small" :disabled="analyzing" @click="emit('replace')">
          {{ t('console.aiTest.spec.replace') }}
        </ElButton>

        <ElButton
          size="small"
          type="primary"
          :loading="analyzing"
          @click="store.analyzeSpec()"
        >
          <ElIcon v-if="!analyzing" class="mr-1.5">
            <Refresh v-if="hasUnderstanding" />
            <MagicStick v-else />
          </ElIcon>
          {{
            hasUnderstanding
              ? t('console.aiTest.spec.reanalyze')
              : t('console.aiTest.spec.analyze')
          }}
        </ElButton>
      </div>
    </div>

    <dl class="mt-3.5 flex flex-wrap gap-x-6 gap-y-2 border-t border-[var(--console-border)] pt-3.5">
      <div v-for="fact in facts" :key="fact.label" class="flex min-w-0 flex-col gap-0.5">
        <dt class="console-label">{{ fact.label }}</dt>
        <dd class="truncate font-mono text-[12px] text-[var(--console-text-dim)]">
          {{ fact.value }}
        </dd>
      </div>
    </dl>
  </section>
</template>
