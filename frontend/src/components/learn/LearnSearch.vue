<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { searchDocs } from '@/content/docs/registry'
import { useI18n } from '@/i18n'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const { t, locale } = useI18n()
const query = ref('')
const input = ref<HTMLInputElement | null>(null)

const results = computed(() => searchDocs(locale.value, query.value))
const hasQuery = computed(() => query.value.trim() !== '')

const close = (): void => {
  emit('close')
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      query.value = ''
      return
    }
    await nextTick()
    input.value?.focus()
  },
)

const focusInput = async (): Promise<void> => {
  await nextTick()
  input.value?.focus()
}

const clearQuery = (): void => {
  query.value = ''
  void focusInput()
}

const trapTab = (event: KeyboardEvent): void => {
  const dialog = event.currentTarget
  if (!(dialog instanceof HTMLElement)) return
  const nodes = Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  )
  const first = nodes[0]
  const last = nodes[nodes.length - 1]
  if (first === undefined || last === undefined) return
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div
    v-if="open"
    class="learn-search-overlay"
    role="presentation"
    @click.self="close"
  >
    <section
      class="learn-search-dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('learn.searchTitle')"
      @keydown.esc.stop="close"
      @keydown.tab="trapTab"
    >
      <header class="learn-search-head">
        <div>
          <p class="learn-search-kicker">{{ t('learn.docsLabel') }}</p>
          <h2>{{ t('learn.searchTitle') }}</h2>
        </div>
        <button
          type="button"
          class="learn-icon-button"
          :aria-label="t('learn.close')"
          :title="t('learn.close')"
          @click="close"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </header>

      <label class="learn-search-field">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="6.5" />
          <path d="m16 16 4 4" />
        </svg>
        <input
          ref="input"
          v-model="query"
          type="search"
          :placeholder="t('learn.searchPlaceholder')"
          :aria-label="t('learn.search')"
          autocomplete="off"
          spellcheck="false"
        />
        <button
          v-if="query !== ''"
          type="button"
          class="learn-search-clear"
          :aria-label="t('learn.close')"
          @click="clearQuery"
        >
          ×
        </button>
      </label>

      <p class="learn-search-hint">{{ t('learn.searchHint') }}</p>

      <div class="learn-search-results" aria-live="polite">
        <p v-if="!hasQuery" class="learn-search-state">{{ t('learn.searchEmpty') }}</p>
        <p v-else-if="results.length === 0" class="learn-search-state">
          {{ t('learn.searchNoResults') }}
        </p>
        <ul v-else>
          <li v-for="result in results" :key="result.doc.slug">
            <RouterLink
              :to="'/learn/' + result.doc.slug"
              class="learn-search-result"
              @click="close"
            >
              <span class="learn-search-result-title">{{ result.title }}</span>
              <span class="learn-search-result-summary">{{ result.summary }}</span>
              <span class="learn-search-result-path">/learn/{{ result.doc.slug }}</span>
            </RouterLink>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
