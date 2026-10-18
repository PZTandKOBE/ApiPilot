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
    <div class="flex flex-col items-center gap-8 text-center lg:items-start lg:text-left">
      <!-- Eyebrow -->
      <div
        class="inline-flex items-center gap-2 rounded-full border border-[var(--glass-border)] bg-white/[0.03] px-3.5 py-1.5 backdrop-blur-md"
      >
        <span
          class="size-1.5 rounded-full bg-[var(--accent)] shadow-[0_0_10px_2px_rgba(167,139,250,0.6)]"
          aria-hidden="true"
        />
        <span class="mockup-label !text-[var(--text-secondary)]">
          {{ messages.hero.badge }}
        </span>
      </div>

      <HeroTitle />

      <!-- Value proposition -->
      <p
        class="max-w-[34ch] text-balance text-lg leading-snug text-[var(--text-secondary)] sm:text-xl lg:max-w-[40ch] lg:text-[1.35rem]"
      >
        <span class="block text-[var(--text-primary)]">
          {{ messages.hero.subtitleLine1 }}
        </span>
        <span class="block">{{ messages.hero.subtitleLine2 }}</span>
      </p>

      <HeroActions />

      <!-- Pipeline caption -->
      <ul
        class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1.5 lg:justify-start"
      >
        <li
          v-for="(step, index) in pipeline"
          :key="step"
          class="flex items-center gap-2"
        >
          <span
            class="font-mono text-[10.5px] uppercase tracking-[0.18em] text-[var(--text-muted)] transition-colors duration-300 hover:text-[var(--accent-soft)]"
          >
            {{ step }}
          </span>
          <span
            v-if="index < pipeline.length - 1"
            class="text-[10px] text-[var(--accent)]/45"
            aria-hidden="true"
            >→</span
          >
        </li>
      </ul>

      <p class="text-xs text-[var(--text-muted)]">{{ messages.hero.ctaHint }}</p>
    </div>
  </section>
</template>
