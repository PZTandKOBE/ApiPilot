<script setup lang="ts">
import { ElButton, ElDialog } from 'element-plus'

import GithubIcon from '@/components/common/GithubIcon.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import type { AuthProvider } from '@/types/user'

/**
 * Sign-in surface.
 *
 * There is no auth server yet, so the providers are presentational and
 * `auth.signIn` resolves a fixture — but the dialog already handles the parts
 * that will matter later: a pending state, a failure message slot, and a
 * provider-aware call signature.
 */
const visible = defineModel<boolean>({ required: true })

const { t } = useI18n()
const auth = useAuthStore()

const PROVIDERS: readonly { value: AuthProvider; labelKey: string }[] = [
  { value: 'github', labelKey: 'console.auth.github' },
  { value: 'google', labelKey: 'console.auth.google' },
]

const onSignIn = async (provider: AuthProvider): Promise<void> => {
  await auth.signIn(provider)
  if (auth.isAuthenticated) visible.value = false
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('console.auth.title')"
    width="400px"
    align-center
    class="console-dialog"
  >
    <p class="text-[13px] leading-relaxed text-[var(--console-text-dim)]">
      {{ t('console.auth.body') }}
    </p>

    <div class="mt-5 flex flex-col gap-2">
      <ElButton
        v-for="provider in PROVIDERS"
        :key="provider.value"
        :loading="auth.signingIn"
        class="!h-9 !w-full !justify-center"
        @click="onSignIn(provider.value)"
      >
        <GithubIcon v-if="provider.value === 'github'" :size="15" class="mr-2" />
        {{
          t('console.auth.continueWith', {
            provider: t(provider.labelKey),
          })
        }}
      </ElButton>
    </div>

    <p class="mt-4 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
      {{ t('console.auth.demoNote') }}
    </p>

    <template #footer>
      <ElButton text @click="visible = false">
        {{ t('console.auth.cancel') }}
      </ElButton>
    </template>
  </ElDialog>
</template>
