<script setup lang="ts">
import BrandMark from '@/components/common/BrandMark.vue'
import GithubIcon from '@/components/common/GithubIcon.vue'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import { GITHUB_REPO, GITHUB_URL, hasGithubUrl, PROJECT_NAME } from '@/config/project'
import { useI18n } from '@/i18n'

const { t } = useI18n()

/**
 * Until a real repository URL is configured (see @/config/project), the
 * GitHub entry renders as a non-interactive control rather than a link that
 * would 404. It stays visible so the layout is final.
 */
const githubAvailable = hasGithubUrl()
</script>

<template>
  <header class="relative z-20 w-full">
    <nav
      class="shell flex h-[72px] items-center justify-between gap-4"
      :aria-label="t('nav.home')"
    >
      <!-- Brand -->
      <RouterLink
        to="/"
        class="group flex min-w-0 items-center gap-2.5 rounded-lg"
        :aria-label="PROJECT_NAME"
      >
        <span
          class="transition-transform duration-300 group-hover:scale-[1.06] group-hover:drop-shadow-[0_0_14px_rgba(167,139,250,0.5)]"
        >
          <BrandMark :size="30" />
        </span>
        <!-- The wordmark is the first thing to go when the bar gets tight;
             the mark alone still identifies the product, and truncating a
             product name reads as broken rather than deliberate. -->
        <span
          class="hidden truncate text-sm font-semibold tracking-[-0.01em] text-[var(--text-primary)] min-[400px]:inline"
        >
          {{ PROJECT_NAME }}
        </span>
      </RouterLink>

      <!-- Actions -->
      <div class="flex shrink-0 items-center gap-2 sm:gap-3">
        <a
          v-if="githubAvailable"
          :href="GITHUB_URL"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 rounded-full border border-[var(--glass-border)] bg-white/[0.03] px-2.5 py-1.5 text-[11px] font-medium text-[var(--text-secondary)] backdrop-blur-md transition-colors duration-200 hover:border-[var(--glass-border-strong)] hover:text-[var(--text-primary)]"
        >
          <GithubIcon :size="14" />
          <span>{{ t('nav.github') }}</span>
        </a>

        <span
          v-else
          class="inline-flex cursor-not-allowed items-center gap-1.5 rounded-full border border-[var(--glass-border)] bg-white/[0.02] px-2.5 py-1.5 text-[11px] font-medium text-[var(--text-muted)] backdrop-blur-md"
          role="link"
          aria-disabled="true"
          :title="`${t('nav.github')}: ${GITHUB_REPO} — URL not configured yet`"
        >
          <GithubIcon :size="14" />
          <span>{{ t('nav.github') }}</span>
        </span>

        <LanguageSwitcher />
      </div>
    </nav>
  </header>
</template>
