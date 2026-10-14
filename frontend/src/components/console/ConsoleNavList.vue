<script setup lang="ts">
import { useI18n } from '@/i18n'
import type { ResolvedNavItem } from '@/types/console'
import ConsoleNavLink from './ConsoleNavLink.vue'

/**
 * The nav list renderer, shared by the persistent rail and the mobile drawer —
 * two renderings of one list, so an active item, a group heading and a
 * disabled entry look identical in both because they are the same component,
 * not two lookalikes.
 */
withDefaults(
  defineProps<{
    items: readonly ResolvedNavItem[]
    /** `routeName` of the active item. */
    activeKey: string | null
    collapsed?: boolean
  }>(),
  { collapsed: false },
)

const { t } = useI18n()
</script>

<template>
  <ul class="flex flex-col gap-0.5">
    <template v-for="item in items" :key="item.routeName">
      <li
        v-if="item.groupKey && !collapsed"
        class="console-label px-2.5 pb-1.5 pt-4 first:pt-1"
      >
        {{ t(item.groupKey) }}
      </li>
      <li v-else-if="item.groupKey" class="console-hairline mx-2 my-2.5" />

      <li>
        <ConsoleNavLink
          :item="item"
          :active="item.routeName === activeKey"
          :collapsed="collapsed"
        />
      </li>
    </template>
  </ul>
</template>
