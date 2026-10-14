<script setup lang="ts">
import { ElAlert, ElButton } from 'element-plus'

import { useI18n } from '@/i18n'
import type { RunError } from '@/services/run'

/**
 * A run-level failure, in the reader's language.
 *
 * The message is resolved from `messageKey` and never from `code`: the code is
 * a branch the store took, and showing it would hand the user a token to
 * search for instead of the reason their run stopped. Dismissal is the
 * parent's call — this component only reports that it was asked for, so the
 * store stays the one place that knows an error has been seen.
 */
defineProps<{ error: RunError }>()

const emit = defineEmits<{ dismiss: [] }>()

const { t } = useI18n()
</script>

<template>
  <ElAlert type="error" show-icon :closable="false">
    <template #title>{{ t('console.runs.errors.title') }}</template>

    <div class="flex flex-wrap items-start justify-between gap-3">
      <span class="text-[12px] leading-relaxed">
        {{ t(error.messageKey, error.params) }}
      </span>

      <ElButton text size="small" @click="emit('dismiss')">
        {{ t('console.runs.errors.dismiss') }}
      </ElButton>
    </div>
  </ElAlert>
</template>
