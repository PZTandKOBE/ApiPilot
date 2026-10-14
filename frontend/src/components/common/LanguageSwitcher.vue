<script setup lang="ts">
import { computed } from 'vue'

import { useI18n, type AppLocale } from '@/i18n'

const { locale, setLocale, t } = useI18n()

interface LocaleOption {
  value: AppLocale
  /** Self-describing label so the target language is legible in any locale. */
  label: string
  aria: string
}

const OPTIONS: LocaleOption[] = [
  { value: 'zh-CN', label: '中文', aria: '切换到中文' },
  { value: 'en-US', label: 'EN', aria: 'Switch to English' },
]

/**
 * Native radio inputs carry selection state and arrow-key traversal for
 * free — the visual pill is just a label over the top of them.
 */
const groupName = computed(() => `locale-${locale.value}`)
</script>

<template>
  <div
    class="relative inline-flex items-center rounded-full border border-[var(--glass-border)] bg-white/[0.03] p-0.5 backdrop-blur-md"
    role="radiogroup"
    :aria-label="t('nav.language')"
  >
    <label
      v-for="option in OPTIONS"
      :key="option.value"
      class="relative cursor-pointer rounded-full px-2.5 py-1 text-[11px] font-medium tracking-wide transition-colors duration-200"
      :class="
        locale === option.value
          ? 'bg-[var(--accent)]/16 text-[var(--text-primary)] shadow-[inset_0_0_0_1px_rgba(167,139,250,0.35)]'
          : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
      "
    >
      <input
        type="radio"
        class="sr-only"
        :name="groupName"
        :value="option.value"
        :checked="locale === option.value"
        :aria-label="option.aria"
        @change="setLocale(option.value)"
      />
      {{ option.label }}
    </label>
  </div>
</template>
