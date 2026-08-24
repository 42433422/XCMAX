<template>
  <section class="office-docking-review" aria-label="办公文件对接审核">
    <header class="office-docking-review__head">
      <div>
        <strong><i class="fa fa-files-o" aria-hidden="true"></i> 办公文件批次审核</strong>
        <span v-if="processing">正在读取 {{ items.length }} 个文件</span>
        <span v-else-if="activeItem">待审核 {{ pendingCount }} 个 · 当前 {{ activeIndex + 1 }} / {{ items.length }}</span>
        <span v-else>本批 {{ items.length }} 个文件已处理完毕</span>
      </div>
      <button type="button" class="office-docking-review__icon-btn" title="结束对接" @click="$emit('close')">
        <i class="fa fa-times" aria-hidden="true"></i>
      </button>
    </header>

    <div v-if="activeItem" class="office-docking-review__list">
      <article class="office-docking-review__item" :class="`office-docking-review__item--${activeItem.status}`">
        <div class="office-docking-review__progress" aria-label="当前对接步骤">
          <span class="is-complete">1 · AI 已阅读</span>
          <span :class="{ 'is-current': activeItem.commitStatus !== 'committing' }">2 · 等待你的决定</span>
          <span :class="{ 'is-current': activeItem.commitStatus === 'committing' }">3 · 确认后执行</span>
        </div>

        <div class="office-docking-review__meta">
          <div>
            <strong>{{ activeItem.fileName }}</strong>
            <span>{{ activeItem.kindLabel }} · {{ activeItem.employeeLabel }}</span>
          </div>
          <span class="office-docking-review__status">{{ statusText(activeItem) }}</span>
        </div>

        <p v-if="activeItem.summary" class="office-docking-review__summary">{{ activeItem.summary }}</p>
        <p v-if="activeItem.intentSummary" class="office-docking-review__intent">
          AI 判断：{{ activeItem.intentLabel }}。{{ activeItem.intentSummary }}
        </p>
        <ul v-if="activeItem.warnings.length" class="office-docking-review__warnings" aria-label="风险提示">
          <li v-for="(warn, idx) in activeItem.warnings.slice(0, 4)" :key="`${activeItem.id}-warn-${idx}`">
            {{ warn }}
          </li>
        </ul>
        <ul v-if="shipmentNotes(activeItem).length" class="office-docking-review__shipment-notes" aria-label="送货单预览">
          <li v-for="(note, idx) in shipmentNotes(activeItem).slice(0, 5)" :key="`${activeItem.id}-note-${idx}`">
            {{ noteLabel(note) }}
          </li>
          <li v-if="shipmentNotes(activeItem).length > 5">…另有 {{ shipmentNotes(activeItem).length - 5 }} 张</li>
        </ul>
        <p v-if="activeItem.error" class="office-docking-review__error">{{ activeItem.error }}</p>

        <div v-if="activeItem.fieldNames.length" class="office-docking-review__chips">
          <span v-for="field in activeItem.fieldNames.slice(0, 12)" :key="field">{{ field }}</span>
        </div>
        <p v-if="previewSnippet(activeItem)" class="office-docking-review__preview-snippet">
          {{ previewSnippet(activeItem) }}
        </p>
        <details v-if="hasDetailedPreview(activeItem)" class="office-docking-review__preview-details">
          <summary>{{ detailsSummary(activeItem) }}</summary>
          <pre class="office-docking-review__preview">{{ detailedPreview(activeItem) }}</pre>
        </details>

        <div class="office-docking-review__advice">
          <div class="office-docking-review__advice-title">
            <i class="fa fa-lightbulb-o" aria-hidden="true"></i>
            <strong>我建议这样处理，可以吗？</strong>
          </div>
          <label class="office-docking-review__target-card">
            <input
              type="checkbox"
              :checked="activeItem.selectedTemplate"
              :disabled="activeItem.status !== 'ready' || activeItem.commitStatus === 'committing' || activeItem.templateCommitStatus === 'committed'"
              @change="onToggle(activeItem.id, 'template', $event)"
            />
            <span>
              <strong>归档到模板库</strong>
              <small>{{ activeItem.templateTargetLabel }} · {{ targetStatusText(activeItem.templateCommitStatus) }}</small>
            </span>
          </label>
          <input
            class="office-docking-review__template-name"
            type="text"
            :value="activeItem.templateName"
            :disabled="!activeItem.selectedTemplate || activeItem.commitStatus === 'committing' || activeItem.templateCommitStatus === 'committed'"
            aria-label="建议模板名称"
            @input="onTemplateNameInput(activeItem.id, $event)"
          />
          <label class="office-docking-review__target-card" :class="{ 'is-disabled': !activeItem.databaseAction }" :title="activeItem.databaseDisabledReason">
            <input
              type="checkbox"
              :checked="activeItem.selectedDatabase"
              :disabled="!activeItem.excelAnalysis || !activeItem.databaseAction || activeItem.status !== 'ready' || activeItem.commitStatus === 'committing' || activeItem.databaseCommitStatus === 'committed'"
              @change="onToggle(activeItem.id, 'database', $event)"
            />
            <span>
              <strong>{{ activeItem.databaseAction ? `同步到 ${activeItem.databaseTargetLabel}` : '暂不写业务数据库' }}</strong>
              <small>{{ activeItem.databaseAction ? targetStatusText(activeItem.databaseCommitStatus) : activeItem.databaseDisabledReason }}</small>
            </span>
          </label>
        </div>
      </article>
    </div>

    <div v-else class="office-docking-review__complete">
      <i class="fa fa-check-circle-o" aria-hidden="true"></i>
      <strong>这批文件已经审核完成</strong>
      <span>已处理 {{ completedCount }} 个，跳过 {{ skippedCount }} 个</span>
    </div>

    <footer class="office-docking-review__foot">
      <span class="office-docking-review__selection-hint">{{ selectionHint }}</span>
      <button v-if="activeItem" type="button" class="btn" :disabled="processing || committing" @click="$emit('skip')">
        跳过这个文件
      </button>
      <button v-else type="button" class="btn" @click="$emit('close')">关闭</button>
      <button v-if="activeItem" type="button" class="btn btn-primary" :disabled="!canConfirm" @click="$emit('confirm')">
        {{ confirmLabel }}
      </button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatOfficeDockingReviewItem, ShipmentEtlNotePreview } from '@/composables/useChatOfficeDocking'

