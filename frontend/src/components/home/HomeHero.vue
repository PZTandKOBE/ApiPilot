<script setup lang="ts">
import { computed } from 'vue'

import HeroActions from '@/components/home/HeroActions.vue'
import HeroTitle from '@/components/home/HeroTitle.vue'
import { useI18n } from '@/i18n'

const { messages } = useI18n()

/**
 * The pipeline the Agent actually runs, shown as a quiet caption under the
 * value proposition so the product's mental model is stated once in text
 * before the cards demonstrate it. Sourced from the dictionary so the stages
 * localise alongside the rest of the page.
 */
const pipeline = computed(() => messages.value.showcase.steps)
</script>

<template>
  <section class="relative">
    <div class="flex flex-col items-center gap-7 text-center lg:items-start lg:text-left">
      <!-- Eyebrow -->
      <div
        class="inline-flex items-center rounded-full border border-[var(--glass-border)] bg-white/[0.03] px-3 py-1.5 backdrop-blur-md"
      >
        <span
          class="text-[11.5px] font-medium leading-none tracking-[0.01em] text-[var(--text-secondary)]"
        >
          {{ messages.hero.badge }}
        </span>
      </div>

      <HeroTitle />

      <!-- Value proposition -->
      <div class="flex max-w-[34rem] flex-col items-center gap-3 lg:items-start">
        <h2
          class="text-balance text-[clamp(1.55rem,2.3vw,2.05rem)] font-semibold leading-[1.25] tracking-[-0.025em] text-[var(--text-primary)]"
        >
          {{ messages.hero.headline }}
        </h2>
        <p class="text-[14px] leading-relaxed text-[var(--text-secondary)]">
          {{ messages.hero.support }}
        </p>
      </div>

      <HeroActions />

      <!-- Pipeline caption -->
      <ol
        class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1.5 lg:justify-start"
      >
        <li
          v-for="(step, index) in pipeline"
          :key="step"
          class="flex items-center gap-2"
        >
          <span
            class="text-[11.5px] font-medium tracking-[0.01em] text-[var(--text-secondary)]"
          >
            {{ step }}
          </span>
          <span
            v-if="index < pipeline.length - 1"
            class="text-[11px] text-[var(--accent)]/60"
            aria-hidden="true"
            >→</span
          >
        </li>
      </ol>

      <p class="text-[12.5px] leading-relaxed text-[var(--text-secondary)]">
        {{ messages.hero.ctaHint }}
      </p>
    </div>
  </section>
</template>
