import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  fetchPublicAuthConfig,
  type DeploymentMode,
  type PublicAuthProvider,
} from '@/services/appConfig'
import {
  fetchCurrentUser,
  loginUrl,
  logoutAccount,
  safeNextPath,
} from '@/services/authApi'
import { ensureSession } from '@/services/session'
import type { AuthProvider, User } from '@/types/user'

const GUEST_INITIALS = '--'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const mode = ref<DeploymentMode>('self_hosted')
  const providers = ref<readonly PublicAuthProvider[]>([])
  const loginRequired = ref(false)
  const guestEnabled = ref(false)
  const initialized = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const signingIn = ref(false)
  const signingOut = ref(false)
  const startingGuest = ref(false)
  const signInError = ref<string | null>(null)
  const guestError = ref<string | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const isGuest = computed(() => user.value === null)
  const isOfficialCloud = computed(() => mode.value === 'official_cloud')
  const isLoginAvailable = computed(
    () =>
      mode.value === 'official_cloud' &&
      providers.value.some((provider) => provider.configured),
  )

  const initials = computed(() => {
    const name = user.value?.name
    if (!name) return GUEST_INITIALS
    const parts = name.split(/\s+/).filter((part) => part.length > 0).slice(0, 2)
    if (parts.length === 0) return GUEST_INITIALS
    return parts.map((part) => part.charAt(0).toUpperCase()).join('')
  })

  const providerConfigured = (provider: 'github' | 'google'): boolean =>
    providers.value.some((item) => item.id === provider && item.configured)

  const initialize = async (force = false): Promise<void> => {
    if (initialized.value && !force) return
    loading.value = true
    error.value = null
    try {
      const config = await fetchPublicAuthConfig()
      mode.value = config.deploymentMode
      providers.value = config.providers
      loginRequired.value = config.loginRequired
      guestEnabled.value = config.guestEnabled
      user.value =
        config.deploymentMode === 'official_cloud'
          ? await fetchCurrentUser()
          : null
      initialized.value = true
    } catch {
      error.value = 'auth.errors.unavailable'
      initialized.value = true
    } finally {
      loading.value = false
    }
  }

  const signIn = async (
    provider: AuthProvider,
    next = '/console',
  ): Promise<void> => {
    if (mode.value !== 'official_cloud') {
      signInError.value = 'auth.errors.authDisabled'
      return
    }
    if (provider !== 'github' && provider !== 'google') {
      signInError.value = 'auth.errors.providerUnavailable'
      return
    }
    if (!providerConfigured(provider)) {
      signInError.value = 'auth.errors.providerUnavailable'
      return
    }
    signingIn.value = true
    signInError.value = null
    try {
      window.location.assign(loginUrl(provider, safeNextPath(next)))
    } catch {
      signInError.value = 'auth.errors.unavailable'
      signingIn.value = false
    }
  }

  const continueAsGuest = async (): Promise<boolean> => {
    if (mode.value !== 'official_cloud' || !guestEnabled.value) {
      guestError.value = 'auth.errors.guestDisabled'
      return false
    }
    startingGuest.value = true
    guestError.value = null
    try {
      await ensureSession()
      user.value = null
      return true
    } catch {
      guestError.value = 'auth.errors.guestStartFailed'
      return false
    } finally {
      startingGuest.value = false
    }
  }

  const signOut = async (): Promise<void> => {
    signingOut.value = true
    error.value = null
    try {
      await logoutAccount()
      user.value = null
    } catch {
      error.value = 'auth.errors.logoutFailed'
    } finally {
      signingOut.value = false
    }
  }

  return {
    user,
    mode,
    providers,
    loginRequired,
    guestEnabled,
    initialized,
    loading,
    error,
    signingIn,
    signingOut,
    startingGuest,
    signInError,
    guestError,
    isAuthenticated,
    isGuest,
    isOfficialCloud,
    isLoginAvailable,
    initials,
    providerConfigured,
    initialize,
    signIn,
    continueAsGuest,
    signOut,
  }
})
