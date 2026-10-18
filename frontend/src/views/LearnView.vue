<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import DocsSidebar from '@/components/learn/DocsSidebar.vue'
import DocsToc from '@/components/learn/DocsToc.vue'
import LearnSearch from '@/components/learn/LearnSearch.vue'
import LearnTopbar from '@/components/learn/LearnTopbar.vue'
import { useClipboard } from '@/composables/useClipboard'
import { useDocsTheme } from '@/composables/useDocsTheme'
import {
  DEFAULT_DOC_SLUG,
  findDoc,
  neighborDocs,
} from '@/content/docs/registry'
import { DOC_GROUP_TITLE_KEYS } from '@/content/docs/types'
import { useI18n } from '@/i18n'
import { renderMarkdown } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const { theme, toggleTheme } = useDocsTheme()
const { copy } = useClipboard()

const drawerOpen = ref(false)
const searchOpen = ref(false)
const activeHeading = ref('')
const notice = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | null = null
let copyTimer: ReturnType<typeof setTimeout> | null = null
let observer: IntersectionObserver | null = null

const slug = computed(() => {
  const value = route.params.slug
  return typeof value === 'string' && value !== '' ? value : DEFAULT_DOC_SLUG
})

const doc = computed(() => findDoc(slug.value))
const groupLabel = computed(() =>
  doc.value === undefined ? '' : t(DOC_GROUP_TITLE_KEYS[doc.value.group]),
)

const rendered = computed(() => {
  if (doc.value === undefined) return { html: '', headings: [] }
  return renderMarkdown(doc.value.body[locale.value], {
    copy: t('learn.copy'),
    copied: t('learn.copied'),
    anchor: t('learn.linkCopied'),
  })
})

const bodyHtml = computed(() => rendered.value.html)
const headings = computed(() => rendered.value.headings)
const neighbors = computed(() =>
  doc.value === undefined
    ? { previous: undefined, next: undefined }
    : neighborDocs(doc.value),
)

const showNotice = (message: string): void => {
  notice.value = message
  if (noticeTimer !== null) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => {
    notice.value = ''
    noticeTimer = null
  }, 2200)
}

const setupObserver = async (): Promise<void> => {
  if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') return
  await nextTick()
  observer?.disconnect()
  const nodes = document.querySelectorAll<HTMLElement>(
    '.docs-content h2[id], .docs-content h3[id]',
  )
  activeHeading.value = nodes[0]?.id ?? ''
  if (nodes.length === 0) return

  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top)
      const first = visible[0]
      if (first) activeHeading.value = first.target.id
    },
    { rootMargin: '-88px 0px -68% 0px', threshold: [0, 1] },
  )
  nodes.forEach((node) => observer?.observe(node))
}

const resetCopyLabel = (button: HTMLButtonElement): void => {
  if (copyTimer !== null) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    button.textContent = t('learn.copy')
    button.classList.remove('is-copied')
    copyTimer = null
  }, 1800)
}

const onArticleClick = async (event: MouseEvent): Promise<void> => {
  const target = event.target
  if (!(target instanceof HTMLElement)) return

  const copyButton = target.closest<HTMLButtonElement>('[data-copy-code]')
  if (copyButton !== null) {
    const block = copyButton.closest('.docs-code')
    const code = block?.querySelector('code')?.textContent ?? ''
    const ok = await copy(code)
    copyButton.textContent = ok ? t('learn.copied') : t('learn.copyFailed')
    copyButton.classList.toggle('is-copied', ok)
    showNotice(ok ? t('learn.copied') : t('learn.copyFailed'))
    resetCopyLabel(copyButton)
    return
  }

  const anchor = target.closest<HTMLAnchorElement>('a[data-heading-anchor]')
  if (anchor !== null) {
    const id = anchor.dataset.headingAnchor ?? ''
    if (id !== '' && typeof window !== 'undefined') {
      const ok = await copy(
        window.location.origin +
          window.location.pathname +
          window.location.search +
          '#' +
          id,
      )
      showNotice(ok ? t('learn.linkCopied') : t('learn.copyFailed'))
    }
    return
  }

  const link = target.closest<HTMLAnchorElement>('a[href]')
  if (link !== null) {
    const href = link.getAttribute('href') ?? ''
    if (href.startsWith('/learn/')) {
      event.preventDefault()
      drawerOpen.value = false
      await router.push(href)
    }
  }
}

