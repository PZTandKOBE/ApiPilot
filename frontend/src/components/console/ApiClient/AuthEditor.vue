<script setup lang="ts">
import { ElInput, ElOption, ElSelect } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import {
  API_AUTH_TYPES,
  API_KEY_LOCATIONS,
  type ApiAuthType,
  type ApiHeaderPair,
  type ApiKeyLocation,
} from '@/types/api'
import { describeAuthContribution } from '@/utils/apiRequest'

/**
 * Authentication tab.
 *
 * The configuration is a form, and the preview below it is the point: auth is
 * the one part of a request whose wire format users habitually get wrong, so
 * the panel shows exactly what will be attached before anything is sent.
 *
 * The preview runs through the same `describeAuthContribution` that builds the
 * real request — placeholders included, since they are resolved later — so the
 * preview cannot disagree with what is actually sent.
 */
const { t } = useI18n()
const store = useApiClientStore()

const auth = computed(() => store.draft.auth)

const TYPE_LABEL_KEY: Readonly<Record<ApiAuthType, string>> = {
  none: 'console.apiClient.auth.none',
  bearer: 'console.apiClient.auth.bearer',
  basic: 'console.apiClient.auth.basic',
  apiKey: 'console.apiClient.auth.apiKey',
}

const LOCATION_LABEL_KEY: Readonly<Record<ApiKeyLocation, string>> = {
  header: 'console.apiClient.auth.inHeader',
  query: 'console.apiClient.auth.inQuery',
}

const contribution = computed(() => describeAuthContribution(auth.value))

const previewPairs = computed<readonly ApiHeaderPair[]>(() => [
  ...contribution.value.headers,
  ...contribution.value.query,
])

const previewEmpty = computed(() => previewPairs.value.length === 0)

/**
 * Element Plus types `v-model` on a select as the option's value type, but the
 * bound value here is a string union — narrowing at the edge keeps the store's
 * action signature honest.
 */
const setType = (value: string): void => {
  if ((API_AUTH_TYPES as readonly string[]).includes(value)) {
    store.patchAuth({ type: value as ApiAuthType })
  }
}

const setLocation = (value: string): void => {
  if ((API_KEY_LOCATIONS as readonly string[]).includes(value)) {
    store.patchAuth({ apiKeyIn: value as ApiKeyLocation })
  }
}
</script>

<template>
  <div class="flex max-w-2xl flex-col gap-3">
    <label class="flex flex-col gap-1.5">
      <span class="console-label">{{ t('console.apiClient.auth.type') }}</span>
      <ElSelect
        :model-value="auth.type"
        class="w-full max-w-[240px]"
        @update:model-value="setType"
      >
        <ElOption
          v-for="type in API_AUTH_TYPES"
          :key="type"
          :label="t(TYPE_LABEL_KEY[type])"
          :value="type"
        />
      </ElSelect>
    </label>

    <p
      v-if="auth.type === 'none'"
      class="text-[12px] text-[var(--console-text-muted)]"
    >
      {{ t('console.apiClient.auth.noneHint') }}
    </p>

    <label v-else-if="auth.type === 'bearer'" class="flex flex-col gap-1.5">
      <span class="console-label">{{ t('console.apiClient.auth.bearerToken') }}</span>
      <ElInput
        :model-value="auth.bearerToken"
        class="console-kv-input max-w-[420px]"
        :placeholder="t('console.apiClient.auth.bearerPlaceholder')"
        @update:model-value="store.patchAuth({ bearerToken: $event })"
      />
    </label>

    <template v-else-if="auth.type === 'basic'">
      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.apiClient.auth.username') }}</span>
        <ElInput
          :model-value="auth.username"
          class="console-kv-input max-w-[420px]"
          @update:model-value="store.patchAuth({ username: $event })"
        />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="console-label">{{ t('console.apiClient.auth.password') }}</span>
        <ElInput
          :model-value="auth.password"
          type="password"
          show-password
          class="console-kv-input max-w-[420px]"
          @update:model-value="store.patchAuth({ password: $event })"
        />
      </label>
    </template>

    <template v-else>
      <div class="flex flex-wrap gap-3">
        <label class="flex min-w-[180px] flex-1 flex-col gap-1.5">
          <span class="console-label">{{ t('console.apiClient.auth.apiKeyName') }}</span>
          <ElInput
            :model-value="auth.apiKeyName"
            class="console-kv-input"
            placeholder="X-API-Key"
            @update:model-value="store.patchAuth({ apiKeyName: $event })"
          />
        </label>

        <label class="flex min-w-[180px] flex-1 flex-col gap-1.5">
          <span class="console-label">{{ t('console.apiClient.auth.apiKeyValue') }}</span>
          <ElInput
            :model-value="auth.apiKeyValue"
            class="console-kv-input"
            placeholder="{{api_key}}"
            @update:model-value="store.patchAuth({ apiKeyValue: $event })"
          />
        </label>

        <label class="flex min-w-[140px] flex-col gap-1.5">
          <span class="console-label">{{ t('console.apiClient.auth.apiKeyIn') }}</span>
          <ElSelect
            :model-value="auth.apiKeyIn"
            @update:model-value="setLocation"
          >
            <ElOption
              v-for="location in API_KEY_LOCATIONS"
              :key="location"
              :label="t(LOCATION_LABEL_KEY[location])"
              :value="location"
            />
          </ElSelect>
        </label>
      </div>
    </template>

    <!-- Preview -->
    <div class="mt-1 rounded-lg border border-[var(--console-border)] bg-black/25 p-3">
      <p class="console-label mb-2">{{ t('console.apiClient.auth.preview') }}</p>

      <p
        v-if="previewEmpty"
        class="text-[12px] text-[var(--console-text-muted)]"
      >
        {{ t('console.apiClient.auth.previewEmpty') }}
      </p>

      <dl v-else class="flex flex-col gap-1">
        <div
          v-for="pair in previewPairs"
          :key="`${pair.name}-${pair.value}`"
          class="flex items-baseline gap-2 font-mono text-[12px]"
        >
          <dt class="shrink-0 text-[var(--console-text-muted)]">{{ pair.name }}:</dt>
          <dd class="min-w-0 truncate text-[var(--accent-soft)]">{{ pair.value }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>
