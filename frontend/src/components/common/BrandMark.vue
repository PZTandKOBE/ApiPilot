<script setup lang="ts">
/**
 * ApiPilot brand mark.
 *
 * The supplied logo master is a white-background lockup. The public mark is a
 * faithful icon crop on its original light field; the light tile keeps the
 * black/purple mark legible on the console's dark surfaces.
 */
withDefaults(
  defineProps<{
    size?: number
  }>(),
  { size: 28 },
)

/** Runtime URL: keeps the public asset out of Vite's SSR static-URL rewrite. */
const markSrc = '/brand/apipilot-mark.png'
</script>

<template>
  <span
    class="inline-flex shrink-0 overflow-hidden rounded-[7px] bg-white shadow-[0_0_0_1px_rgba(196,181,253,0.16)]"
    :style="{ width: size + 'px', height: size + 'px' }"
    aria-hidden="true"
  >
    <img
      :src="markSrc"
      alt=""
      width="512"
      height="512"
      class="h-full w-full object-cover"
      draggable="false"
    />
  </span>
</template>
