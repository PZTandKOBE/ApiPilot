<script setup lang="ts">
import { User as UserIcon } from '@element-plus/icons-vue'
import { ElButton, ElDialog, ElIcon } from 'element-plus'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import GithubIcon from '@/components/common/GithubIcon.vue'
import GoogleIcon from '@/components/common/GoogleIcon.vue'
import { useI18n } from '@/i18n'
import { safeNextPath } from '@/services/authApi'
import { useAuthStore } from '@/stores/auth'

const visible = defineModel<boolean>({ required: true })
const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const currentNext = computed(() => {
  const value = route.fullPath === '/login' ? route.query.next : route.fullPath
  return safeNextPath(value)
})
const errorMessage = computed(() => {
  const key = auth.guestError ?? auth.signInError
  return key === null ? null : t(key)
})

const onSignIn = (provider: 'github' | 'google'): void => {
  void auth.signIn(provider, currentNext.value)
}

const onGuest = async (): Promise<void> => {
  const started = await auth.continueAsGuest()
  if (!started) return
  visible.value = false
  void router.push(currentNext.value)
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="t('auth.title')"
    width="420px"
    align-center
    class="console-dialog signin-dialog"
  >
    <template v-if="auth.isOfficialCloud">
      <p class="text-[13px] leading-relaxed text-[var(--console-text-dim)]">
        {{ t('auth.subtitle') }}
      </p>
      <p class="mt-2 text-[11.5px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('auth.firstTime') }}
      </p>

      <p
        v-if="errorMessage !== null"
        class="mt-4 rounded-md border border-[var(--console-border-strong)] bg-[var(--console-surface-hover)] p-2 text-[12px] text-[var(--status-fail)]"
        role="alert"
      >
        {{ errorMessage }}
      </p>

      <div class="signin-actions mt-5 flex flex-col gap-2.5">
        <ElButton
          v-for="provider in auth.providers"
          :key="provider.id"
          :disabled="!provider.configured || auth.signingIn"
          class="signin-provider"
          :title="provider.configured ? undefined : t('auth.providerUnavailable')"
          @click="onSignIn(provider.id)"
        >
          <GithubIcon v-if="provider.id === 'github'" :size="16" />
          <GoogleIcon v-else :size="16" />
          <span class="signin-provider-label">
            {{
              provider.id === 'github'
                ? t('auth.continueWithGithub')
                : t('auth.continueWithGoogle')
            }}
          </span>
          <span
            v-if="!provider.configured"
            class="signin-provider-state"
          >
            {{ t('auth.providerUnavailable') }}
          </span>
        </ElButton>
      </div>

      <p
        v-if="!auth.providers.some((provider) => provider.configured)"
        class="mt-4 text-[11.5px] text-[var(--status-fail)]"
      >
        {{ t('auth.noProviders') }}
      </p>

      <div
        v-if="auth.guestEnabled"
        class="mt-4 border-t border-[var(--console-border)] pt-4"
      >
        <p class="mb-2 text-center text-[11px] uppercase tracking-[0.16em] text-[var(--console-text-muted)]">
          {{ t('auth.or') }}
        </p>
        <ElButton
          :loading="auth.startingGuest"
          class="signin-provider signin-provider-guest"
          @click="onGuest"
        >
          <ElIcon :size="16" class="signin-guest-icon">
            <UserIcon />
          </ElIcon>
          <span class="signin-provider-label">{{ t('auth.continueAsGuest') }}</span>
        </ElButton>
      </div>

      <p class="mt-4 text-[11px] leading-relaxed text-[var(--console-text-muted)]">
        {{ t('auth.privacyNote') }}
      </p>
    </template>

    <template v-else>
      <p class="text-[13px] leading-relaxed text-[var(--console-text-dim)]">
        {{ t('auth.selfHostedBody') }}
      </p>
      <p class="mt-3 text-[11.5px] leading-relaxed text-[var(--status-fail)]">
        {{ t('auth.errors.authDisabled') }}
      </p>
    </template>

    <template #footer>
      <ElButton text @click="visible = false">
        {{ t('auth.backHome') }}
      </ElButton>
    </template>
  </ElDialog>
</template>
