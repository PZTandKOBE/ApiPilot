<script setup lang="ts">
import { Menu } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'

import BrandMark from '@/components/common/BrandMark.vue'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import { PROJECT_NAME } from '@/config/project'
import { useI18n } from '@/i18n'
import { useUiStore } from '@/stores/ui'
import EnvironmentSwitcher from './EnvironmentSwitcher.vue'
import NotificationCenter from './NotificationCenter.vue'
import ProjectSwitcher from './ProjectSwitcher.vue'
import UserMenu from './UserMenu.vue'

/**
 * Application top bar.
 *
 * Reading order is deliberate: identity (what product), then context (which
 * project, which environment), then the viewer's own controls. Context sits
 * next to the brand rather than on the right, because "which environment am I
 * about to fire a request at" is the question this bar exists to answer.
 */
const { t } = useI18n()
const ui = useUiStore()
</script>

<template>
  <header
    class="flex h-[var(--console-topbar-h)] shrink-0 items-center gap-1.5 border-b border-[var(--console-border)] bg-[var(--console-surface)] px-2.5 sm:gap-2 sm:px-3"
  >
    <button
      type="button"
      class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-dim)] transition-colors duration-150 hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)] lg:hidden"
      :aria-label="t('console.nav.openMenu')"
      @click="ui.setMobileNav(true)"
    >
      <ElIcon :size="18"><Menu /></ElIcon>
    </button>

    <RouterLink
      to="/console"
      class="flex shrink-0 items-center gap-2 rounded-md"
      :aria-label="PROJECT_NAME"
    >
      <BrandMark :size="24" />
      <span
        class="hidden text-[13px] font-semibold tracking-[-0.01em] text-[var(--console-text)] md:inline"
      >
        {{ PROJECT_NAME }}
      </span>
    </RouterLink>

    <span
      class="mx-1 hidden h-5 w-px shrink-0 bg-[var(--console-border)] md:block"
    />

    <ProjectSwitcher />
    <div class="hidden md:flex">
      <EnvironmentSwitcher />
    </div>

    <div class="min-w-0 flex-1" />

    <div class="hidden sm:flex">
      <LanguageSwitcher />
    </div>

    <NotificationCenter />
    <UserMenu />
  </header>
</template>
