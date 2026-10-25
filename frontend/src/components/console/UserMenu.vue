<script setup lang="ts">
import {
  ArrowDown,
  SwitchButton,
  User as UserIcon,
} from '@element-plus/icons-vue'
import {
  ElAvatar,
  ElButton,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElIcon,
} from 'element-plus'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useI18n } from '@/i18n'
import { revokeSession } from '@/services/session'
import { useAuthStore } from '@/stores/auth'
import SignInDialog from './SignInDialog.vue'

/**
 * Account entry point.
 *
 * Guest is a supported mode, not an error state: the API Client and the test
 * lab work without an account, so the menu offers sign-in without demanding
 * it. The identity header inside the dropdown is the "profile" — a separate
 * profile page would be a page for its own sake.
 */
const { t } = useI18n()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const signInOpen = ref(false)

const onCommand = async (command: unknown): Promise<void> => {
  if (command === 'login') {
    signInOpen.value = true
    return
  }

  if (command === 'leave-guest') {
    await revokeSession()
    await router.replace({ name: 'login', query: { next: route.fullPath } })
    return
  }

  if (command === 'logout') {
    await auth.signOut()
    if (auth.isOfficialCloud && auth.user === null) {
      void router.replace({ name: 'login', query: { next: '/console' } })
    }
  }
}
</script>

<template>
  <div class="flex items-center">
    <ElButton
      v-if="auth.isGuest && auth.isOfficialCloud && !auth.guestEnabled"
      size="small"
      type="primary"
      @click="signInOpen = true"
    >
      {{ t('console.topbar.signIn') }}
    </ElButton>

    <ElDropdown
      v-else-if="auth.isGuest"
      trigger="click"
      placement="bottom-end"
      @command="onCommand"
    >
      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent py-1 pl-1 pr-1.5 text-[var(--console-text-muted)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)]"
        :aria-label="t('console.topbar.guest')"
        :title="t('console.topbar.guestHint')"
        aria-haspopup="menu"
      >
        <ElAvatar
          :size="26"
          class="!bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] !text-[var(--accent-soft)]"
        >
          <ElIcon :size="14"><UserIcon /></ElIcon>
        </ElAvatar>
        <span class="hidden text-[12.5px] sm:inline">
          {{ t('console.topbar.guest') }}
        </span>
        <ElIcon :size="12" class="hidden sm:inline">
          <ArrowDown />
        </ElIcon>
      </button>

      <template #dropdown>
        <ElDropdownMenu class="min-w-[230px]">
          <li class="list-none px-3 py-2">
            <p class="truncate text-[13px] font-medium text-[var(--console-text)]">
              {{ t('console.topbar.guestMode') }}
            </p>
            <p class="truncate text-[11.5px] text-[var(--console-text-muted)]">
              {{ t('console.topbar.guestHint') }}
            </p>
          </li>

          <ElDropdownItem divided command="login">
            <ElIcon class="mr-2"><UserIcon /></ElIcon>
            {{ t('console.topbar.loginAccount') }}
          </ElDropdownItem>

          <ElDropdownItem command="leave-guest">
            <ElIcon class="mr-2"><SwitchButton /></ElIcon>
            {{ t('console.topbar.leaveGuest') }}
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>

    <ElDropdown
      v-else-if="auth.isAuthenticated"
      trigger="click"
      placement="bottom-end"
      @command="onCommand"
    >
      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent py-1 pl-1 pr-1.5 transition-colors duration-150 hover:bg-[var(--console-surface-hover)]"
        :aria-label="t('console.topbar.account')"
      >
        <ElAvatar
          :size="26"
          :src="auth.user?.avatarUrl ?? undefined"
          class="!bg-[color-mix(in_srgb,var(--accent)_26%,transparent)] !text-[11px] !font-semibold !text-[var(--accent-soft)]"
        >
          {{ auth.initials }}
        </ElAvatar>
        <span
          class="hidden max-w-[120px] truncate text-[12.5px] text-[var(--console-text-dim)] sm:inline"
        >
          {{ auth.user?.name }}
        </span>
        <ElIcon :size="12" class="hidden text-[var(--console-text-muted)] sm:inline">
          <ArrowDown />
        </ElIcon>
      </button>

      <template #dropdown>
        <ElDropdownMenu class="min-w-[220px]">
          <li class="list-none px-3 py-2">
            <p class="truncate text-[13px] font-medium text-[var(--console-text)]">
              {{ auth.user?.name }}
            </p>
            <p class="truncate text-[11.5px] text-[var(--console-text-muted)]">
              {{ auth.user?.email ?? t('auth.noEmail') }}
            </p>
          </li>

          <ElDropdownItem divided command="logout">
            <ElIcon class="mr-2"><SwitchButton /></ElIcon>
            {{ t('console.topbar.logout') }}
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>

    <SignInDialog v-model="signInOpen" />
  </div>
</template>
