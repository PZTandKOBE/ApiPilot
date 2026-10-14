<script setup lang="ts">
import { ArrowRight, CopyDocument, Expand } from '@element-plus/icons-vue'
import { ElIcon, ElTooltip } from 'element-plus'
import { computed, ref, watch } from 'vue'

import ConsoleTabs from '@/components/console/ConsoleTabs.vue'
import { useClipboard } from '@/composables/useClipboard'
import { useI18n } from '@/i18n'
import type { ConsoleTab } from '@/types/console'
import {
  collectContainerPaths,
  flattenJson,
  formatJson,
  parseJson,
  type JsonNodeKind,
  type JsonRow,
} from '@/utils/json'

/**
 * Response body viewer.
 *
 * Hand-rolled rather than pulled from a library: what is needed here is a
 * read-only tree, a raw view and a copy button, and a full JSON editor would
 * be hundreds of kilobytes for that.
 *
 * Two behaviours worth stating:
 *
 * - Expansion state is per response, reset whenever the body changes. Carrying
 *   paths over from a previous response would leave unrelated nodes open.
 * - The tree/raw choice *is* remembered across responses, because it reflects
 *   how the reader likes to read, not what they were reading. A non-JSON body
 *   overrides it — there is nothing to tree.
 *
 * The root takes `flex-1` so the toolbar stays put while the body scrolls: the
 * content box below only scrolls internally if it is the one that shrinks, and
 * that contract has to be established here or the whole viewer grows instead.
 */
const props = defineProps<{ text: string }>()

const { t } = useI18n()
const { copy, copied } = useClipboard()

const parsed = computed(() => parseJson(props.text))
const isJson = computed(() => parsed.value.ok)
const isEmpty = computed(() => props.text.trim() === '')

const preferredView = ref('tree')
const expanded = ref<ReadonlySet<string>>(new Set(['$']))

/** Only a JSON body can be treed; anything else is shown as it arrived. */
const view = computed(() => (isJson.value ? preferredView.value : 'raw'))

const tabs = computed<readonly ConsoleTab[]>(() => [
  { key: 'tree', label: t('console.apiClient.json.tree') },
  { key: 'raw', label: t('console.apiClient.json.raw') },
])

/**
 * Open the root and its immediate children by default.
 *
 * Depth is derived from the path rather than tracked during the walk: `$.data`
 * is depth 1, `$.data[0]` is depth 2.
 */
