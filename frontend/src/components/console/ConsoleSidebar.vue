<script setup lang="ts">
import { Expand, Fold } from '@element-plus/icons-vue'
import { ElDrawer, ElIcon } from 'element-plus'

import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import { useConsoleNav } from '@/composables/useConsoleNav'
import { useI18n } from '@/i18n'
import { useUiStore } from '@/stores/ui'
import ConsoleNavList from './ConsoleNavList.vue'
import EnvironmentSwitcher from './EnvironmentSwitcher.vue'

/**
 * The console rail — the only navigation column in the shell.
 *
 * Two renderings of the same list: a persistent column from `lg` up, and a
 * drawer below it. The drawer is the only place the console overlays content —
 * on a narrow screen the rail would otherwise eat a third of the width.
 *
 * Settings sits in the footer, outside the scrolling list, because it is not a
 * step of anything above it; the collapse control lives there too, so the
 * scrolling area holds nothing but destinations.
 */
const { t } = useI18n()
const ui = useUiStore()
const { items, footerItems, activeKey } = useConsoleNav()
</script>

<template>
  <aside
    class="console-sidebar hidden shrink-0 flex-col border-r border-[var(--console-border)] bg-[var(--console-surface)] transition-[width] duration-200 ease-out lg:flex"
    :style="{
      width: ui.sidebarCollapsed
        ? 'var(--console-sidebar-w-collapsed)'
        : 'var(--console-sidebar-w)',
    }"
  >
    <nav
      class="console-scroll min-h-0 flex-1 px-2.5 py-3"
      :aria-label="t('console.nav.openMenu')"
    >
      <ConsoleNavList
        :items="items"
        :active-key="activeKey"
        :collapsed="ui.sidebarCollapsed"
      />
    </nav>

    <div
      class="flex shrink-0 flex-col gap-0.5 border-t border-[var(--console-border)] p-2.5"
    >
      <ConsoleNavList
        :items="footerItems"
        :active-key="activeKey"
        :collapsed="ui.sidebarCollapsed"
      />

      <button
        type="button"
        class="console-nav-link w-full cursor-pointer border-0 bg-transparent text-left"
        :class="{ 'is-collapsed': ui.sidebarCollapsed }"
        :aria-label="
          ui.sidebarCollapsed ? t('console.nav.expand') : t('console.nav.collapse')
        "
        @click="ui.toggleSidebar()"
      >
        <ElIcon :size="16" class="shrink-0">
          <Expand v-if="ui.sidebarCollapsed" />
          <Fold v-else />
        </ElIcon>
        <span class="console-nav-link__label min-w-0 flex-1 truncate">
          {{
            ui.sidebarCollapsed
              ? t('console.nav.expand')
              : t('console.nav.collapse')
          }}
        </span>
      </button>
    </div>
  </aside>

  <ElDrawer
    v-model="ui.mobileNavOpen"
    direction="ltr"
    :with-header="false"
    size="248px"
    class="console-drawer"
  >
    <!-- The drawer also carries the controls the top bar drops on narrow
         screens, so nothing becomes unreachable just because it is small. -->
    <div class="flex items-center gap-2 border-b border-[var(--console-border)] px-2.5 py-2.5">
      <EnvironmentSwitcher />
      <LanguageSwitcher />
    </div>

    <nav class="px-2.5 py-3" :aria-label="t('console.nav.openMenu')">
      <ConsoleNavList :items="items" :active-key="activeKey" />
      <!-- Nothing to pin the footer against here, so a hairline carries the
           same "outside the list above" meaning instead. -->
      <div class="console-hairline my-2.5" />
      <ConsoleNavList :items="footerItems" :active-key="activeKey" />
    </nav>
  </ElDrawer>
</template>
