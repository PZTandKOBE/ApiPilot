<script setup lang="ts">
import StrokeText from '@/components/effects/StrokeText.vue'
import { useI18n } from '@/i18n'

/**
 * The hero display title.
 *
 * Each entry in `hero.titleLines` becomes one self-drawing SVG line. The
 * real text also lives in a visually-hidden `<h1>`, because StrokeText
 * exposes itself as `role="img"` with an aria-label — correct for a graphic,
 * but not a substitute for the page's top-level heading.
 *
 * Sizing is driven by the `.hero-title` custom property in home.css. The em
 * value is handed to StrokeText as a relative unit rather than a pixel count,
 * so the SVG inherits the responsive scale instead of pinning itself to a
 * fixed size.
 */
const { messages } = useI18n()

/** Only the first line takes the brighter fill; the second stays cooler. */
const FILL_BY_INDEX = ['#F8FAFC', '#DCD6F7'] as const

/**
 * Per-line type scale. The em values are relative to `.hero-title`, whose
 * font-size is deliberately left at the document default — the responsive
 * units are resolved there, so each line is simply a multiple of one number.
 *
 * The heights are not derived from the em values because the line box needs
 * ~1.3x the glyph size to clear ascenders and descenders; measuring the
 * glyph box and scaling by the last line's ratio was the alternative, but a
 * token is easier to reason about and cannot drift.
 */
const LINE_EM = ['2.4em', '2em'] as const
const LINE_HEIGHT = [
  'var(--hero-title-line-height)',
  'var(--hero-title-line-height)',
] as const
</script>

<template>
  <h1 class="hero-title">
    <span class="visually-hidden">{{ messages.hero.titleLines.join(' ') }}</span>

    <span aria-hidden="true" class="block">
      <span
        v-for="(line, index) in messages.hero.titleLines"
        :key="line"
        class="block"
      >
        <StrokeText
          :text="line"
          :class="[
            'hero-title__line',
            index === 0
              ? 'hero-title__line--primary'
              : 'hero-title__line--secondary',
          ]"
          :font-size="index === 0 ? LINE_EM[0] : LINE_EM[1]"
          :height="index === 0 ? LINE_HEIGHT[0] : LINE_HEIGHT[1]"
          stroke-color="#A78BFA"
          :fill-color="FILL_BY_INDEX[index] ?? '#F8FAFC'"
          :stroke-width="1.6"
          :draw-duration="1.6"
          :fill-delay="0.2"
          :stagger="0.05"
          ease="power2.out"
          trigger="mount"
          fill-mode="wipe"
          :font-weight="800"
          :letter-spacing="-0.045"
        />
      </span>
    </span>
  </h1>
</template>
