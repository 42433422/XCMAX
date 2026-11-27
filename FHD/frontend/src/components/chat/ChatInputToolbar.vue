<template>
  <div class="input-toolbar" @mousedown.stop>
    <button
      class="toolbar-btn composer-control composer-icon-button"
      type="button"
      data-tutorial-id="toolbar-excel-analyze"
      :aria-label="`${$t(attachmentUploading ? 'shell.uploadingAttachment' : 'chat.uploadAttachment')}${multimodalPendingCount ? ` (${multimodalPendingCount})` : ''}`"
      :title="$t('chat.uploadTitle')"
      :disabled="attachmentUploading"
      @click="triggerUpload"
    >
      <ElIcon :class="{ 'is-loading': attachmentUploading }" aria-hidden="true">
        <Loading v-if="attachmentUploading" />
        <Paperclip v-else />
      </ElIcon>
    </button>
    <button
      class="toolbar-btn composer-control composer-icon-button"
      type="button"
      data-tutorial-id="toolbar-office-docking"
      :aria-label="$t(officeDockingProcessing ? 'chat.officeDockingBusy' : 'chat.officeDocking')"
      :title="$t('chat.officeDockingTitle')"
      :disabled="officeDockingProcessing"
      @click="emit('trigger-office-docking')"
    >
      <ElIcon :class="{ 'is-loading': officeDockingProcessing }" aria-hidden="true">
        <Loading v-if="officeDockingProcessing" />
        <Document v-else />
      </ElIcon>
    </button>
    <div class="approval-mode" data-testid="approval-mode-toggle">
      <button
        class="toolbar-btn composer-control approval-mode__toggle"
        id="approvalModeBtn"
        type="button"
        :title="$t('chat.approvalModeTitle')"
        :aria-pressed="approvalMode.state.enabled"
        :class="{ 'is-active': approvalMode.state.enabled }"
        @click="toggleApproval"
      >
        <CircleCheck aria-hidden="true" /> {{ $t('chat.approvalMode') }}
      </button>
      <div
        v-if="approvalMode.state.enabled"
        class="approval-mode__choices"
        role="radiogroup"
        :aria-label="$t('chat.approvalMode')"
      >
        <button
          type="button"
          class="approval-mode__choice"
          :class="{ 'is-active': approvalMode.state.mode === 'manual' }"
          :aria-pressed="approvalMode.state.mode === 'manual'"
          @click="approvalMode.setMode('manual')"
        >
          {{ $t('chat.approvalManual') }}
        </button>
        <button
          type="button"
          class="approval-mode__choice"
          :class="{ 'is-active': approvalMode.state.mode === 'auto' }"
          :aria-pressed="approvalMode.state.mode === 'auto'"
          @click="approvalMode.setMode('auto')"
        >
          {{ $t('chat.approvalAuto') }}
        </button>
      </div>
    </div>
    <input
      ref="fileInputRef"
      type="file"
      :accept="`${intakeAcceptAttribute('context', 'analysis')},${CHAT_WORD_ATTACHMENT_SUFFIX}`"
      multiple
      style="display: none"
      @change="onFileChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElIcon } from 'element-plus'
import { CircleCheck, Document, Loading, Paperclip } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useApprovalMode } from '@/composables/useApprovalMode'
import { CHAT_WORD_ATTACHMENT_SUFFIX, intakeAcceptAttribute } from '@/utils/documentIntake'

useI18n()

const approvalMode = useApprovalMode()

defineProps<{
  attachmentUploading: boolean
  multimodalPendingCount: number
  /** @deprecated kept optional for older callers; chat toolbar no longer binds WeChat star refresh */
  autoRefreshStarredWechat?: boolean
  officeDockingProcessing?: boolean
}>()

const emit = defineEmits<{
  'trigger-office-docking': []
  'attachment-file-change': [event: Event]
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)

function toggleApproval() {
  approvalMode.setEnabled(!approvalMode.state.enabled)
}

function triggerUpload() {
  fileInputRef.value?.click()
}

function onFileChange(event: Event) {
  emit('attachment-file-change', event)
}
</script>

<style scoped>
.input-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }

.toolbar-toggle-text {
  /* Avoid fractional inherited leading in these centered flex text items. */
  line-height: 1;
}

.approval-mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.approval-mode__toggle.is-active {
  color: var(--xc-color-primary);
  background: var(--xc-color-primary-soft);
}

.approval-mode__choices {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding-left: 2px;
  border-left: 2px solid var(--xc-color-primary, #0d47a1);
}

.approval-mode__choice {
  background: transparent;
  border: none;
  padding: 2px 8px;
  font-size: var(--app-font-size-caption, 12px);
  color: var(--app-text-muted, #667085);
  cursor: pointer;
  border-radius: 2px;
}

.approval-mode__choice.is-active {
  color: var(--xc-color-primary, #0d47a1);
  background: rgba(13, 71, 161, 0.08);
}

@media (max-width: 768px) {
  .approval-mode__choice { min-height: 44px; }
}
</style>
