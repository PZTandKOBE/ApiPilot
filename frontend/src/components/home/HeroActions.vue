<script setup lang="ts">
import { useRouter } from 'vue-router'

import SpecularButton from '@/components/effects/SpecularButton.vue'
import { APP_ENTRY_ROUTE } from '@/config/project'
import { useI18n } from '@/i18n'

const props = defineProps<{
  /** Element id of the section the secondary CTA scrolls to. */
  scrollTargetId: string
}>()

const router = useRouter()
const { t } = useI18n()

const prefersReducedMotion = (): boolean =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

const onTryUs = (): void => {
  // TODO: point APP_ENTRY_ROUTE at the real console once it exists.
  void router.push(APP_ENTRY_ROUTE)
}

const onLearnUs = (): void => {
  const target = document.getElementById(props.scrollTargetId)
  if (!target) return

  target.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start',
  })
}
</script>

<template>
  <!--
    SpecularButton is the CTA primitive here rather than a plain <button>, so
    the specular highlight is part of the product's visual language. `autoAnimate`
    is kept on so the rim light stays discoverable: with `followMouse` alone the
    highlight is gated behind pointer proximity and zeroes out before the cursor
    gets close, which reads as a dead control.
  -->
  <div class="flex flex-wrap items-center gap-3 sm:gap-4">
    <SpecularButton
      size="lg"
      :radius="14"
      tint="#ffffff"
      :tint-opacity="0.015"
      :blur="10"
      line-color="#c4b5fd"
      base-color="#3b1580"
      :intensity="1"
      :shine-size="13"
      :shine-fade="46"
      :thickness="1.05"
      :speed="0.3"
      :follow-mouse="true"
      :auto-animate="true"
      :proximity="280"
      data-testid="cta-try-us"
      @click="onTryUs"
    >
      {{ t('hero.tryUs') }}
    </SpecularButton>

    <SpecularButton
      size="lg"
      :radius="14"
      tint="#ffffff"
      :tint-opacity="0.03"
      :blur="12"
      line-color="#cbd5e1"
      base-color="#33333a"
      :intensity="0.85"
      :shine-size="9"
      :shine-fade="42"
      :thickness="1"
      :speed="0.24"
      :follow-mouse="true"
      :auto-animate="true"
      :proximity="260"
      data-testid="cta-learn-us"
      @click="onLearnUs"
    >
      {{ t('hero.learnUs') }}
    </SpecularButton>
  </div>
</template>
