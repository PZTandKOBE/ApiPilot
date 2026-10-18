<script setup lang="ts">
import { computed } from 'vue'

import BrandMark from '@/components/common/BrandMark.vue'
import { APP_ENTRY_ROUTE } from '@/config/project'
import type { DocsTheme } from '@/composables/useDocsTheme'
import { useI18n, type AppLocale } from '@/i18n'

const props = defineProps<{
  theme: DocsTheme
  menuOpen: boolean
  searchOpen: boolean
}>()

const emit = defineEmits<{
  toggleTheme: []
  openSearch: []
  toggleMenu: []
}>()

const { t, locale, setLocale } = useI18n()

const nextLocale = computed<AppLocale>(() =>
  locale.value === 'zh-CN' ? 'en-US' : 'zh-CN',
)
const themeAction = computed(() =>
  props.theme === 'dark' ? t('learn.switchToLight') : t('learn.switchToDark'),
)
const menuAction = computed(() =>
  props.menuOpen ? t('learn.closeMenu') : t('learn.menu'),
)

const onLocale = (): void => {
  setLocale(nextLocale.value)
}
</script>

<template>
  <header class="learn-topbar">
    <div class="learn-topbar-inner">
      <div class="learn-topbar-left">
        <button
          type="button"
          class="learn-icon-button learn-menu-button"
          :aria-label="menuAction"
          :aria-expanded="menuOpen"
          aria-controls="learn-sidebar"
          @click="emit('toggleMenu')"
        >
          <span class="learn-menu-lines" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
        </button>

        <RouterLink to="/learn/overview" class="learn-brand" :aria-label="t('learn.brand')">
          <BrandMark :size="28" />
          <span class="learn-brand-name">{{ t('learn.brand') }}</span>
        </RouterLink>

        <span class="learn-docs-badge">{{ t('learn.docsLabel') }}</span>
      </div>

      <div class="learn-topbar-actions">
        <button
          type="button"
          class="learn-search-trigger"
          :class="{ 'is-active': searchOpen }"
          :aria-label="t('learn.search')"
          :aria-expanded="searchOpen"
          @click="emit('openSearch')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="6.5" />
            <path d="m16 16 4 4" />
          </svg>
          <span class="learn-search-label">{{ t('learn.search') }}</span>
          <kbd>Ctrl K</kbd>
        </button>

        <button
          type="button"
          class="learn-icon-button learn-theme-button"
          :aria-label="themeAction"
          :title="themeAction"
          @click="emit('toggleTheme')"
        >
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20.2 14.2A8.5 8.5 0 0 1 9.8 3.8 8.5 8.5 0 1 0 20.2 14.2Z" />
          </svg>
          <span class="learn-theme-label">
            {{ theme === 'dark' ? t('learn.dark') : t('learn.light') }}
          </span>
        </button>

        <button
          type="button"
          class="learn-locale-button"
          :aria-label="t('nav.language')"
          :title="t('nav.language')"
          @click="onLocale"
        >
          {{ nextLocale === 'en-US' ? 'EN' : '中文' }}
        </button>

        <RouterLink :to="APP_ENTRY_ROUTE" class="learn-try-link">
          {{ t('learn.tryUs') }}
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12h13M13 6l6 6-6 6" />
          </svg>
        </RouterLink>
      </div>
    </div>
  </header>
</template>
