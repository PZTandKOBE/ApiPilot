<script setup lang="ts">
import { MagicStick, UploadFilled } from '@element-plus/icons-vue'
import { ElButton, ElIcon, ElInput, ElUpload, type UploadFile } from 'element-plus'
import { computed, ref } from 'vue'

import { useI18n } from '@/i18n'
import { useAgentStore } from '@/stores/agent'

/**
 * Where a specification enters the lab.
 *
 * Three routes in — file, clipboard, built-in demo — and no parsing: the
 * component's whole job is to get text and a filename, then hand them to the
 * store. Syntax detection, format validation and every error message live
 * behind the service boundary, which is why nothing here mentions OpenAPI
 * versions or tries to guess at a half-written document.
 *
 * Deliberately no extension filter on the drop zone. A `.txt` holding valid
 * JSON is a legitimate input, and the parser produces a far better message for
 * a genuinely wrong file than "unsupported extension" would.
 */
const { t } = useI18n()
const store = useAgentStore()

const pasted = ref('')
const uploadRef = ref<InstanceType<typeof ElUpload> | null>(null)

const busy = computed(() => store.loading)

const onFileChange = async (file: UploadFile): Promise<void> => {
  const raw = file.raw
  if (raw === undefined) return

  await store.loadSpec({
    filename: raw.name,
    content: await raw.text(),
    source: 'upload',
  })

  // Element Plus keeps the selection internally; clearing it lets the same
  // file be re-picked after it has been edited on disk.
  uploadRef.value?.clearFiles()
}

const onPaste = async (): Promise<void> => {
  if (pasted.value.trim() === '') return

  await store.loadSpec({
    filename: 'pasted-document',
    content: pasted.value,
    source: 'paste',
  })
}

const onDemo = async (): Promise<void> => {
  await store.loadDemoSpec()
}
</script>

<template>
  <section class="console-panel p-4 sm:p-5">
    <h2 class="text-[14px] font-semibold text-[var(--console-text)]">
      {{ t('console.aiTest.upload.heading') }}
    </h2>
    <p class="mt-1 text-[12px] text-[var(--console-text-muted)]">
      {{ t('console.aiTest.upload.supported') }}
    </p>

    <!-- Drop zone -->
    <ElUpload
      ref="uploadRef"
      class="mt-4 block"
      drag
      :auto-upload="false"
      :show-file-list="false"
      :disabled="busy"
      @change="onFileChange"
    >
      <div class="flex flex-col items-center gap-2.5 px-4 py-7">
        <ElIcon :size="28" class="text-[var(--console-text-muted)]">
          <UploadFilled />
        </ElIcon>
        <p class="text-[13px] font-medium text-[var(--console-text-dim)]">
          {{ t('console.aiTest.upload.dropTitle') }}
        </p>
        <p class="text-[11.5px] text-[var(--console-text-muted)]">
          {{ t('console.aiTest.upload.dropHint') }}
        </p>
        <ElButton size="small" :disabled="busy">
          {{ t('console.aiTest.upload.selectFile') }}
        </ElButton>
      </div>
    </ElUpload>

    <!-- Paste -->
    <p class="my-4 flex items-center gap-3">
      <span class="h-px flex-1 bg-[var(--console-border)]" />
      <span class="text-[11px] text-[var(--console-text-muted)]">
        {{ t('console.aiTest.upload.divider') }}
      </span>
      <span class="h-px flex-1 bg-[var(--console-border)]" />
    </p>

    <label class="flex flex-col gap-1.5">
      <span class="console-label">{{ t('console.aiTest.upload.pasteTitle') }}</span>
      <ElInput
        v-model="pasted"
        type="textarea"
        :rows="7"
        resize="vertical"
        class="console-code-input"
        :placeholder="t('console.aiTest.upload.pastePlaceholder')"
        spellcheck="false"
      />
    </label>

    <div class="mt-3 flex flex-wrap items-center gap-2">
      <ElButton
        type="primary"
        :loading="busy"
        :disabled="pasted.trim() === ''"
        @click="onPaste"
      >
        {{ t('console.aiTest.upload.pasteAction') }}
      </ElButton>

      <ElButton :disabled="busy" @click="onDemo">
        <ElIcon class="mr-1.5"><MagicStick /></ElIcon>
        {{ t('console.aiTest.upload.useDemo') }}
      </ElButton>
    </div>
  </section>
</template>

<style scoped>
/* Element Plus draws its own dashed drop area; the console's surfaces are
   flatter, so only the border and radius are kept. */
:deep(.el-upload-dragger) {
  padding: 0;
  border: 1px dashed var(--console-border);
  border-radius: 10px;
  background-color: transparent;
  transition: border-color 150ms ease, background-color 150ms ease;
}

:deep(.el-upload-dragger:hover),
:deep(.el-upload-dragger.is-dragover) {
  border-color: var(--console-border-strong);
  background-color: var(--console-surface-hover);
}
</style>
