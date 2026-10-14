<script setup lang="ts">
import { Compass } from '@element-plus/icons-vue'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import { useI18n } from '@/i18n'

/**
 * Catch-all for `/console/*`.
 *
 * Rendered inside the console shell on purpose: the rail and the top bar stay
 * usable, so a mistyped URL costs the user nothing but a click.
 */
const { t } = useI18n()
</script>

<template>
  <div class="console-page">
    <div class="console-panel">
      <ConsoleEmptyState
        :icon="Compass"
        :title="t('console.project.notFound')"
        :body="t('console.project.notFoundBody')"
      >
        <RouterLink
          to="/console/dashboard"
          class="text-[12.5px] text-[var(--accent-soft)] hover:underline"
        >
          {{ t('console.nav.dashboard') }}
        </RouterLink>
      </ConsoleEmptyState>
    </div>
  </div>
</template>
