<script setup lang="ts">
import { Expand, Fold, FolderOpened, Plus } from '@element-plus/icons-vue'
import { ElDrawer, ElIcon, ElTooltip } from 'element-plus'
import { computed, ref } from 'vue'

import ApiRequestBar from '@/components/console/ApiClient/ApiRequestBar.vue'
import CollectionsPanel from '@/components/console/ApiClient/CollectionsPanel.vue'
import HistoryPanel from '@/components/console/ApiClient/HistoryPanel.vue'
import RequestTabs from '@/components/console/ApiClient/RequestTabs.vue'
import ResponsePanel from '@/components/console/ApiClient/ResponsePanel.vue'
import SaveRequestDialog from '@/components/console/ApiClient/SaveRequestDialog.vue'
import ConsoleTabs from '@/components/console/ConsoleTabs.vue'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { useResizableSplit } from '@/composables/useResizableSplit'
import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import { useUiStore } from '@/stores/ui'
import type { ConsoleTab } from '@/types/console'

/**
 * API Client workspace.
 *
 * Three columns that behave differently on purpose: the saved-request rail is
 * disposable chrome, the request editor and the response are both content, and
 * the divider between those two is draggable because the right split depends
 * on whether the user is writing a body or reading a response.
 *
 * The whole workspace is viewport-height and its panes scroll individually —
 * the request bar must not scroll away, which is only possible because
 * `ConsoleLayout` gives this page a fixed-height pane to live in.
 *
 * It claims that height by *growing into* the frame (`flex-1`) rather than by
 * asking for `height: 100%`: `ProjectLayout`'s column is the box that owns the
 * viewport height, and a grown flex item fills it without depending on
 * percentage resolution, which silently falls back to `auto` the moment the
 * containing block's own height stops being definite.
 *
 * Both panes carry the same 140px floor. They share whatever height the shell
 * has left, and on a short viewport two floors are the entire budget: a taller
 * floor on either side would not shrink the other pane, it would push it past
 * the bottom of the shell where `overflow: hidden` cuts it off unreachably.
 */
const { t } = useI18n()
const store = useApiClientStore()
const ui = useUiStore()

const railTab = ref('collections')
const railDrawerOpen = ref(false)
const saveDialogOpen = ref(false)

const railTabs = computed<readonly ConsoleTab[]>(() => [
  { key: 'collections', label: t('console.apiClient.collections.title') },
  { key: 'history', label: t('console.apiClient.history.title') },
])

/** Below `md` the rail becomes a drawer; above it, a column. */
const isWide = useMediaQuery('(min-width: 1024px)')

/** Owned here so it can be bound with a template ref in the markup below. */
const containerRef = ref<HTMLElement | null>(null)

const { ratio, dragging, onPointerDown } = useResizableSplit(containerRef, {
  initial: 0.5,
  min: 0.2,
  max: 0.8,
})

/**
 * The draggable pane's size.
 *
 * `flexShrink` stays at 1 even though the ratio is a deliberate choice: both
 * panes have a floor, and on a short viewport the two floors are the largest
 * thing that fits. Leaving it at 0 lets a dragged-down splitter push the
 * response past the bottom of the pane instead, where the shell's
 * `overflow: hidden` would cut it off with no way back. Shrinking only ever
 * happens once the panes cannot both keep the ratio, so at every size that
 * fits, the drag behaves exactly as before.
 */
const requestPaneStyle = computed(() =>
  isWide.value
    ? { flexBasis: `${String(ratio.value * 100)}%`, flexGrow: 0, flexShrink: 1 }
    : { flexGrow: 1, flexShrink: 1, flexBasis: '0%' },
)

const onNewRequest = (): void => {
  store.newRequest()
  railDrawerOpen.value = false
}
</script>

