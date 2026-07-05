<template>
  <section class="office-docking-review" aria-label="办公文件对接审核">
    <header class="office-docking-review__head">
      <div>
        <strong>办公文件对接审核</strong>
        <span>{{ processing ? '员工识别中' : `待确认 ${readyCount} 个` }}</span>
      </div>
      <button type="button" class="office-docking-review__icon-btn" title="关闭" @click="$emit('close')">
        <i class="fa fa-times" aria-hidden="true"></i>
      </button>
    </header>

    <div class="office-docking-review__list">
      <article
        v-for="item in items"
        :key="item.id"
        class="office-docking-review__item"
        :class="`office-docking-review__item--${item.status}`"
      >
        <div class="office-docking-review__meta">
          <div>
            <strong>{{ item.fileName }}</strong>
            <span>{{ item.kindLabel }} · {{ item.employeeLabel }}</span>
          </div>
          <span class="office-docking-review__status">{{ statusText(item) }}</span>
        </div>

        <p v-if="item.summary" class="office-docking-review__summary">{{ item.summary }}</p>
        <p v-if="item.intentSummary" class="office-docking-review__intent">
          意图：{{ item.intentLabel }}{{ item.databaseTargetLabel ? ` · ${item.databaseTargetLabel}` : '' }}，{{ item.intentSummary }}
        </p>
        <p v-if="item.error" class="office-docking-review__error">{{ item.error }}</p>

        <div v-if="item.fieldNames.length" class="office-docking-review__chips">
          <span v-for="field in item.fieldNames.slice(0, 12)" :key="field">{{ field }}</span>
        </div>

        <pre v-if="item.sampleRows.length" class="office-docking-review__preview">{{ samplePreview(item) }}</pre>
        <pre v-else-if="item.textPreview" class="office-docking-review__preview">{{ item.textPreview }}</pre>

        <div class="office-docking-review__targets">
          <label>
            <input
              type="checkbox"
              :checked="item.selectedKnowledge"
              :disabled="item.status !== 'ready' || item.commitStatus === 'committing'"
              @change="onToggle(item.id, 'knowledge', $event)"
            >
            入知识库
          </label>
          <label :class="{ muted: !item.databaseAction }" :title="item.databaseDisabledReason">
            <input
              type="checkbox"
              :checked="item.selectedDatabase"
              :disabled="!item.excelAnalysis || !item.databaseAction || item.status !== 'ready' || item.commitStatus === 'committing'"
              @change="onToggle(item.id, 'database', $event)"
            >
            入数据库{{ item.databaseTargetLabel ? `（${item.databaseTargetLabel}）` : '' }}
          </label>
        </div>
        <p v-if="item.status === 'ready' && !item.databaseAction && item.databaseDisabledReason" class="office-docking-review__hint">
          {{ item.databaseDisabledReason }}
        </p>
      </article>
    </div>

    <footer class="office-docking-review__foot">
      <button type="button" class="btn" @click="$emit('close')">取消</button>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="processing || !readyCount || committing"
        @click="$emit('confirm')"
      >
        {{ committing ? '提交中...' : '确认入库' }}
      </button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatOfficeDockingReviewItem } from '@/composables/useChatOfficeDocking'

const props = defineProps<{
  items: ChatOfficeDockingReviewItem[]
  processing: boolean
}>()

const emit = defineEmits<{
  close: []
  confirm: []
  toggleTarget: [id: string, target: 'knowledge' | 'database', enabled: boolean]
}>()

const readyCount = computed(() => props.items.filter((item) => item.status === 'ready').length)
const committing = computed(() => props.items.some((item) => item.commitStatus === 'committing'))

function statusText(item: ChatOfficeDockingReviewItem): string {
  if (item.commitStatus === 'committed') return '已提交'
  if (item.commitStatus === 'failed') return '提交失败'
  if (item.commitStatus === 'committing') return '提交中'
  if (item.status === 'running') return '识别中'
  if (item.status === 'error') return '识别失败'
  return '待确认'
}

function samplePreview(item: ChatOfficeDockingReviewItem): string {
  try {
    return JSON.stringify(item.sampleRows.slice(0, 3), null, 2)
  } catch {
    return ''
  }
}

function onToggle(id: string, target: 'knowledge' | 'database', event: Event) {
  emit('toggleTarget', id, target, (event.target as HTMLInputElement).checked)
}
</script>

<style scoped>
.office-docking-review {
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 8px;
  background: var(--app-surface, #fff);
  padding: 10px;
  display: grid;
  gap: 10px;
}

.office-docking-review__head,
.office-docking-review__meta,
.office-docking-review__targets,
.office-docking-review__foot {
  display: flex;
  align-items: center;
  gap: 10px;
}

.office-docking-review__head,
.office-docking-review__meta,
.office-docking-review__foot {
  justify-content: space-between;
}

.office-docking-review__head span,
.office-docking-review__meta span,
.office-docking-review__summary,
.office-docking-review__intent,
.office-docking-review__hint {
  color: var(--app-text-muted, #667085);
  font-size: var(--app-font-size-caption, 12px);
}

.office-docking-review__icon-btn {
  border: 0;
  background: transparent;
  color: var(--app-text-muted, #667085);
  cursor: pointer;
  width: 28px;
  height: 28px;
}

.office-docking-review__list {
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}

.office-docking-review__item {
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 8px;
  padding: 10px;
  display: grid;
  gap: 8px;
}

.office-docking-review__item--error {
  border-color: #f5b5b5;
}

.office-docking-review__status {
  white-space: nowrap;
}

.office-docking-review__summary,
.office-docking-review__intent,
.office-docking-review__hint,
.office-docking-review__error {
  margin: 0;
}

.office-docking-review__error {
  color: #b42318;
  font-size: var(--app-font-size-caption, 12px);
}

.office-docking-review__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.office-docking-review__chips span {
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--app-text-muted, #667085);
}

.office-docking-review__preview {
  margin: 0;
  max-height: 96px;
  overflow: auto;
  padding: 8px;
  border-radius: 6px;
  background: var(--app-muted-bg, #f6f8fb);
  font-size: 12px;
  white-space: pre-wrap;
}

.office-docking-review__targets label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--app-text, #111827);
}

.office-docking-review__targets .muted {
  color: var(--app-text-muted, #667085);
}
</style>
