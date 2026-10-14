<script setup lang="ts">
import HomeNavbar from '@/components/home/HomeNavbar.vue'

/**
 * Public-facing shell: fixed veil backdrop underneath, page content above.
 * The background layers are fixed-position and sit behind everything, so the
 * layout only has to own the stacking context and the vertical rhythm.
 */
</script>

<template>
  <div class="relative min-h-screen">
    <div class="relative z-10 flex min-h-screen flex-col">
      <HomeNavbar />

      <main class="flex-1">
        <slot />
      </main>
    </div>
  </div>
</template>
