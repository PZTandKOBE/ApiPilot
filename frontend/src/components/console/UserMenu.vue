<script setup lang="ts">
import { ArrowDown, Setting, SwitchButton } from '@element-plus/icons-vue'
import {
  ElAvatar,
  ElButton,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElIcon,
} from 'element-plus'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useI18n } from '@/i18n'
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

const signInOpen = ref(false)

/** Settings arrives in a later phase; until then the entry stays inert. */
const settingsAvailable = computed(() => router.hasRoute('console-settings'))

const onCommand = (command: unknown): void => {
  if (command === 'logout') {
    auth.signOut()
    return
  }

  if (command === 'settings' && settingsAvailable.value) {
    void router.push({ name: 'console-settings' })
  }
}
</script>

<template>
  <div class="flex items-center">
    <ElButton
      v-if="auth.isGuest"
      size="small"
      type="primary"
      @click="signInOpen = true"
    >
      {{ t('console.topbar.signIn') }}
    </ElButton>

    <ElDropdown v-else trigger="click" placement="bottom-end" @command="onCommand">
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
              {{ auth.user?.email }}
            </p>
          </li>

          <ElDropdownItem divided command="settings" :disabled="!settingsAvailable">
            <ElIcon class="mr-2"><Setting /></ElIcon>
            {{ t('console.topbar.settings') }}
          </ElDropdownItem>

          <ElDropdownItem command="logout">
            <ElIcon class="mr-2"><SwitchButton /></ElIcon>
            {{ t('console.topbar.logout') }}
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>

    <SignInDialog v-model="signInOpen" />
  </div>
</template>