const props = defineProps<{
  items: ChatOfficeDockingReviewItem[]
  processing: boolean
}>()

const emit = defineEmits<{
  close: []
  confirm: []
  skip: []
  toggleTarget: [id: string, target: 'template' | 'database', enabled: boolean]
  updateTemplateName: [id: string, value: string]
}>()

const activeItem = computed(() => props.items.find(
  (item) => item.commitStatus !== 'committed' && item.commitStatus !== 'skipped',
) || null)
const activeIndex = computed(() => activeItem.value ? props.items.findIndex((item) => item.id === activeItem.value?.id) : -1)
const pendingCount = computed(() => props.items.filter(
  (item) => item.commitStatus !== 'committed' && item.commitStatus !== 'skipped',
).length)
const completedCount = computed(() => props.items.filter((item) => item.commitStatus === 'committed').length)
const skippedCount = computed(() => props.items.filter((item) => item.commitStatus === 'skipped').length)
const committing = computed(() => activeItem.value?.commitStatus === 'committing')
const hasSelectedTarget = computed(() => Boolean(activeItem.value?.selectedTemplate || activeItem.value?.selectedDatabase))
const canConfirm = computed(() => Boolean(
  activeItem.value &&
  !props.processing &&
  activeItem.value.status === 'ready' &&
  !committing.value &&
  hasSelectedTarget.value &&
  (!activeItem.value.selectedTemplate || activeItem.value.templateName.trim()),
))

const selectionHint = computed(() => {
  const item = activeItem.value
  if (!item) return '所有文件均已得到明确处理结果'
  if (props.processing) return '读取完成前不会自动归档或写入'
  if (!hasSelectedTarget.value) return '请选择模板归档或数据库目标'
  const targets = [item.selectedTemplate ? `模板库「${item.templateName || '未命名模板'}」` : '', item.selectedDatabase ? item.databaseTargetLabel : ''].filter(Boolean)
  return `确认后仅处理当前文件：${targets.join('、')}`
})

