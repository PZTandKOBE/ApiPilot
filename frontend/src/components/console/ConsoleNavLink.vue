<script setup lang="ts">
import { ElIcon, ElTooltip } from 'element-plus'
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import type { ResolvedNavItem } from '@/types/console'

const props = withDefaults(
  defineProps<{
    item: ResolvedNavItem
    active?: boolean
    /** Icon-only rail: the label stays in the DOM for screen readers. */
    collapsed?: boolean
  }>(),
  { active: false, collapsed: false },
)

const { t } = useI18n()

const label = computed(() => t(props.item.labelKey))

/**
 * The optional second line. Only entries that would otherwise look like the
 * same destination carry one, so it is read as a distinction rather than as
 * decoration — and it is dropped in the collapsed rail alongside the label,
 * because an icon-only row has no room for a sentence.
 */
const hint = computed(() =>
  props.item.hintKey === undefined ? '' : t(props.item.hintKey),
)

/**
 * Destinations whose route is not registered yet stay visible but inert.
 *
 * The information architecture is part of what the console communicates, so
 * hiding unbuilt entries would misrepresent the product; linking to a 404
 * would break it. An entry becomes live on its own the moment its route is
 * registered — nothing here needs editing when that happens.
 */
const unavailableHint = computed(
  () => `${label.value} — ${t('console.nav.notBuiltYet')}`,
)
</script>

<template>
  <ElTooltip
    :disabled="!collapsed"
    :content="label"
    placement="right"
    :offset="14"
    :show-after="160"
  >
    <RouterLink
      v-if="item.available"
      :to="item.to"
      class="console-nav-link"
      :class="{
        'is-active': active,
        'is-collapsed': collapsed,
        'has-hint': hint !== '',
      }"
      :aria-current="active ? 'page' : undefined"
    >
      <ElIcon :size="16" class="shrink-0">
        <component :is="item.icon" />
      </ElIcon>
      <span class="console-nav-link__text min-w-0 flex-1">
        <span class="console-nav-link__label block truncate">{{ label }}</span>
        <span
          v-if="hint"
          class="console-nav-link__hint block truncate text-[11px] leading-tight font-normal text-[var(--console-text-muted)]"
        >
          {{ hint }}
        </span>
      </span>
      <span
        v-if="item.badge"
        class="shrink-0 rounded-full bg-white/8 px-1.5 py-0.5 font-mono text-[10px] leading-none text-[var(--console-text-muted)]"
      >
        {{ item.badge }}
      </span>
    </RouterLink>

    <span
      v-else
      class="console-nav-link is-disabled"
      :class="{
        'is-collapsed': collapsed,
        'has-hint': hint !== '',
      }"
      :title="collapsed ? undefined : unavailableHint"
      aria-disabled="true"
    >
      <ElIcon :size="16" class="shrink-0">
        <component :is="item.icon" />
      </ElIcon>
      <span class="console-nav-link__text min-w-0 flex-1">
        <span class="console-nav-link__label block truncate">{{ label }}</span>
        <span
          v-if="hint"
          class="console-nav-link__hint block truncate text-[11px] leading-tight font-normal text-[var(--console-text-muted)]"
        >
          {{ hint }}
        </span>
      </span>
    </span>
  </ElTooltip>
</template>
