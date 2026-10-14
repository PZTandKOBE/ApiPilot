<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { useI18n } from '@/i18n'

/**
 * Product preview #3 — the Agent's multi-step workflow.
 *
 * Nodes are real DOM rows, which keeps text rendering, truncation and i18n in
 * HTML where they belong. The connector spine is drawn afterwards from the
 * *measured* marker positions rather than a fixed viewBox, so the diagram
 * stays aligned at any width and under any locale.
 *
 * The connector labels are the whole argument of this card: `token`,
 * `Bearer`, `order_id` — the values the Agent carries from one request into
 * the next. It is not issuing isolated calls.
 */
const { messages } = useI18n()

const listRef = ref<HTMLOListElement | null>(null)

interface Connector {
  /** Vertical segment between two markers, in container coordinates. */
  path: string
  cx: number
  cy: number
}

const connectors = shallowRef<Connector[]>([])
const size = ref({ width: 0, height: 0 })

/** Vertical inset so a marker never touches the segment it terminates. */
const GAP = 5

let observer: ResizeObserver | null = null
let frame = 0

const measure = (): void => {
  const list = listRef.value
  if (!list) return

  // Markers are the leading span of each row; use them as the source of
  // truth so the diagram follows whatever the row layout actually did.
  const markers = Array.from(
    list.querySelectorAll<HTMLElement>('[data-node-marker]'),
  )
  if (markers.length === 0) return

  const listBox = list.getBoundingClientRect()
  size.value = { width: listBox.width, height: listBox.height }

  const centers = markers.map((marker) => {
    const box = marker.getBoundingClientRect()
    return {
      x: box.left - listBox.left + box.width / 2,
      y: box.top - listBox.top + box.height / 2,
    }
  })

  const next: Connector[] = []
  for (let i = 0; i < centers.length - 1; i += 1) {
    const from = centers[i]
    const to = centers[i + 1]
    next.push({
      path: `M ${from.x} ${from.y + GAP} L ${to.x} ${to.y - GAP}`,
      cx: from.x,
      cy: from.y,
    })
  }

  const last = centers[centers.length - 1]
  next.push({ path: '', cx: last.x, cy: last.y })

  connectors.value = next
}

const scheduleMeasure = (): void => {
  if (frame) cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    frame = 0
    measure()
  })
}

onMounted(() => {
  scheduleMeasure()

  // Web fonts land after first paint and shift row heights; re-measure then.
  document.fonts?.ready.then(scheduleMeasure).catch(() => {})

  if (listRef.value) {
    observer = new ResizeObserver(scheduleMeasure)
    observer.observe(listRef.value)
  }
})

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
  observer?.disconnect()
  observer = null
})

/** Badges are marked in the copy as a bracketed suffix, e.g. `Login [auth]`. */
const BADGE_PATTERN = /\[([^\]]+)\]/

const labelOf = (node: string): string => node.replace(BADGE_PATTERN, '').trim()
const badgeOf = (node: string): string | undefined => node.match(BADGE_PATTERN)?.[1]
</script>

<template>
  <article
    class="mockup flex h-full w-full flex-col overflow-hidden rounded-[inherit]"
  >
    <header
      class="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--glass-border)] px-5 py-3"
    >
      <span class="mockup-label truncate">{{ messages.workflow.kicker }}</span>
      <span
        class="inline-flex items-center gap-1.5 rounded-full border border-[var(--status-pass)]/30 bg-[var(--status-pass)]/10 px-2 py-0.5 text-[9.5px] tracking-wide text-[var(--status-pass)]"
      >
        <span
          class="size-1.5 rounded-full bg-[var(--status-pass)] shadow-[0_0_8px_1px_rgba(74,222,128,0.55)]"
          aria-hidden="true"
        />
        {{ messages.workflow.passed }}
      </span>
    </header>

    <section class="relative min-h-0 flex-1 px-5 py-3.5">
      <!-- Diagram layer. `inset-0` makes the SVG's coordinate space identical
           to the section, which is also what the markers are measured
           against — so the spine cannot drift from the rows. -->
      <svg
        v-if="size.width > 0"
        class="pointer-events-none absolute inset-0"
        :viewBox="`0 0 ${size.width} ${size.height}`"
        :width="size.width"
        :height="size.height"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id="workflow-spine" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.2" />
            <stop offset="60%" stop-color="var(--accent)" stop-opacity="0.7" />
            <stop offset="100%" stop-color="var(--status-pass)" stop-opacity="0.9" />
          </linearGradient>
        </defs>

        <path
          v-for="(connector, index) in connectors"
          :key="`connector-${index}`"
          :d="connector.path"
          stroke="url(#workflow-spine)"
          stroke-width="1.4"
          stroke-linecap="round"
          fill="none"
        />
      </svg>

      <ol ref="listRef" class="relative z-1 flex h-full flex-col justify-between">
        <li
          v-for="(node, index) in messages.workflow.nodes"
          :key="node"
          class="relative flex items-center gap-3"
        >
          <!-- Marker column + sparkline. Both are decorative: the ordered list
               already conveys the sequence to assistive tech. -->
          <span
            data-node-marker
            class="z-1 grid size-[22px] shrink-0 place-items-center"
            aria-hidden="true"
          >
            <span
              v-if="index < messages.workflow.nodes.length - 1"
              class="size-[7px] rounded-full bg-[var(--accent)] shadow-[0_0_9px_1px_color-mix(in_srgb,var(--accent)_55%,transparent)]"
            />
            <span
              v-else
              class="size-[11px] rounded-full border-[1.6px] border-[var(--status-pass)] bg-[var(--bg-deep)] shadow-[0_0_10px_1px_color-mix(in_srgb,var(--status-pass)_45%,transparent)]"
            />
          </span>

          <span
            class="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-[var(--glass-border)] bg-white/[0.03] px-3 py-1.5"
          >
            <span class="truncate text-[12px] font-medium text-[var(--text-secondary)]">
              {{ labelOf(node) }}
            </span>
            <span
              v-if="badgeOf(node)"
              class="ml-auto shrink-0 rounded border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-1.5 py-0.5 text-[9.5px] text-[var(--accent-soft)]"
            >
              {{ badgeOf(node) }}
            </span>
          </span>

          <span
            v-if="messages.workflow.edges[index]"
            class="w-[74px] shrink-0 truncate text-[10px] text-[var(--text-muted)]"
          >
            {{ messages.workflow.edges[index] }}
          </span>
        </li>
      </ol>
    </section>

    <!-- Fingerprint of the evidence the Agent collected along the way. -->
    <footer
      class="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--glass-border)] px-5 py-2.5"
    >
      <span class="mockup-label">{{ messages.workflow.evidence }}</span>
      <span class="text-[10.5px] text-[var(--accent-soft)]">
        {{ messages.workflow.evidenceValue }}
      </span>
    </footer>
  </article>
</template>