const confirmLabel = computed(() => {
  const item = activeItem.value
  if (committing.value) return '正在处理这个文件...'
  if (!item || !hasSelectedTarget.value) return '请先选择处理方式'
  if (item.selectedTemplate && !item.selectedDatabase) return '确认归档这个模板'
  if (!item.selectedTemplate && item.selectedDatabase) return `确认写入${item.databaseTargetLabel}`
  return '按当前选择处理这个文件'
})

function statusText(item: ChatOfficeDockingReviewItem): string {
  if (item.commitStatus === 'committed') return '已处理'
  if (item.commitStatus === 'partial') return '部分成功，可重试失败项'
  if (item.commitStatus === 'failed') return '处理失败，可重试'
  if (item.commitStatus === 'committing') return '正在执行你的决定'
  if (item.status === 'running') return 'AI 阅读中'
  if (item.status === 'error') return 'AI 阅读失败'
  return '等待你的决定'
}

function targetStatusText(status: ChatOfficeDockingReviewItem['commitStatus']): string {
  if (status === 'committed') return '已完成'
  if (status === 'rolled_back') return '失败后已自动回滚'
  if (status === 'failed') return '失败，可重试'
  if (status === 'committing') return '执行中'
  return '建议执行'
}

function samplePreview(item: ChatOfficeDockingReviewItem): string {
  try {
    return JSON.stringify(item.sampleRows.slice(0, 3), null, 2)
  } catch {
    return ''
  }
}

function normalizedTextPreview(item: ChatOfficeDockingReviewItem): string {
  return String(item.textPreview || '')
    .replace(/\s+/g, ' ')
    .trim()
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

function onToggle(id: string, target: 'template' | 'database', event: Event) {
  emit('toggleTarget', id, target, (event.target as HTMLInputElement).checked)
}

function onTemplateNameInput(id: string, event: Event) {
  emit('updateTemplateName', id, (event.target as HTMLInputElement).value)
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

.office-docking-review__head strong {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--app-text, #172033);
}

.office-docking-review__head strong i,
.office-docking-review__advice-title i {
  color: var(--app-interactive, #175cd3);
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
  max-height: min(60vh, 620px);
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

.office-docking-review__progress {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.office-docking-review__progress span {
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--app-text-muted, #667085);
  font-size: 11px;
}

.office-docking-review__progress .is-complete {
  border-color: rgba(23, 92, 211, 0.22);
  background: rgba(23, 92, 211, 0.08);
  color: var(--app-interactive, #175cd3);
}

.office-docking-review__progress .is-current {
  border-color: rgba(23, 92, 211, 0.38);
  color: var(--app-interactive, #175cd3);
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

.office-docking-review__advice {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(23, 92, 211, 0.2);
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(23, 92, 211, 0.055), rgba(255, 255, 255, 0.72));
}

.office-docking-review__advice-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
}

.office-docking-review__target-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 7px;
  background: var(--app-surface, #fff);
}

.office-docking-review__target-card > span {
  display: grid;
  gap: 2px;
}

.office-docking-review__target-card strong {
  color: var(--app-text, #111827);
  font-size: 12px;
}

.office-docking-review__target-card small {
  color: var(--app-text-muted, #667085);
  font-size: 11px;
}

.office-docking-review__target-card.is-disabled {
  opacity: 0.64;
}

.office-docking-review__template-name {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 7px;
  padding: 8px 10px;
  background: var(--app-surface, #fff);
  color: var(--app-text, #111827);
  font: inherit;
  font-size: 12px;
}

.office-docking-review__template-name:focus {
  outline: 2px solid rgba(23, 92, 211, 0.16);
  border-color: var(--app-interactive, #175cd3);
}

.office-docking-review__complete {
  display: grid;
  justify-items: center;
  gap: 5px;
  padding: 20px;
  border: 1px dashed rgba(23, 92, 211, 0.28);
  border-radius: 8px;
  color: var(--app-text-muted, #667085);
  font-size: 12px;
}

.office-docking-review__complete i {
  color: var(--app-interactive, #175cd3);
  font-size: 24px;
}

.office-docking-review__complete strong {
  color: var(--app-text, #111827);
  font-size: 13px;
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