<template>
  <div class="flex min-h-0 flex-1 overflow-hidden">
    <!-- Saved requests rail (>= md) -->
    <aside
      v-if="!ui.apiRailCollapsed"
      class="hidden w-[286px] shrink-0 flex-col border-r border-[var(--console-border)] bg-[var(--console-surface)] p-2.5 md:flex"
    >
      <header class="flex shrink-0 items-center justify-between gap-2 pb-2">
        <ConsoleTabs
          v-model="railTab"
          :tabs="railTabs"
          :aria-label="t('console.apiClient.collections.title')"
        />

        <div class="flex shrink-0 items-center gap-0.5">
          <ElTooltip :content="t('console.apiClient.newRequest')" placement="top" :show-after="300">
            <button
              type="button"
              class="flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-dim)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
              :aria-label="t('console.apiClient.newRequest')"
              @click="onNewRequest"
            >
              <ElIcon :size="15"><Plus /></ElIcon>
            </button>
          </ElTooltip>

          <ElTooltip :content="t('console.nav.collapse')" placement="top" :show-after="300">
            <button
              type="button"
              class="flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
              :aria-label="t('console.nav.collapse')"
              @click="ui.toggleApiRail()"
            >
              <ElIcon :size="14"><Fold /></ElIcon>
            </button>
          </ElTooltip>
        </div>
      </header>

      <CollectionsPanel v-if="railTab === 'collections'" />
      <HistoryPanel v-else />
    </aside>

    <!-- Collapsed rail handle -->
    <button
      v-else
      type="button"
      class="hidden w-9 shrink-0 cursor-pointer items-start justify-center border-0 border-r border-[var(--console-border)] bg-[var(--console-surface)] pt-3.5 text-[var(--console-text-muted)] hover:text-[var(--console-text)] md:flex"
      :aria-label="t('console.nav.expand')"
      @click="ui.toggleApiRail()"
    >
      <ElIcon :size="15"><Expand /></ElIcon>
    </button>

    <!-- Main -->
    <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3.5">
      <!-- Small screens get the rail as a drawer instead of a column. -->
      <button
        type="button"
        class="flex shrink-0 cursor-pointer items-center gap-2 self-start rounded-md border border-[var(--console-border)] bg-transparent px-2.5 py-1.5 text-[12px] text-[var(--console-text-dim)] md:hidden"
        @click="railDrawerOpen = true"
      >
        <ElIcon :size="14"><FolderOpened /></ElIcon>
        {{ t('console.apiClient.collections.title') }}
      </button>

      <ApiRequestBar @save="saveDialogOpen = true" />

      <div ref="containerRef" class="flex min-h-0 flex-1 flex-col">
        <!-- Request -->
        <section
          class="console-panel flex min-h-[140px] flex-col p-3.5"
          :style="requestPaneStyle"
        >
          <RequestTabs />
        </section>

        <!-- Divider -->
        <div
          v-if="isWide"
          class="group/split flex h-2 shrink-0 cursor-row-resize items-center justify-center"
          role="separator"
          aria-orientation="horizontal"
          @pointerdown="onPointerDown"
        >
          <span
            class="h-px w-8 rounded-full transition-colors duration-150"
            :class="
              dragging
                ? 'bg-[var(--accent)]'
                : 'bg-[var(--console-border)] group-hover/split:bg-[var(--console-border-strong)]'
            "
          />
        </div>
        <div v-else class="h-1.5 shrink-0" />

        <!-- Response -->
        <ResponsePanel />
      </div>
    </div>

    <!-- Rail drawer (< md) -->
    <ElDrawer
      v-model="railDrawerOpen"
      direction="ltr"
      :with-header="false"
      size="290px"
      class="console-drawer"
    >
      <div class="flex h-full flex-col p-2.5">
        <header class="flex shrink-0 items-center justify-between gap-2 pb-2">
          <ConsoleTabs v-model="railTab" :tabs="railTabs" />
          <button
            type="button"
            class="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-dim)] hover:bg-[var(--console-surface-hover)]"
            :aria-label="t('console.apiClient.newRequest')"
            @click="onNewRequest"
          >
            <ElIcon :size="15"><Plus /></ElIcon>
          </button>
        </header>

        <CollectionsPanel v-if="railTab === 'collections'" />
        <HistoryPanel v-else />
      </div>
    </ElDrawer>

    <SaveRequestDialog v-model="saveDialogOpen" />
  </div>
</template>
