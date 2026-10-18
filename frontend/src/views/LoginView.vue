<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import GithubIcon from '@/components/common/GithubIcon.vue'
import GoogleIcon from '@/components/common/GoogleIcon.vue'
import MarketingLayout from '@/layouts/MarketingLayout.vue'
import { useI18n } from '@/i18n'
import { safeNextPath } from '@/services/authApi'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

const nextPath = computed(() => safeNextPath(route.query.next))
const errorKey = computed(() => {
  const value = route.query.error
  if (typeof value !== 'string') return null
  const keys: Record<string, string> = {
    'provider-unavailable': 'auth.errors.providerUnavailable',
    'guest-sessions-disabled': 'auth.errors.guestSessionsDisabled',
    'forbidden-origin': 'auth.errors.forbiddenOrigin',
    'oauth-cancelled': 'auth.errors.oauthCancelled',
    'oauth-failed': 'auth.errors.oauthFailed',
    'state-invalid': 'auth.errors.stateInvalid',
    'oidc-invalid': 'auth.errors.oidcInvalid',
    'provider-profile-failed': 'auth.errors.providerProfileFailed',
    'account-unavailable': 'auth.errors.accountUnavailable',
    'auth-disabled': 'auth.errors.authDisabled',
  }
  return keys[value] ?? 'auth.errors.oauthFailed'
})

const errorMessage = computed<string | null>(() => {
  if (errorKey.value !== null) return t(errorKey.value)
  if (auth.error !== null) return t(auth.error)
  if (auth.signInError !== null) return t(auth.signInError)
  if (auth.guestError !== null) return t(auth.guestError)
  return null
})

const providerLabel = (provider: 'github' | 'google'): string =>
  provider === 'github'
    ? t('auth.continueWithGithub')
    : t('auth.continueWithGoogle')

const onSignIn = (provider: 'github' | 'google'): void => {
  void auth.signIn(provider, nextPath.value)
}

const continueToConsole = (): void => {
  void router.push(nextPath.value)
}

const onGuest = async (): Promise<void> => {
  const started = await auth.continueAsGuest()
  if (started) void router.push(nextPath.value)
}

const onLogout = async (): Promise<void> => {
  await auth.signOut()
  if (auth.user === null) {
    void router.replace({ name: 'login' })
  }
}

onMounted(() => {
  void auth.initialize()
})
</script>

<template>
  <MarketingLayout>
    <div class="login-page">
      <section class="login-card">
        <p class="login-kicker">ApiPilot · Learn Us / Try Us</p>

        <template v-if="auth.loading && !auth.initialized">
          <h1>{{ t('auth.title') }}</h1>
          <p class="login-muted">{{ t('auth.loading') }}</p>
        </template>

        <template v-else-if="auth.isOfficialCloud && auth.isAuthenticated">
          <p class="login-kicker">{{ t('auth.signedInAs') }}</p>
          <h1>{{ auth.user?.name }}</h1>
          <p class="login-muted">{{ auth.user?.email ?? t('auth.noEmail') }}</p>
          <div class="login-actions">
            <button type="button" class="login-provider login-provider-primary" @click="continueToConsole">
              {{ t('auth.continueToConsole') }}
            </button>
            <button type="button" class="login-text-button" :disabled="auth.signingOut" @click="onLogout">
              {{ auth.signingOut ? t('auth.loading') : t('auth.logout') }}
            </button>
          </div>
        </template>

        <template v-else-if="auth.isOfficialCloud">
          <h1>{{ t('auth.officialTitle') }}</h1>
          <p class="login-muted">{{ t('auth.subtitle') }}</p>
          <p class="login-note">{{ t('auth.firstTime') }}</p>

          <p v-if="errorMessage !== null" class="login-error" role="alert">
            {{ errorMessage }}
          </p>

          <div v-if="auth.providers.some((provider) => provider.configured)" class="login-actions">
            <button
              v-for="provider in auth.providers"
              :key="provider.id"
              type="button"
              class="login-provider"
              :disabled="!provider.configured || auth.signingIn"
              :title="provider.configured ? undefined : t('auth.providerUnavailable')"
              @click="onSignIn(provider.id)"
            >
              <GithubIcon v-if="provider.id === 'github'" :size="16" />
              <GoogleIcon v-else :size="16" />
              <span>{{ providerLabel(provider.id) }}</span>
              <span v-if="!provider.configured" class="login-provider-state">
                {{ t('auth.providerUnavailable') }}
              </span>
            </button>
          </div>

          <p v-else class="login-error" role="status">{{ t('auth.noProviders') }}</p>

          <div v-if="auth.guestEnabled" class="login-guest">
            <p class="login-guest-divider">{{ t('auth.or') }}</p>
            <button
              type="button"
              class="login-provider login-provider-primary"
              :disabled="auth.startingGuest"
              @click="onGuest"
            >
              {{ auth.startingGuest ? t('auth.loading') : t('auth.continueAsGuest') }}
            </button>
          </div>

          <p class="login-note">{{ t('auth.privacyNote') }}</p>
        </template>

        <template v-else>
          <h1>{{ t('auth.selfHostedTitle') }}</h1>
          <p class="login-muted">{{ t('auth.selfHostedBody') }}</p>
          <p v-if="errorMessage !== null" class="login-error" role="alert">{{ errorMessage }}</p>
          <div class="login-actions">
            <button type="button" class="login-provider login-provider-primary" @click="continueToConsole">
              {{ t('auth.continueToConsole') }}
            </button>
          </div>
          <p class="login-note">{{ t('auth.errors.authDisabled') }}</p>
        </template>

        <RouterLink to="/" class="login-back">{{ t('auth.backHome') }}</RouterLink>
      </section>
    </div>
  </MarketingLayout>
</template>