const closeSearch = async (): Promise<void> => {
  searchOpen.value = false
  await nextTick()
  document.querySelector<HTMLButtonElement>('.learn-search-trigger')?.focus()
}

const onGlobalKeydown = (event: KeyboardEvent): void => {
  const target = event.target
  const typing =
    target instanceof HTMLElement &&
    (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    if (!typing) {
      event.preventDefault()
      searchOpen.value = true
    }
    return
  }

  if (event.key === 'Escape') {
    if (searchOpen.value) {
      void closeSearch()
    } else if (drawerOpen.value) {
      drawerOpen.value = false
    }
  }
}

watch(
  () => slug.value,
  () => {
    drawerOpen.value = false
    activeHeading.value = ''
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'auto' })
  },
)

watch(
  rendered,
  () => {
    void setupObserver()
  },
  { flush: 'post' },
)

watch(
  () => [doc.value?.title[locale.value] ?? 'ApiPilot', locale.value],
  () => {
    if (typeof document !== 'undefined') {
      document.title = (doc.value?.title[locale.value] ?? 'Learn Us') + ' · ApiPilot'
    }
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  void setupObserver()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  observer?.disconnect()
  if (noticeTimer !== null) clearTimeout(noticeTimer)
  if (copyTimer !== null) clearTimeout(copyTimer)
})
</script>

<template>
  <div class="learn-app" :data-theme="theme">
    <LearnTopbar
      :theme="theme"
      :menu-open="drawerOpen"
      :search-open="searchOpen"
      @toggle-theme="toggleTheme"
      @open-search="searchOpen = true"
      @toggle-menu="drawerOpen = !drawerOpen"
    />

    <div class="learn-shell">
      <div
        v-if="drawerOpen"
        class="learn-drawer-backdrop"
        aria-hidden="true"
        @click="drawerOpen = false"
      />
      <DocsSidebar
        :active-slug="slug"
        :open="drawerOpen"
        @close="drawerOpen = false"
      />

      <main class="learn-main">
        <article v-if="doc !== undefined" class="learn-article">
          <nav class="learn-breadcrumb" :aria-label="t('learn.docsLabel')">
            <RouterLink to="/learn/overview">{{ t('learn.breadcrumbHome') }}</RouterLink>
            <span aria-hidden="true">/</span>
            <span>{{ groupLabel }}</span>
            <span aria-hidden="true">/</span>
            <span aria-current="page">{{ doc.title[locale] }}</span>
          </nav>

          <header class="learn-article-header">
            <p class="learn-eyebrow">{{ groupLabel }}</p>
            <h1>{{ doc.title[locale] }}</h1>
            <p class="learn-summary">{{ doc.summary[locale] }}</p>
          </header>

          <div class="docs-content" v-html="bodyHtml" @click="onArticleClick" />

          <nav class="learn-pager" :aria-label="t('learn.docsLabel')">
            <RouterLink
              v-if="neighbors.previous !== undefined"
              :to="'/learn/' + neighbors.previous.slug"
              class="learn-pager-link learn-pager-previous"
            >
              <span>{{ t('learn.previous') }}</span>
              <strong>{{ neighbors.previous.title[locale] }}</strong>
            </RouterLink>
            <span v-else />
            <RouterLink
              v-if="neighbors.next !== undefined"
              :to="'/learn/' + neighbors.next.slug"
              class="learn-pager-link learn-pager-next"
            >
              <span>{{ t('learn.next') }}</span>
              <strong>{{ neighbors.next.title[locale] }}</strong>
            </RouterLink>
          </nav>
        </article>

        <section v-else class="learn-not-found">
          <p class="learn-eyebrow">{{ t('learn.docsLabel') }}</p>
          <h1>{{ t('learn.notFound') }}</h1>
          <p>{{ t('learn.notFoundBody') }}</p>
          <RouterLink to="/learn/overview" class="learn-primary-link">
            {{ t('learn.backToDocs') }}
          </RouterLink>
        </section>
      </main>

      <DocsToc :headings="headings" :active-id="activeHeading" />
    </div>

    <LearnSearch :open="searchOpen" @close="closeSearch" />

    <p v-if="notice !== ''" class="learn-toast" role="status" aria-live="polite">
      {{ notice }}
    </p>
  </div>
</template>
