<script setup lang="ts">
import { ArrowRight, Delete, FolderOpened } from '@element-plus/icons-vue'
import { ElIcon, ElMessageBox, ElTooltip } from 'element-plus'
import { computed, ref } from 'vue'

import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import { useI18n } from '@/i18n'
import { useApiClientStore } from '@/stores/apiClient'
import type { ApiCollection, ApiCollectionFolder, ApiSavedRequest } from '@/types/api'
import { methodColor } from '@/utils/http'

/**
 * Saved requests.
 *
 * Rendered as a disclosure list rather than `el-tree`: rows need a method
 * chip, an active state tied to the open request, and a hover-only delete —
 * all of which would be fought for inside a tree node template.
 *
 * The tree is flattened into a row list before rendering. Two levels of
 * nesting in a template would mean repeating the request row verbatim in two
 * places, and those copies would drift the first time a row changed.
 */
const { t } = useI18n()
const store = useApiClientStore()

/** Folders start collapsed... */
const expandedFolders = ref<ReadonlySet<string>>(new Set())
/** ...and collections start open, so `this` set holds the *collapsed* ones. */
const collapsedCollections = ref<ReadonlySet<string>>(new Set())

type TreeRow =
  | {
      readonly type: 'collection'
      readonly key: string
      readonly collection: ApiCollection
      readonly count: number
      readonly expanded: boolean
    }
  | {
      readonly type: 'folder'
      readonly key: string
      readonly folder: ApiCollectionFolder
      readonly expanded: boolean
    }
  | { readonly type: 'request'; readonly key: string; readonly request: ApiSavedRequest }

const requestCount = (collection: ApiCollection): number =>
  collection.requests.length +
  collection.folders.reduce((total, folder) => total + folder.requests.length, 0)

/**
 * Two explicit toggles rather than one taking the set as an argument: a ref
 * passed through a template expression arrives unwrapped, so a shared helper
 * would have to take the unwrapped value and lose the ability to write back.
 */
const toggleFolder = (id: string): void => {
  const next = new Set(expandedFolders.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedFolders.value = next
}

const toggleCollection = (id: string): void => {
  const next = new Set(collapsedCollections.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedCollections.value = next
}

const rows = computed<readonly TreeRow[]>(() => {
  const list: TreeRow[] = []

  for (const collection of store.projectCollections) {
    const open = !collapsedCollections.value.has(collection.id)

    list.push({
      type: 'collection',
      key: collection.id,
      collection,
      count: requestCount(collection),
      expanded: open,
    })

    if (!open) continue

    for (const folder of collection.folders) {
      const folderOpen = expandedFolders.value.has(folder.id)

      list.push({
        type: 'folder',
        key: folder.id,
        folder,
        expanded: folderOpen,
      })

      if (folderOpen) {
        for (const request of folder.requests) {
          list.push({ type: 'request', key: request.id, request })
        }
      }
    }

    for (const request of collection.requests) {
      list.push({ type: 'request', key: request.id, request })
    }
  }

  return list
})

const open = (request: ApiSavedRequest): void => {
  store.openSavedRequest(request.id)
}

const remove = async (request: ApiSavedRequest): Promise<void> => {
  try {
    await ElMessageBox.confirm(
      t('console.apiClient.collections.deleteConfirm', { name: request.name }),
      t('console.apiClient.collections.delete'),
      {
        confirmButtonText: t('console.common.delete'),
        cancelButtonText: t('console.common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return // Dismissed.
  }

  store.deleteSavedRequest(request.id)
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div v-if="rows.length === 0" class="flex flex-1 items-center">
      <ConsoleEmptyState
        class="w-full"
        :icon="FolderOpened"
        :title="t('console.apiClient.collections.empty')"
        :body="t('console.apiClient.collections.emptyHint')"
      />
    </div>

    <!-- The list scrolls rather than the rail growing: the rail is a fixed-height
         column, so an unbounded list would push past the bottom of the shell and
         the overflow would be clipped with no way to reach it. -->
    <ul v-else class="console-scroll flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
      <li v-for="row in rows" :key="row.key">
        <!-- Collection -->
        <button
          v-if="row.type === 'collection'"
          type="button"
          class="flex w-full cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-1.5 py-1.5 text-start hover:bg-[var(--console-surface-hover)]"
          :aria-expanded="row.expanded"
          @click="toggleCollection(row.collection.id)"
        >
          <ElIcon
            :size="11"
            class="shrink-0 text-[var(--console-text-muted)] transition-transform duration-150"
            :class="row.expanded ? 'rotate-90' : ''"
          >
            <ArrowRight />
          </ElIcon>
          <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--console-text)]">
            {{ row.collection.name }}
          </span>
          <span class="shrink-0 font-mono text-[10.5px] text-[var(--console-text-muted)]">
            {{ row.count }}
          </span>
        </button>

        <!-- Folder -->
        <button
          v-else-if="row.type === 'folder'"
          type="button"
          class="ms-3 flex w-[calc(100%-0.75rem)] cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-1.5 py-1 text-start hover:bg-[var(--console-surface-hover)]"
          :aria-expanded="row.expanded"
          @click="toggleFolder(row.folder.id)"
        >
          <ElIcon
            :size="10"
            class="shrink-0 text-[var(--console-text-muted)] transition-transform duration-150"
            :class="row.expanded ? 'rotate-90' : ''"
          >
            <ArrowRight />
          </ElIcon>
          <span class="min-w-0 flex-1 truncate text-[12px] text-[var(--console-text-dim)]">
            {{ row.folder.name }}
          </span>
          <span class="shrink-0 font-mono text-[10.5px] text-[var(--console-text-muted)]">
            {{ row.folder.requests.length }}
          </span>
        </button>

        <!-- Request -->
        <div v-else class="group/req ms-6 flex items-center gap-1">
          <button
            type="button"
            class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-1.5 py-1 text-start"
            :class="
              store.openRequestId === row.request.id
                ? 'bg-[color-mix(in_srgb,var(--accent)_14%,transparent)]'
                : 'hover:bg-[var(--console-surface-hover)]'
            "
            @click="open(row.request)"
          >
            <span
              class="w-[42px] shrink-0 font-mono text-[10px] font-semibold"
              :style="{ color: methodColor(row.request.draft.method) }"
            >
              {{ row.request.draft.method }}
            </span>
            <span
              class="min-w-0 flex-1 truncate text-[12px]"
              :class="
                store.openRequestId === row.request.id
                  ? 'text-[var(--accent-soft)]'
                  : 'text-[var(--console-text-dim)]'
              "
            >
              {{ row.request.name }}
            </span>
          </button>

          <ElTooltip
            :content="t('console.apiClient.collections.delete')"
            placement="top"
            :show-after="300"
          >
            <button
              type="button"
              class="flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] opacity-0 transition-opacity duration-150 hover:text-[var(--status-fail)] focus-visible:opacity-100 group-hover/req:opacity-100"
              :aria-label="t('console.apiClient.collections.delete')"
              @click="remove(row.request)"
            >
              <ElIcon :size="12"><Delete /></ElIcon>
            </button>
          </ElTooltip>
        </div>
      </li>
    </ul>
  </div>
</template>
