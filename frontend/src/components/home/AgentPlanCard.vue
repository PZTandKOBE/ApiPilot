<script setup lang="ts">
import { useI18n } from '@/i18n'

/**
 * Product preview #2 — the Agent's proposed test plan.
 *
 * The point this card has to land is that the Agent *stops here* and hands
 * control back: a concrete, reviewable plan with an explicit risk rating and
 * a human decision at the bottom. That is why Approve/Reject are the
 * heaviest elements on the card.
 *
 * The controls are deliberately inert — this is a preview inside a rotating
 * showcase, not the console. Making them real would imply behaviour that
 * does not exist yet.
 */
const { messages } = useI18n()
</script>

<template>
  <article class="flex h-full w-full flex-col overflow-hidden rounded-[inherit]">
    <!-- Title bar -->
    <header
      class="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--glass-border)] px-5 py-3"
    >
      <span class="mockup-label">{{ messages.plan.kicker }}</span>
      <span
        class="rounded-full border border-[var(--glass-border-strong)] bg-[var(--accent)]/10 px-2 py-0.5 font-mono text-[9.5px] tracking-wide text-[var(--accent-soft)]"
      >
        {{ messages.plan.generatedBy }}
      </span>
    </header>

    <!-- Proposed cases -->
    <section class="min-h-0 flex-1 px-5 py-4">
      <ul class="space-y-2.5">
        <li
          v-for="testCase in messages.plan.cases"
          :key="testCase"
          class="flex items-center gap-2.5"
        >
          <svg
            viewBox="0 0 16 16"
            class="size-3.5 shrink-0"
            aria-hidden="true"
            focusable="false"
          >
            <circle
              cx="8"
              cy="8"
              r="6.6"
              fill="color-mix(in srgb, var(--status-pass) 14%, transparent)"
              stroke="color-mix(in srgb, var(--status-pass) 46%, transparent)"
              stroke-width="1"
            />
            <path
              d="M5.2 8.2 7 10 10.8 6"
              fill="none"
              stroke="var(--status-pass)"
              stroke-width="1.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <span class="truncate text-[12.5px] text-[var(--text-secondary)]">
            {{ testCase }}
          </span>
        </li>
      </ul>
    </section>

    <!-- Risk + volume -->
    <section class="shrink-0 px-5">
      <div
        class="flex items-center justify-between rounded-lg border border-[var(--glass-border)] bg-white/[0.02] px-3.5 py-2.5"
      >
        <div class="flex items-center gap-2">
          <span class="mockup-label">{{ messages.plan.riskLabel }}</span>
          <span
            class="inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold text-[var(--status-warn)]"
          >
            <span
              class="size-1.5 rounded-full bg-[var(--status-warn)]"
              aria-hidden="true"
            />
            {{ messages.plan.riskValue }}
          </span>
        </div>

        <div class="flex items-baseline gap-2">
          <span class="mockup-label">{{ messages.plan.countLabel }}</span>
          <span class="font-mono text-[13px] font-semibold text-[var(--text-primary)]">
            {{ messages.plan.countValue }}
          </span>
        </div>
      </div>
    </section>

    <!-- Human decision -->
    <footer
      class="mt-4 flex shrink-0 flex-col gap-2.5 border-t border-[var(--glass-border)] px-5 py-3.5"
    >
      <div class="flex items-center gap-2.5">
        <span
          class="flex-1 rounded-lg border border-[var(--glass-border)] bg-white/[0.02] px-3 py-1.5 text-center text-[11.5px] font-medium text-[var(--text-muted)]"
        >
          {{ messages.plan.reject }}
        </span>
        <span
          class="flex-1 rounded-lg border px-3 py-1.5 text-center text-[11.5px] font-semibold"
          :style="{
            color: 'var(--text-primary)',
            borderColor: 'var(--glass-border-strong)',
            backgroundColor: 'color-mix(in srgb, var(--accent) 22%, transparent)',
            boxShadow: '0 0 24px -6px color-mix(in srgb, var(--accent) 55%, transparent)',
          }"
        >
          {{ messages.plan.approve }}
        </span>
      </div>

      <p class="text-center text-[10.5px] leading-relaxed text-[var(--text-muted)]">
        {{ messages.plan.note }}
      </p>
    </footer>
  </article>
</template>
