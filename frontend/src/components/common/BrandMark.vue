<script setup lang="ts">
/**
 * Placeholder brand mark — an original SVG, not a downloaded logo.
 *
 * It reads as a small dependency graph: two endpoints (solid) feeding one
 * downstream assertion (hollow), which is the product's core idea in one
 * glyph. Swap the paths here when a real logo exists; nothing else changes.
 */
withDefaults(
  defineProps<{
    size?: number
  }>(),
  { size: 28 },
)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
    class="shrink-0"
  >
    <defs>
      <linearGradient :id="'brand-stroke'" x1="0" y1="0" x2="24" y2="24">
        <stop offset="0%" stop-color="#C4B5FD" />
        <stop offset="100%" stop-color="#7C3AED" />
      </linearGradient>
    </defs>

    <rect
      x="1.25"
      y="1.25"
      width="21.5"
      height="21.5"
      rx="6.5"
      stroke="url(#brand-stroke)"
      stroke-opacity="0.55"
      stroke-width="1.1"
    />

    <path
      d="M8 7.5 L16 12 L8 16.5"
      stroke="url(#brand-stroke)"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />

    <circle cx="6.4" cy="7.5" r="1.5" fill="#A78BFA" />
    <circle cx="6.4" cy="16.5" r="1.5" fill="#A78BFA" />
    <circle
      cx="17.6"
      cy="12"
      r="1.6"
      fill="#0A0714"
      stroke="#C4B5FD"
      stroke-width="1.1"
    />
  </svg>
</template>
