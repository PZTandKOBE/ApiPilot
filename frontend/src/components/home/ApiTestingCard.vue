<script setup lang="ts">
import { useI18n } from '@/i18n'

/**
 * Product preview #1 — the API Client surface.
 *
 * Drawn to read as a real request composer rather than a marketing panel:
 * real HTTP shapes, real header names, monospaced body, and a status/time
 * chip where a client would actually put one.
 */
const { messages } = useI18n()
</script>

<template>
  <article class="flex h-full w-full flex-col overflow-hidden rounded-[inherit]">
    <!-- Title bar -->
    <header
      class="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--glass-border)] px-5 py-3"
    >
      <div class="flex items-center gap-2.5">
        <span class="flex items-center gap-1.5" aria-hidden="true">
          <span class="size-2 rounded-full bg-white/12" />
          <span class="size-2 rounded-full bg-white/12" />
          <span class="size-2 rounded-full bg-white/12" />
        </span>
        <span class="mockup-label">{{ messages.apiTesting.kicker }}</span>
      </div>

      <!-- Response chip: a client surfaces status + latency right where the
           request was issued, so the card shows a *completed* round trip. -->
      <span class="flex items-center gap-2 font-mono text-[10px] tracking-wide">
        <span class="text-[var(--status-pass)]">
          {{ messages.apiTesting.responseStatusValue }}
        </span>
        <span class="text-[var(--text-muted)]">
          {{ messages.apiTesting.timeLabel }} {{ messages.apiTesting.timeValue }}
        </span>
      </span>
    </header>

    <!-- Request line -->
    <div class="flex shrink-0 items-center gap-2.5 px-5 pt-4">
      <span
        class="rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-wider"
        :style="{
          color: 'var(--status-warn)',
          borderColor: 'color-mix(in srgb, var(--status-warn) 34%, transparent)',
          backgroundColor: 'color-mix(in srgb, var(--status-warn) 12%, transparent)',
        }"
      >
        {{ messages.apiTesting.method }}
      </span>
      <span class="truncate font-mono text-[12.5px] text-[var(--text-primary)]">
        {{ messages.apiTesting.path }}
      </span>
    </div>

    <div class="mockup-divider my-3.5" />

    <!-- Headers -->
    <section class="shrink-0 px-5">
      <p class="mockup-label mb-2">{{ messages.apiTesting.headers }}</p>
      <dl class="mockup space-y-1.5">
        <div class="flex items-baseline gap-3">
          <dt class="w-[112px] shrink-0 text-[var(--text-muted)]">
            {{ messages.apiTesting.authKey }}
          </dt>
          <dd class="truncate text-[var(--accent-soft)]">
            {{ messages.apiTesting.authValue }}
          </dd>
        </div>
        <div class="flex items-baseline gap-3">
          <dt class="w-[112px] shrink-0 text-[var(--text-muted)]">
            {{ messages.apiTesting.contentTypeKey }}
          </dt>
          <dd class="truncate text-[var(--text-secondary)]">
            {{ messages.apiTesting.contentTypeValue }}
          </dd>
        </div>
      </dl>
    </section>

    <!-- Body -->
    <section class="min-h-0 flex-1 px-5 pt-3.5">
      <p class="mockup-label mb-2">{{ messages.apiTesting.body }}</p>
      <pre
        class="mockup overflow-hidden rounded-lg border border-[var(--glass-border)] bg-black/35 p-3 text-[11.5px] leading-[1.5] text-[var(--text-secondary)]"
      ><span class="text-[var(--text-muted)]">{</span>
  <span class="text-[var(--accent-soft)]">"product_id"</span><span class="text-[var(--text-muted)]">:</span> <span class="text-[var(--status-pass)]">"prod_001"</span><span class="text-[var(--text-muted)]">,</span>
  <span class="text-[var(--accent-soft)]">"quantity"</span><span class="text-[var(--text-muted)]">:</span> <span class="text-[var(--status-warn)]">2</span>
<span class="text-[var(--text-muted)]">}</span></pre>
    </section>

    <!-- Action row -->
    <footer
      class="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--glass-border)] px-5 py-3"
    >
      <span class="flex items-center gap-2">
        <span class="mockup-label">{{ messages.apiTesting.responseTitle }}</span>
        <span class="font-mono text-[10.5px] text-[var(--status-pass)]">
          {{ messages.apiTesting.responseStatusValue }}
        </span>
      </span>

      <span
        class="rounded-md border px-3 py-1 font-mono text-[10.5px] font-bold tracking-[0.12em]"
        :style="{
          color: 'var(--accent-soft)',
          borderColor: 'var(--glass-border-strong)',
          backgroundColor: 'color-mix(in srgb, var(--accent) 14%, transparent)',
        }"
      >
        {{ messages.apiTesting.send }}
      </span>
    </footer>
  </article>
</template>
