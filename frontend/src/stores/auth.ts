import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { usePersistedRef } from '@/composables/usePersistedRef'
import { MOCK_AUTH_LATENCY_MS, resolveMockUser } from '@/services/mock/user'
import { isUser, type AuthProvider, type User } from '@/types/user'

const STORAGE_KEY = 'aiata.console.user'

/** Character budget for the `--` placeholder; keeps layouts stable. */
const GUEST_INITIALS = '--'

/**
 * Session state.
 *
 * There is no auth server yet, so `signIn` resolves a fixture. What matters
 * for the architecture is that it is already asynchronous and provider-aware:
 * the components call `signIn(provider)` and await it, so swapping the body
 * for `POST /api/auth/session` changes nothing above this store.
 *
 * Guests are a first-class state, not an error state — the API Client and the
 * test lab are usable without an account, and gated actions are the only place
 * that should ever ask for one.
 */
export const useAuthStore = defineStore('auth', () => {
  const user = usePersistedRef<User | null>(STORAGE_KEY, null, {
    validate: (value): value is User | null => value === null || isUser(value),
  })

  const signingIn = ref(false)
  const signInError = ref<string | null>(null)

  const isAuthenticated = computed(() => user.value !== null)
  const isGuest = computed(() => user.value === null)

  /** Two-letter monogram for the avatar fallback. */
  const initials = computed(() => {
    const name = user.value?.name
    if (!name) return GUEST_INITIALS

    const parts = name
      .split(/\s+/)
      .filter((part) => part.length > 0)
      .slice(0, 2)

    if (parts.length === 0) return GUEST_INITIALS

    return parts.map((part) => part.charAt(0).toUpperCase()).join('')
  })

  const signIn = async (provider: AuthProvider): Promise<void> => {
    signingIn.value = true
    signInError.value = null

    try {
      await new Promise((resolve) => setTimeout(resolve, MOCK_AUTH_LATENCY_MS))
      user.value = resolveMockUser(provider)
    } catch {
      // Unreachable against the mock, but the real request can fail and the
      // dialog already renders this state.
      signInError.value = 'unknown'
    } finally {
      signingIn.value = false
    }
  }

  const signOut = (): void => {
    user.value = null
    signInError.value = null
  }

  return {
    user,
    signingIn,
    signInError,
    isAuthenticated,
    isGuest,
    initials,
    signIn,
    signOut,
  }
})
