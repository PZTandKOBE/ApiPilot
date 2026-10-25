<script setup lang="ts">
import CardSwap, { Card } from '@/components/effects/CardSwap.vue'
import AgentPlanCard from '@/components/home/AgentPlanCard.vue'
import AgentWorkflowCard from '@/components/home/AgentWorkflowCard.vue'
import ApiTestingCard from '@/components/home/ApiTestingCard.vue'
import { useI18n } from '@/i18n'

/**
 * Owns the rotating product previews.
 *
 * CardSwap is treated strictly as the animation primitive: it knows nothing
 * about API clients or test plans, it just positions three slot-driven cards.
 * The product UI lives in the three card components, and their order here is
 * the narrative order — request → plan → approval-gated workflow.
 */
const { t } = useI18n()

/** Card box. CardSwap writes these onto each card element directly. */
const CARD_WIDTH = 500
const CARD_HEIGHT = 400
</script>

<template>
  <section class="relative">
    <!-- Section copy -->
    <div
      class="mx-auto flex max-w-2xl flex-col items-center gap-4 text-center lg:mx-0 lg:max-w-xl lg:items-start lg:text-left"
    >
      <span class="text-[11px] font-medium tracking-[0.02em] text-[var(--text-secondary)]">
        {{ t('showcase.eyebrow') }}
      </span>
      <h2
        class="text-balance text-2xl font-semibold leading-tight tracking-[-0.02em] text-[var(--text-primary)] sm:text-3xl"
      >
        {{ t('showcase.title') }}
      </h2>
      <p class="text-sm leading-relaxed text-[var(--text-secondary)]">
        {{ t('showcase.description') }}
      </p>
    </div>

    <!--
      The stage. CardSwap positions itself absolutely against the bottom-right
      of this box and applies its own scale/translate at <=768px, so the box
      only has to reserve the room it needs — the negative bottom margin keeps
      the transparent padding from inflating the page.
    -->
    <!-- Height comes from `--showcase-height` in home.css, which is pinned to
         the measured card stack at each breakpoint. -->
    <div class="showcase-stage mt-6 lg:mt-8">
      <CardSwap
        :width="CARD_WIDTH"
        :height="CARD_HEIGHT"
        :card-distance="60"
        :vertical-distance="70"
        :delay="5000"
        :pause-on-hover="true"
        :skew-amount="6"
        easing="elastic"
      >
        <Card>
          <ApiTestingCard />
        </Card>
        <Card>
          <AgentPlanCard />
        </Card>
        <Card>
          <AgentWorkflowCard />
        </Card>
      </CardSwap>
    </div>
  </section>
</template>
