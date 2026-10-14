<script setup lang="ts">
import DarkVeil from '@/components/effects/DarkVeil.vue'
import HomeHero from '@/components/home/HomeHero.vue'
import ProductShowcase from '@/components/home/ProductShowcase.vue'
import MarketingLayout from '@/layouts/MarketingLayout.vue'

/**
 * Landing page composition only.
 *
 * Everything below is delegated: the background stack, the hero, and the
 * product showcase each own their internals. This file just declares the
 * stacking order (veil → glow → grain → content) and the section rhythm.
 */

/** Id shared between the hero's secondary CTA and the showcase section. */
const SHOWCASE_ID = 'product-showcase'
</script>

<template>
  <div class="relative min-h-screen">
    <!-- Background stack. Every layer is fixed and pointer-transparent so it
         can never intercept a click or widen the document. -->
    <div class="veil-backdrop" aria-hidden="true">
      <DarkVeil
        :hue-shift="24"
        :noise-intensity="0.035"
        :scanline-intensity="0"
        :scanline-frequency="0"
        :speed="0.32"
        :warp-amount="0.14"
      />
    </div>
    <div class="veil-glow" aria-hidden="true" />
    <div class="veil-grain" aria-hidden="true" />

    <MarketingLayout>
      <div class="shell hero-stage">
        <div
          class="grid items-center gap-16 pb-24 pt-10 lg:min-h-[calc(100svh-72px)] lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:gap-10 lg:pb-28 lg:pt-4"
        >
          <HomeHero :scroll-target-id="SHOWCASE_ID" />

          <div :id="SHOWCASE_ID" class="w-full scroll-mt-24">
            <ProductShowcase />
          </div>
        </div>
      </div>
    </MarketingLayout>
  </div>
</template>