const defaultExpansion = (value: unknown): ReadonlySet<string> =>
  new Set(
    collectContainerPaths(value).filter(
      (path) => path.split(/[.[]/).length <= 2,
    ),
  )

watch(
  () => props.text,
  (text) => {
    const outcome = parseJson(text)
    expanded.value = outcome.ok ? defaultExpansion(outcome.value) : new Set()
  },
  { immediate: true },
)

const rows = computed<readonly JsonRow[]>(() => {
  const outcome = parsed.value
  return outcome.ok ? flattenJson(outcome.value, expanded.value) : []
})

const prettyText = computed(() => formatJson(props.text))

const toggle = (path: string): void => {
  const next = new Set(expanded.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  expanded.value = next
}

const expandAll = (): void => {
  const outcome = parsed.value
  if (!outcome.ok) return
  expanded.value = new Set(collectContainerPaths(outcome.value))
}

const collapseAll = (): void => {
  expanded.value = new Set(['$'])
}

const valueClass = (kind: JsonNodeKind): string => {
  switch (kind) {
    case 'string':
      return 'json-string'
    case 'number':
      return 'json-number'
    case 'boolean':
      return 'json-boolean'
    case 'null':
      return 'json-null'
    default:
      return 'json-punctuation'
  }
}

const previewLabel = (row: JsonRow): string =>
  row.kind === 'array'
    ? t('console.apiClient.json.arrayItems', { count: row.childCount })
    : t('console.apiClient.json.objectKeys', { count: row.childCount })

const onCopy = async (): Promise<void> => {
  await copy(prettyText.value)
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <!-- Toolbar -->
    <div class="flex shrink-0 items-center justify-between gap-3 pb-2.5">
      <ConsoleTabs
        v-if="isJson && !isEmpty"
        v-model="preferredView"
        :tabs="tabs"
        :aria-label="t('console.apiClient.json.tree')"
      />
      <span v-else class="console-label">
        {{ isEmpty ? t('console.apiClient.json.empty') : 'text' }}
      </span>

      <div class="flex shrink-0 items-center gap-1">
        <template v-if="isJson && view === 'tree'">
          <ElTooltip :content="t('console.apiClient.json.expandAll')" placement="top" :show-after="300">
            <button
              type="button"
              class="flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
              :aria-label="t('console.apiClient.json.expandAll')"
              @click="expandAll"
            >
              <ElIcon :size="14"><Expand /></ElIcon>
            </button>
          </ElTooltip>

          <ElTooltip :content="t('console.apiClient.json.collapseAll')" placement="top" :show-after="300">
            <button
              type="button"
              class="flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-[var(--console-text-muted)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
              :aria-label="t('console.apiClient.json.collapseAll')"
              @click="collapseAll"
            >
              <ElIcon :size="14" class="rotate-90"><ArrowRight /></ElIcon>
            </button>
          </ElTooltip>
        </template>

        <button
          v-if="!isEmpty"
          type="button"
          class="flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1 text-[11.5px] text-[var(--console-text-dim)] hover:bg-[var(--console-surface-hover)] hover:text-[var(--console-text)]"
          @click="onCopy"
        >
          <ElIcon :size="14"><CopyDocument /></ElIcon>
          {{ copied ? t('console.common.copied') : t('console.apiClient.json.copy') }}
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="min-h-0 flex-1 overflow-auto console-scroll">
      <p
        v-if="isEmpty"
        class="py-8 text-center text-[12.5px] text-[var(--console-text-muted)]"
      >
        {{ t('console.apiClient.json.empty') }}
      </p>

      <pre
        v-else-if="!isJson"
        class="whitespace-pre-wrap break-all font-mono text-[12px] leading-[1.7] text-[var(--console-text-dim)]"
      >{{ text }}</pre>

      <pre
        v-else-if="view === 'raw'"
        class="whitespace-pre-wrap break-all font-mono text-[12px] leading-[1.7] text-[var(--console-text-dim)]"
      >{{ prettyText }}</pre>

      <div v-else class="flex flex-col">
        <div
          v-for="row in rows"
          :key="row.path"
          class="flex items-start gap-1 rounded-sm font-mono text-[12px] leading-[1.7] hover:bg-white/[0.035]"
          :style="{ paddingInlineStart: `${row.depth * 14}px` }"
        >
          <button
            v-if="row.expandable"
            type="button"
            class="mt-[4px] flex size-3.5 shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent text-[var(--console-text-muted)] hover:text-[var(--accent-soft)]"
            :aria-label="row.expanded ? t('console.apiClient.json.collapseAll') : t('console.apiClient.json.expandAll')"
            :aria-expanded="row.expanded"
            @click="toggle(row.path)"
          >
            <ElIcon
              :size="10"
              class="transition-transform duration-150"
              :class="row.expanded ? 'rotate-90' : ''"
            >
              <ArrowRight />
            </ElIcon>
          </button>
          <span v-else class="size-3.5 shrink-0" />

          <span class="min-w-0 whitespace-pre-wrap break-all">
            <template v-if="row.isCloser">
              <span class="json-punctuation">{{ row.value }}{{ row.last ? '' : ',' }}</span>
            </template>

            <template v-else>
              <template v-if="row.label !== ''">
                <span class="json-key">{{ row.label }}</span>
                <span class="json-punctuation">: </span>
              </template>

              <template v-if="row.expandable">
                <span class="json-punctuation">
                  {{ row.kind === 'array' ? '[' : '{' }}
                  <template v-if="!row.expanded">
                    … {{ row.kind === 'array' ? ']' : '}' }}<template v-if="!row.last">,</template>
                  </template>
                </span>
                <span
                  v-if="!row.expanded"
                  class="ms-2 text-[11px] text-[var(--console-text-muted)]"
                >
                  {{ previewLabel(row) }}
                </span>
              </template>

              <template v-else>
                <span :class="valueClass(row.kind)">{{ row.value }}</span>
                <span v-if="!row.last" class="json-punctuation">,</span>
              </template>
            </template>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
