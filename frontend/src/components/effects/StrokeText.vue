<script setup lang="ts">
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { computed, onMounted, onUnmounted, ref, watch, type CSSProperties } from 'vue';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
}

export type StrokeTextTrigger = 'mount' | 'hover' | 'scroll' | 'loop';
export type StrokeTextFillMode = 'wipe' | 'fade' | 'none';

interface StrokeTextProps {
  text?: string;
  strokeColor?: string;
  fillColor?: string;
  strokeWidth?: number;
  drawDuration?: number;
  fillDelay?: number;
  stagger?: number;
  ease?: string;
  trigger?: StrokeTextTrigger;
  fillMode?: StrokeTextFillMode;
  /**
   * Number = pixels. A string such as `'4.7em'` is also accepted so the SVG
   * can be sized relative to the surrounding type instead of being pinned to
   * a pixel value — that keeps it responsive to zoom and to user font-size
   * preferences. The geometry below stays unit-agnostic: `getBBox()` returns
   * user-space units, which map 1:1 to the viewBox.
   */
  fontSize?: number | string;
  fontWeight?: number | string;
  letterSpacing?: number;
  reverse?: boolean;
  /** Explicit CSS height for the SVG box; falls back to `fontSize * 1.3`. */
  height?: string;
  className?: string;
  style?: CSSProperties;
}

interface StrokeTextBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

const props = withDefaults(defineProps<StrokeTextProps>(), {
  text: 'Draw Attention',
  strokeColor: '#8bfa99',
  fillColor: '#F8FAFC',
  strokeWidth: 1.4,
  drawDuration: 1.6,
  fillDelay: 0.2,
  stagger: 0.05,
  ease: 'power2.out',
  trigger: 'mount',
  fillMode: 'wipe',
  fontSize: 128,
  fontWeight: 800,
  letterSpacing: -4,
  reverse: false,
  className: ''
});

const rootRef = ref<HTMLSpanElement | null>(null);
const strokeTextRef = ref<SVGTextElement | null>(null);
const wipeRectRef = ref<SVGRectElement | null>(null);

const box = ref<StrokeTextBox | null>(null);

const uid = Math.random().toString(36).slice(2, 10);
const wipeId = `stroke-text-wipe-${uid}`;

const characters = computed(() => Array.from(String(props.text ?? '')));

/**
 * Dash length for the draw-on reveal. It only needs to exceed the longest
 * glyph path, and glyph paths are measured in font-relative user units, so a
 * large constant covers every font size rather than tracking the font size
 * (which may now be a relative unit such as `em`).
 */
const dash = 4000;

/** Bare number of pixels; used only for the fallback viewBox. */
const fontSizePx = computed(() => {
  const parsed = Number.parseFloat(String(props.fontSize));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 128;
});

const resolvedHeight = computed(() =>
  props.height ??
  (/[a-z%]/i.test(String(props.fontSize))
    ? `calc(${props.fontSize} * 1.3)`
    : `${Math.round(fontSizePx.value * 1.3)}px`)
);

const fontStyle = computed<CSSProperties>(() => ({
  // `0.1em` keeps the font relative to its parent when a unit is given;
  // a plain number is treated as pixels.
  fontSize: /[a-z%]/i.test(String(props.fontSize))
    ? String(props.fontSize)
    : `${props.fontSize}px`,
  fontWeight: props.fontWeight,
  letterSpacing: `${props.letterSpacing}px`
}));

const viewBox = computed(() =>
  box.value
    ? `${box.value.x} ${box.value.y} ${box.value.width} ${box.value.height}`
    : `0 ${-fontSizePx.value} 600 ${fontSizePx.value * 1.3}`
);

let cancelMeasure: (() => void) | null = null;

const runMeasure = () => {
  cancelMeasure?.();
  let cancelled = false;
  cancelMeasure = () => {
    cancelled = true;
  };

  const measureOnce = () => {
    if (cancelled) return;
    const node = strokeTextRef.value;
    if (!node) return;
    let bbox: DOMRect | undefined;
    try {
      bbox = node.getBBox();
    } catch {
      return;
    }
    if (!bbox || !bbox.width) return;

    // Padding is in user-space units, so it only has to clear the stroke
    // itself; deriving it from a font size that may be relative would be
    // meaningless here.
    const pad = Math.max(Number(props.strokeWidth) || 1, 4);
    const next: StrokeTextBox = {
      x: bbox.x - pad,
      y: bbox.y - pad,
      width: bbox.width + pad * 2,
      height: bbox.height + pad * 2
    };

    const prev = box.value;
    box.value =
      prev &&
      Math.abs(prev.x - next.x) < 0.5 &&
      Math.abs(prev.width - next.width) < 0.5 &&
      Math.abs(prev.y - next.y) < 0.5
        ? prev
        : next;
  };

  measureOnce();
  if (typeof document !== 'undefined' && document.fonts?.ready) {
    document.fonts.ready.then(measureOnce).catch(() => {});
  }
};

/**
 * The glyph box is only correct once the SVG has been laid out at its final
 * size. When the font size is responsive — a `vw`-derived length, or a unit
 * relative to an ancestor that is itself still resolving — the first
 * measurement happens against a stale box and the viewBox would clip the
 * text. Observing the SVG box closes that loop: any change to the rendered
 * size triggers a fresh measurement, and the comparison in `measureOnce`
 * stops it from looping once the box stabilises.
 */
let resizeObserver: ResizeObserver | null = null;

onMounted(() => {
  runMeasure();

  const svg = rootRef.value?.querySelector('svg');
  if (svg && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => runMeasure());
    resizeObserver.observe(svg);
  }
});

onUnmounted(() => {
  cancelMeasure?.();
  cancelMeasure = null;
  resizeObserver?.disconnect();
  resizeObserver = null;
});

