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
        <ul
          v-if="item.warnings.length"
          class="office-docking-review__warnings"
          aria-label="风险提示"
        >
          <li v-for="(warn, idx) in item.warnings.slice(0, 4)" :key="`${item.id}-warn-${idx}`">
            {{ warn }}
          </li>
        </ul>
        <ul
          v-if="shipmentNotes(item).length"
          class="office-docking-review__shipment-notes"
          aria-label="送货单预览"
        >
          <li v-for="(note, idx) in shipmentNotes(item).slice(0, 5)" :key="`${item.id}-note-${idx}`">
            {{ noteLabel(note) }}
          </li>
          <li v-if="shipmentNotes(item).length > 5">
            …另有 {{ shipmentNotes(item).length - 5 }} 张
          </li>
        </ul>
        <p v-if="item.error" class="office-docking-review__error">{{ item.error }}</p>

        <div v-if="item.fieldNames.length" class="office-docking-review__chips">
          <span v-for="field in item.fieldNames.slice(0, 12)" :key="field">{{ field }}</span>
        </div>

        <p v-if="previewSnippet(item)" class="office-docking-review__preview-snippet">
          {{ previewSnippet(item) }}
        </p>
        <details v-if="hasDetailedPreview(item)" class="office-docking-review__preview-details">
          <summary>{{ detailsSummary(item) }}</summary>
          <pre class="office-docking-review__preview">{{ detailedPreview(item) }}</pre>
        </details>

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
      <span class="office-docking-review__selection-hint">{{ selectionHint }}</span>
      <button type="button" class="btn" @click="$emit('close')">取消</button>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="processing || !selectedReadyCount || committing"
        @click="$emit('confirm')"
      >
        {{ confirmLabel }}
      </button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type {
  ChatOfficeDockingReviewItem,
  ShipmentEtlNotePreview,
} from '@/composables/useChatOfficeDocking'

const props = defineProps<{
  items: ChatOfficeDockingReviewItem[]
  processing: boolean
}>()

const emit = defineEmits<{
  close: []
  confirm: []
  toggleTarget: [id: string, target: 'knowledge' | 'database', enabled: boolean]
}>()

const readyCount = computed(() => props.items.filter((item) => (
  item.status === 'ready' && item.commitStatus !== 'committed'
)).length)
const committing = computed(() => props.items.some((item) => item.commitStatus === 'committing'))
const selectedReadyItems = computed(() => props.items.filter((item) => (
  item.status === 'ready'
  && item.commitStatus !== 'committed'
  && item.commitStatus !== 'committing'
  && (item.selectedKnowledge || item.selectedDatabase)
)))
const selectedReadyCount = computed(() => selectedReadyItems.value.length)

const databaseTargets = computed(() => [...new Set(
  selectedReadyItems.value
    .filter((item) => item.selectedDatabase)
    .map((item) => item.databaseTargetLabel || '业务数据库'),
)])
const hasKnowledgeTarget = computed(() => selectedReadyItems.value.some((item) => item.selectedKnowledge))

const selectionHint = computed(() => {
  if (!selectedReadyCount.value) return '请选择至少一种处理方式'
  const targets: string[] = []
  if (hasKnowledgeTarget.value) targets.push('知识库')
  targets.push(...databaseTargets.value)
  const base = `将写入：${targets.join('、')}`
  return databaseTargets.value.length ? base : `${base}；不会修改业务数据库`
})

const confirmLabel = computed(() => {
  if (committing.value) return '正在提交...'
  if (!selectedReadyCount.value) return '请选择处理方式'
  if (hasKnowledgeTarget.value && !databaseTargets.value.length) return '确认加入知识库'
  if (!hasKnowledgeTarget.value && databaseTargets.value.length === 1) {
    return `确认写入${databaseTargets.value[0]}`
  }
  return '确认按所选方式写入'
})

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

function normalizedTextPreview(item: ChatOfficeDockingReviewItem): string {
  return String(item.textPreview || '').replace(/\s+/g, ' ').trim()
}

function previewSnippet(item: ChatOfficeDockingReviewItem): string {
  const notes = shipmentNotes(item)
  if (notes.length) {
    const units = [...new Set(notes.map((n) => String(n.unit_name || '').trim()).filter(Boolean))].slice(0, 3)
    const amount = notes.reduce((sum, n) => sum + (Number(n.total_amount) || 0), 0)
    const parts = [`送货单 ${notes.length} 张`]
    if (units.length) parts.push(`购货单位 ${units.join('、')}`)
    if (amount > 0) parts.push(`合计约 ${amount}`)
    return parts.join('；')
  }
  if (item.sampleRows.length) {
    const first = item.sampleRows[0]
    const cells = Object.entries(first)
      .slice(0, 6)
      .map(([key, value]) => `${key}：${String(value ?? '')}`)
    const rowLabel = item.rowCount ? `共 ${item.rowCount} 行` : `已读取 ${item.sampleRows.length} 行样例`
    return `${rowLabel}${cells.length ? `；首行 ${cells.join('，')}` : ''}`
  }
  const text = normalizedTextPreview(item)
  if (!text) return ''
  return text.length > 220 ? `${text.slice(0, 220)}…` : text
}

function shipmentNotes(item: ChatOfficeDockingReviewItem): ShipmentEtlNotePreview[] {
  return Array.isArray(item.shipmentEtlPreview?.notes) ? item.shipmentEtlPreview!.notes! : []
}

function noteLabel(note: ShipmentEtlNotePreview): string {
  const unit = String(note.unit_name || '未命名购货单位').trim()
  const sheet = String(note.sheet_name || '').trim()
  const count = Number(note.item_count) || (Array.isArray(note.items) ? note.items.length : 0)
  const amount = Number(note.total_amount)
  const bits = [unit]
  if (sheet) bits.push(`表「${sheet}」`)
  if (count) bits.push(`${count} 行明细`)
  if (amount) bits.push(`金额 ${amount}`)
  return bits.join(' · ')
}

function detailsSummary(item: ChatOfficeDockingReviewItem): string {
  if (shipmentNotes(item).length) return '查看送货单结构化预览'
  if (item.sampleRows.length) return '查看样例数据'
  return '查看原文摘录'
}

function detailedPreview(item: ChatOfficeDockingReviewItem): string {
  const notes = shipmentNotes(item)
  if (notes.length) {
    try {
      return JSON.stringify(notes.slice(0, 3), null, 2)
    } catch {
      return ''
    }
  }
  if (item.sampleRows.length) return samplePreview(item)
  return String(item.textPreview || '').trim()
}

function hasDetailedPreview(item: ChatOfficeDockingReviewItem): boolean {
  if (shipmentNotes(item).length) return true
  if (item.sampleRows.length) return true
  return normalizedTextPreview(item).length > 220
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
.office-docking-review__hint,
.office-docking-review__selection-hint {
  color: var(--app-text-muted, #667085);
  font-size: var(--app-font-size-caption, 12px);
}

.office-docking-review__shipment-notes {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--app-text, #1f2937);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.45;
}

.office-docking-review__warnings {
  margin: 0;
  padding-left: 1.1rem;
  color: #9a6700;
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.45;
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

.office-docking-review__preview-snippet {
  margin: 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--app-muted-bg, #f6f8fb);
  color: var(--app-text, #111827);
  font-size: 12px;
  line-height: 1.55;
}

.office-docking-review__preview-details summary {
  color: var(--app-interactive, #175cd3);
  cursor: pointer;
  font-size: 12px;
}

.office-docking-review__selection-hint {
  margin-right: auto;
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
