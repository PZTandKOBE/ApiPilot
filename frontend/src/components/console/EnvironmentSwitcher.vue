<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue'
import { ElDropdown, ElDropdownItem, ElDropdownMenu, ElIcon } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { useProjectStore } from '@/stores/project'
import type { EnvironmentKind } from '@/types/project'

/**
 * Environment picker.
 *
 * The kind drives the dot colour, which is the one place the console uses a
 * status colour decoratively: a production environment selected by accident is
 * the most expensive mistake this tool can cause, so it has to be visible at a
 * glance without reading the label.
 */
const { t } = useI18n()
const store = useProjectStore()

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

const active = computed(() => store.activeEnvironment)
const hasEnvironments = computed(() => store.environments.length > 0)

const onCommand = (command: unknown): void => {
  if (typeof command !== 'string') return
  store.selectEnvironment(command)
}
</script>

<template>
  <ElDropdown
    trigger="click"
    placement="bottom-start"
    :disabled="!hasEnvironments"
    @command="onCommand"
  >
    <button
      type="button"
      class="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--console-border)] bg-transparent px-2 py-1.5 text-[12px] text-[var(--console-text-dim)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)] disabled:cursor-not-allowed"
      :disabled="!hasEnvironments"
    >
      <span
        class="size-1.5 shrink-0 rounded-full"
        :style="{
          backgroundColor: active ? KIND_COLOR[active.kind] : 'var(--console-text-muted)',
        }"
      />
      <span class="max-w-[120px] truncate">
        {{ active ? t(KIND_LABEL_KEY[active.kind]) : t('console.environment.empty') }}
      </span>
      <ElIcon :size="12" class="text-[var(--console-text-muted)]">
        <ArrowDown />
      </ElIcon>
    </button>

    <template #dropdown>
      <ElDropdownMenu class="min-w-[240px]">
        <ElDropdownItem
          v-for="environment in store.environments"
          :key="environment.id"
          :command="environment.id"
        >
          <span class="flex w-full flex-col gap-0.5">
            <span class="flex items-center gap-2">
              <span
                class="size-1.5 shrink-0 rounded-full"
                :style="{ backgroundColor: KIND_COLOR[environment.kind] }"
              />
              <span
                :class="
                  environment.id === store.activeEnvironmentId
                    ? 'text-[var(--accent-soft)]'
                    : ''
                "
              >
                {{ t(KIND_LABEL_KEY[environment.kind]) }}
              </span>
            </span>
            <span
              class="truncate pl-3.5 font-mono text-[11px] text-[var(--console-text-muted)]"
            >
              {{ environment.baseUrl }}
            </span>
          </span>
        </ElDropdownItem>
      </ElDropdownMenu>
    </template>
  </ElDropdown>
</template>
