<script setup lang="ts">
import { MagicStick, Warning } from '@element-plus/icons-vue'
import {
  ElButton,
  ElIcon,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElTooltip,
} from 'element-plus'
import { computed, onBeforeUnmount, onMounted } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import { HTTP_METHODS, type HttpMethod } from '@/types/api'
import { methodColor } from '@/utils/http'

/**
 * Method + URL + Send.
 *
 * The one interaction that has to be perfect, so it carries the whole request
 * lifecycle: the send button becomes a cancel button while in flight, the bar
 * reports *why* it refuses to send when a variable is undefined, and
 * Cmd/Ctrl+Enter works from anywhere in the editor.
 */
const emit = defineEmits<{ save: [] }>()

const { t } = useI18n()
const store = useApiClientStore()

const method = computed(() => store.draft.method)
const blocked = computed(() => store.blockedReason)

/** Cancel is always available while sending; Send is gated on a resolvable request. */
const sendDisabled = computed(() => !store.sending && blocked.value !== null)

const blockedMessage = computed(() => {
  const reason = blocked.value
  if (reason === null) return ''

  return reason === 'unresolved-variables'
    ? t('console.apiClient.error.unresolvedVariables', {
        names: store.unresolvedVariables.join(', '),
      })
    : t('console.apiClient.error.missingBaseUrl')
})

const setMethod = (value: string): void => {
  if ((HTTP_METHODS as readonly string[]).includes(value)) {
    store.setMethod(value as HttpMethod)
  }
}

const onSend = async (): Promise<void> => {
  if (store.sending) {
    store.cancel()
    return
  }

  await store.send()
}

/**
 * Global rather than scoped to the URL field: the user is usually in the body
 * editor when they hit this, and a shortcut that only works in one focused
 * field would be a trap.
 */
const onKeydown = (event: KeyboardEvent): void => {
  if (event.key !== 'Enter') return
  if (!event.metaKey && !event.ctrlKey) return

  event.preventDefault()
  void onSend()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

const onGenerateTest = (): void => {
  if (store.requestAgentHandoff()) {
    ElMessage({ message: t('console.apiClient.agent.queued'), type: 'success' })
  }
}
</script>

<template>
  <div class="flex shrink-0 flex-col gap-2">
    <div class="flex flex-wrap items-stretch gap-2">
      <!-- Method -->
      <ElSelect
        :model-value="method"
        class="w-[118px] shrink-0"
        @update:model-value="setMethod"
      >
        <template #prefix>
          <span
            class="size-1.5 rounded-full"
            :style="{ backgroundColor: methodColor(method) }"
          />
        </template>

        <ElOption
          v-for="candidate in HTTP_METHODS"
          :key="candidate"
          :label="candidate"
          :value="candidate"
        >
          <span class="flex items-center gap-2 font-mono text-[12.5px]">
            <span
              class="size-1.5 rounded-full"
              :style="{ backgroundColor: methodColor(candidate) }"
            />
            {{ candidate }}
          </span>
        </ElOption>
      </ElSelect>

      <!-- URL -->
      <ElInput
        :model-value="store.draft.url"
        class="console-code-input min-w-[220px] flex-1"
        :placeholder="t('console.apiClient.urlPlaceholder')"
        :aria-label="t('console.apiClient.request')"
        spellcheck="false"
        @update:model-value="store.setUrl($event)"
      />

      <!-- Save -->
      <ElButton class="shrink-0" @click="emit('save')">
        {{ t('console.apiClient.save') }}
      </ElButton>

      <!-- Agent entry point -->
      <ElTooltip
        :content="t('console.apiClient.agent.generateHint')"
        placement="bottom"
        :show-after="300"
      >
        <ElButton
          class="shrink-0"
          :disabled="sendDisabled"
          :aria-label="t('console.apiClient.agent.generate')"
          @click="onGenerateTest"
        >
          <ElIcon><MagicStick /></ElIcon>
        </ElButton>
      </ElTooltip>

      <!-- Send / Cancel -->
      <ElButton
        class="w-[104px] shrink-0"
        :type="store.sending ? 'default' : 'primary'"
        :disabled="sendDisabled"
        :loading="store.sending"
        @click="onSend"
      >
        {{
          store.sending
            ? t('console.apiClient.cancelRequest')
            : t('console.apiClient.send')
        }}
      </ElButton>
    </div>

    <!-- Why the request cannot be sent -->
    <p
      v-if="blocked !== null"
      class="flex items-center gap-1.5 text-[11.5px] text-[var(--status-warn)]"
      role="status"
    >
      <ElIcon :size="13"><Warning /></ElIcon>
      {{ blockedMessage }}
    </p>
  </div>
</template>
