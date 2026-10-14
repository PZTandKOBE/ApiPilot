<script setup lang="ts">
import { Back, MagicStick, Tickets } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import ApprovalPanel from '@/components/console/Agent/ApprovalPanel.vue'
import TestPlan from '@/components/console/Agent/TestPlan.vue'
import ConsoleEmptyState from '@/components/console/ConsoleEmptyState.vue'
import ConsolePageHeader from '@/components/console/ConsolePageHeader.vue'
import { useLocalizedText } from '@/composables/useLocalizedText'
import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'
import type { TestPlan as TestPlanModel } from '@/types/agent'

/**
 * A plan on its own page.
 *
 * The whole view is a lookup: take the id from the route, find the plan in the
 * store, hand it to the same components the lab uses. Nothing about a plan is
 * re-implemented here — the header, the scenarios, the approval gate and the
 * metadata editor are the shared ones, given a different plan to display.
 */
const { t } = useI18n()
const { localize } = useLocalizedText()
const store = useAgentStore()
const route = useRoute()

/**
 * Read through `projectPlans` rather than a dedicated getter: a plan only
 * exists in the context of its project, and looking it up any other way could
 * surface one that belongs somewhere else.
 */
const plan = computed<TestPlanModel | null>(() => {
  const planId = route.params.planId
  if (typeof planId !== 'string') return null

  return store.projectPlans.find((candidate) => candidate.id === planId) ?? null
})
</script>

<template>
  <div class="console-page">
    <ConsolePageHeader
      v-if="plan !== null"
      :title="localize(plan.name)"
      :eyebrow="t('console.plans.title')"
    >
      <template #meta>
        <RouterLink
          :to="{ name: 'console-project-plans' }"
          class="mt-2 flex items-center gap-1.5 text-[11.5px] text-[var(--accent-soft)] hover:underline"
        >
          <ElIcon :size="11"><Back /></ElIcon>
          {{ t('console.plans.backToList') }}
        </RouterLink>
      </template>
    </ConsolePageHeader>

    <div v-if="plan === null" class="console-panel">
      <ConsoleEmptyState
        :icon="Tickets"
        :title="t('console.plans.notFound')"
        :body="t('console.plans.notFoundBody')"
      >
        <div class="flex flex-wrap items-center justify-center gap-2">
          <RouterLink
            :to="{ name: 'console-project-plans' }"
            class="rounded-md border border-[var(--console-border)] px-3 py-1.5 text-[12px] text-[var(--console-text-dim)] hover:border-[var(--console-border-strong)]"
          >
            {{ t('console.plans.backToList') }}
          </RouterLink>

          <RouterLink
            :to="{ name: 'console-project-ai-test' }"
            class="inline-flex items-center gap-1.5 rounded-md border border-[var(--console-border-strong)] px-3 py-1.5 text-[12px] text-[var(--accent-soft)]"
          >
            <ElIcon :size="13"><MagicStick /></ElIcon>
            {{ t('console.plans.openLab') }}
          </RouterLink>
        </div>
      </ConsoleEmptyState>
    </div>

    <div v-else class="flex flex-col gap-4">
      <TestPlan :plan="plan" />
      <ApprovalPanel :plan="plan" />

      <ElButton class="self-start" size="small" @click="$router.back()">
        <ElIcon class="mr-1.5"><Back /></ElIcon>
        {{ t('console.plans.backToList') }}
      </ElButton>
    </div>
  </div>
</template>