watch(
  () => [characters.value, props.fontSize, props.fontWeight, props.letterSpacing, props.strokeWidth],
  () => runMeasure(),
  { flush: 'post' }
);

let animTeardown: (() => void) | null = null;

const setupAnimation = () => {
  const root = rootRef.value;
  if (typeof window === 'undefined' || !root || !box.value) return;

  const strokes = gsap.utils.toArray<Element>(root.querySelectorAll('[data-stroke-char]'));
  const fills = gsap.utils.toArray<Element>(root.querySelectorAll('[data-fill-char]'));
  const wipe = wipeRectRef.value;
  if (!strokes.length) return;

  const fillEnabled = props.fillMode !== 'none';
  const useWipe = fillEnabled && props.fillMode === 'wipe';
  const fillDuration = Math.max(0.4, props.drawDuration * 0.5);
  const staggerConfig: number | gsap.StaggerVars = props.reverse
    ? { each: props.stagger, from: 'end' as const }
    : props.stagger;
  const targets = [...strokes, ...fills, wipe].filter(Boolean);

  const setStartState = () => {
    gsap.killTweensOf(targets);
    gsap.set(strokes, { strokeDasharray: dash, strokeDashoffset: dash });
    gsap.set(fills, { opacity: useWipe ? 1 : 0 });
    if (wipe) gsap.set(wipe, { attr: { width: 0 } });
  };

  const setEndState = () => {
    gsap.killTweensOf(targets);
    gsap.set(strokes, { strokeDasharray: dash, strokeDashoffset: 0 });
    gsap.set(fills, { opacity: fillEnabled ? 1 : 0 });
    if (wipe) gsap.set(wipe, { attr: { width: fillEnabled ? box.value!.width : 0 } });
  };

  const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (prefersReducedMotion) {
    setEndState();
    animTeardown = () => gsap.killTweensOf(targets);
    return;
  }

  const build = (): gsap.core.Timeline => {
    setStartState();
    const tl = gsap.timeline({
      paused: true,
      repeat: props.trigger === 'loop' ? -1 : 0,
      repeatDelay: props.trigger === 'loop' ? 0.9 : 0,
      defaults: { overwrite: 'auto' }
    });

    tl.to(strokes, { strokeDashoffset: 0, duration: props.drawDuration, ease: props.ease, stagger: staggerConfig }, 0);

    if (useWipe && wipe) {
      tl.to(
        wipe,
        { attr: { width: box.value!.width }, duration: fillDuration, ease: 'power2.inOut' },
        props.drawDuration + props.fillDelay
      );
    } else if (fillEnabled) {
      tl.to(
        fills,
        { opacity: 1, duration: fillDuration, ease: 'power2.out', stagger: staggerConfig },
        props.drawDuration + props.fillDelay
      );
    }

    return tl;
  };

  let timeline: gsap.core.Timeline | null = null;
  let scrollTrigger: ReturnType<typeof ScrollTrigger.create> | null = null;
  let removeHover: (() => void) | null = null;

  if (props.trigger === 'hover') {
    setEndState();
    const play = () => {
      timeline?.kill();
      timeline = build();
      timeline.play(0);
    };
    root.addEventListener('pointerenter', play);
    removeHover = () => root.removeEventListener('pointerenter', play);
  } else {
    timeline = build();
    if (props.trigger === 'scroll') {
      scrollTrigger = ScrollTrigger.create({
        trigger: root,
        start: 'top 82%',
        once: true,
        onEnter: () => timeline?.play(0)
      });
    } else {
      timeline.play(0);
    }
  }

  animTeardown = () => {
    removeHover?.();
    scrollTrigger?.kill();
    timeline?.kill();
    gsap.killTweensOf(targets);
  };
};

onUnmounted(() => {
  animTeardown?.();
  animTeardown = null;
});

watch(
  () => [
    box.value,
    dash,
    props.drawDuration,
    props.fillDelay,
    props.stagger,
    props.ease,
    props.trigger,
    props.fillMode,
    props.reverse
  ],
  () => {
    animTeardown?.();
    animTeardown = null;
    setupAnimation();
  },
  { flush: 'post' }
);
</script>

<template>
  <span
    ref="rootRef"
    class="block w-full leading-0"
    :class="[trigger === 'hover' ? 'cursor-pointer' : '', className]"
    :style="style"
    role="img"
    :aria-label="String(text ?? '')"
  >
    <!-- Height can be supplied by the caller (e.g. a token derived from the
         surrounding type scale) so the box does not have to be re-derived
         from the font size. -->
    <svg
      class="block w-full"
      :style="{ height: resolvedHeight }"
      :viewBox="viewBox"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      <defs v-if="fillMode === 'wipe' && box">
        <clipPath :id="wipeId" clipPathUnits="userSpaceOnUse">
          <rect ref="wipeRectRef" :x="box.x" :y="box.y" width="0" :height="box.height" />
        </clipPath>
      </defs>

      <text
        ref="strokeTextRef"
        class="select-none"
        x="0"
        y="0"
        fill="none"
        :stroke="strokeColor"
        :stroke-width="strokeWidth"
        stroke-linejoin="round"
        stroke-linecap="round"
        :style="fontStyle"
      >
        <tspan v-for="(char, index) in characters" data-stroke-char :key="`s-${index}`">{{ char }}</tspan>
      </text>

      <text
        class="select-none"
        x="0"
        y="0"
        :fill="fillColor"
        stroke="none"
        :style="fontStyle"
        :clip-path="fillMode === 'wipe' && box ? `url(#${wipeId})` : undefined"
      >
        <tspan v-for="(char, index) in characters" data-fill-char :key="`f-${index}`">{{ char }}</tspan>
      </text>
    </svg>
  </span>
</template>
