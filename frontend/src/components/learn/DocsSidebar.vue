<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { DOC_GROUPS, docsForGroup } from '@/content/docs/registry'
import { DOC_GROUP_TITLE_KEYS, type DocGroupId } from '@/content/docs/types'
import { useI18n } from '@/i18n'

const props = defineProps<{
  activeSlug: string
  open: boolean
}>()

const emit = defineEmits<{ close: [] }>()
const { t, locale } = useI18n()
const isMobile = ref(false)
let mediaQuery: MediaQueryList | null = null

const onMediaChange = (event: MediaQueryListEvent): void => {
  isMobile.value = event.matches
}

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  mediaQuery = window.matchMedia('(max-width: 860px)')
  isMobile.value = mediaQuery.matches
  mediaQuery.addEventListener('change', onMediaChange)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', onMediaChange)
})

const groupTitle = (group: DocGroupId): string => t(DOC_GROUP_TITLE_KEYS[group])
const groups = computed(() =>
  DOC_GROUPS.map((group) => ({
    id: group.id,
    docs: docsForGroup(group.id),
  })),
)
</script>

<template>
  <aside
    id="learn-sidebar"
    class="learn-sidebar"
    :class="{ 'is-open': open }"
    :inert="isMobile && !open"
    :aria-hidden="isMobile && !open ? 'true' : undefined"
    :aria-label="t('learn.docsLabel')"
  >
    <div class="learn-sidebar-inner">
      <p class="learn-sidebar-kicker">{{ t('learn.docsLabel') }}</p>

      <nav class="learn-sidebar-nav">
        <details
          v-for="group in groups"
          :key="group.id"
          class="learn-nav-group"
          open
        >
          <summary>
            <span>{{ groupTitle(group.id) }}</span>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="m8 10 4 4 4-4" />
            </svg>
          </summary>

          <ul>
            <li v-for="doc in group.docs" :key="doc.slug">
              <RouterLink
                :to="'/learn/' + doc.slug"
                class="learn-nav-link"
                :class="{ 'is-active': doc.slug === activeSlug }"
                :aria-current="doc.slug === activeSlug ? 'page' : undefined"
                @click="emit('close')"
              >
                {{ doc.title[locale] }}
              </RouterLink>
            </li>
          </ul>
        </details>
      </nav>

      <div class="learn-sidebar-footer">
        <RouterLink to="/" class="learn-sidebar-home">{{ t('learn.brand') }}</RouterLink>
        <span aria-hidden="true">·</span>
        <RouterLink to="/learn/overview">{{ t('learn.docsLabel') }}</RouterLink>
      </div>
    </div>
  </aside>
</template>
