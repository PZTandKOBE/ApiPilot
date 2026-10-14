<script setup lang="ts">
import { Warning } from '@element-plus/icons-vue'
import { ElButton, ElIcon, ElInput, ElOption, ElSelect } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import { API_BODY_MODES, type ApiBodyMode } from '@/types/api'
import { formatJson, parseJson } from '@/utils/json'

/**
 * Request body tab.
 *
 * The body is held as text, never as a parsed object: a half-typed JSON
 * document is the normal case while composing, and round-tripping it through
 * `JSON.parse` would either lose it or force it into a shape the user did not
 * write.
 *
 * Invalid JSON is reported inline and does not block anything. It is the
 * *mock server* that answers 400 for a malformed body — which is the honest
 * behaviour, and lets the user see how the API reacts to bad input.
 *
 * The textarea is sized by the tab pane, not by a row count: it *is* the body
 * of this tab, so a fixed number of rows would leave the rest of the pane
 * empty. For the same reason its resize handle is off — the layout already
 * hands it every pixel it can have, and a manual drag would only fight it.
 */
const { t } = useI18n()
const store = useApiClientStore()

const body = computed(() => store.draft.body)

const validation = computed(() => {
  if (body.value.mode !== 'json') return null

  const text = body.value.text
  if (text.trim() === '') return null

  const outcome = parseJson(text)
  return outcome.ok ? null : outcome
})

const errorMessage = computed(() => {
  const outcome = validation.value
  if (outcome === null || outcome.ok) return ''

  return outcome.line === null
    ? t('console.apiClient.body.invalid')
    : t('console.apiClient.body.invalidAtLine', { line: outcome.line })
})

const setMode = (value: string): void => {
  if ((API_BODY_MODES as readonly string[]).includes(value)) {
    store.setBody({ ...body.value, mode: value as ApiBodyMode })
  }
}

const setText = (value: string): void => {
  store.setBody({ ...body.value, text: value })
}

const onFormat = (): void => {
  if (validation.value !== null) return
  setText(formatJson(body.value.text))
}
</script>

<template>
  <!-- No `min-h-0`: on a pane too short to hold the toolbar and a usable
       textarea, this keeps its content height and the tab region scrolls. -->
  <div class="flex flex-1 flex-col gap-2.5">
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-3">
      <label class="flex items-center gap-2">
        <span class="console-label">{{ t('console.apiClient.body.mode') }}</span>
        <ElSelect
          :model-value="body.mode"
          class="w-[140px]"
          size="small"
          @update:model-value="setMode"
        >
          <ElOption
            v-for="mode in API_BODY_MODES"
            :key="mode"
            :label="
              mode === 'none'
                ? t('console.apiClient.body.none')
                : mode === 'json'
                  ? t('console.apiClient.body.json')
                  : t('console.apiClient.body.raw')
            "
            :value="mode"
          />
        </ElSelect>
      </label>

      <ElButton
        v-if="body.mode === 'json'"
        size="small"
        :disabled="validation !== null || body.text.trim() === ''"
        @click="onFormat"
      >
        {{ t('console.apiClient.body.format') }}
      </ElButton>
    </div>

    <p
      v-if="body.mode === 'none'"
      class="text-[12px] text-[var(--console-text-muted)]"
    >
      {{ t('console.apiClient.body.noneHint') }}
    </p>

    <template v-else>
      <ElInput
        :model-value="body.text"
        type="textarea"
        resize="none"
        class="console-code-input console-code-input--fill"
        :placeholder="
          body.mode === 'json'
            ? t('console.apiClient.body.jsonPlaceholder')
            : t('console.apiClient.body.rawPlaceholder')
        "
        :aria-label="t('console.apiClient.tabs.body')"
        @update:model-value="setText"
      />

      <p
        v-if="validation !== null"
        class="flex shrink-0 items-center gap-1.5 text-[11.5px] text-[var(--status-fail)]"
        role="alert"
      >
        <ElIcon :size="13"><Warning /></ElIcon>
        {{ errorMessage }}
      </p>
    </template>
  </div>
</template>
