<script setup lang="ts">
import { RouterView } from 'vue-router'

import { useDocumentTitle } from '@/composables/useDocumentTitle'

/**
 * Route-agnostic root. Layouts (MarketingLayout / ConsoleLayout) are chosen
 * per route, not here — this component only owns document-level concerns.
 */
useDocumentTitle()
</script>

<template>
  <RouterView />
</template>
