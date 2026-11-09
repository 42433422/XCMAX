<template>
  <section class="office-docking-review" aria-label="办公文件对接审核">
    <header class="office-docking-review__head">
      <div>
        <strong>办公文件对接审核</strong>
        <span>{{ processing ? '正在解析' : `待确认 ${readyCount} 个` }}</span>
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
        :class="{ 'office-docking-review__item--error': item.status === 'error' || item.commitStatus === 'failed' }"
      >
        <div class="office-docking-review__meta">
          <div>
            <strong>{{ item.fileName }}</strong>
            <span>{{ item.kindLabel }} · {{ item.employeeLabel }}</span>
          </div>
          <span class="office-docking-review__status">{{ statusText(item) }}</span>
        </div>
        <p v-if="item.summary" class="office-docking-review__summary">{{ item.summary }}</p>
        <p v-if="item.error" class="office-docking-review__error">{{ item.error }}</p>
        <div v-if="item.status === 'ready'" class="office-docking-review__templates">
          <button
            type="button"
            class="office-docking-review__capsule"
            :aria-expanded="openId === item.id"
            @click="openId = openId === item.id ? '' : item.id"
          >
            {{ capsuleLabel(item) }}
          </button>
          <div v-if="openId === item.id" class="office-docking-review__picker" role="dialog" aria-label="可选工作表模板">
            <button type="button" @click="choose(item.id, -1)">不使用模板</button>
            <button
              v-for="(template, index) in item.worksheetTemplates || []"
              :key="template.id"
              type="button"
              @click="choose(item.id, index)"
            >
              {{ template.label }}
            </button>
            <p v-if="!(item.worksheetTemplates || []).length">暂无可选模板</p>
          </div>
        </div>
      </article>
    </div>

    <footer class="office-docking-review__foot">
      <span class="office-docking-review__selection-hint">工作表模板可选。保存后进入审批，通过后才入库。</span>
      <button type="button" class="btn" @click="$emit('close')">取消</button>
      <button type="button" class="btn btn-primary" :disabled="processing || !readyCount || committing" @click="$emit('confirm')">
        {{ committing ? '提交中' : '保存并提交入库' }}
      </button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatOfficeDockingReviewItem } from '@/composables/useChatOfficeDocking'

const props = defineProps<{
  items: ChatOfficeDockingReviewItem[]
  processing: boolean
}>()
const emit = defineEmits<{
  close: []
  confirm: []
  toggleTarget: [id: string, target: 'knowledge' | 'database', checked: boolean]
  pickTemplate: [id: string, index: number]
}>()

const openId = ref('')
const readyCount = computed(() => props.items.filter((item) => item.status === 'ready' && item.commitStatus !== 'committed').length)
const committing = computed(() => props.items.some((item) => item.commitStatus === 'committing'))

function statusText(item: ChatOfficeDockingReviewItem): string {
  if (item.status === 'running') return '识别中'
  if (item.status === 'error') return '识别失败'
  if (item.commitStatus === 'committed') return '已提交'
  if (item.commitStatus === 'failed') return '提交失败'
  if (item.commitStatus === 'committing') return '提交中'
  return '待确认'
}

function capsuleLabel(item: ChatOfficeDockingReviewItem): string {
  const templates = item.worksheetTemplates || []
  const index = item.selectedTemplateIndex ?? -1
  const chosen = templates[index]
  if (chosen?.label) return chosen.label
  if (item.commitStatus === 'committing') return '模板处理中…'
  return templates.length ? '选择模板' : '暂无可选模板'
}

function choose(id: string, index: number) {
  openId.value = ''
  emit('pickTemplate', id, index)
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
.office-docking-review__foot,
.office-docking-review__templates {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.office-docking-review__head,
.office-docking-review__meta,
.office-docking-review__foot { justify-content: space-between; }
.office-docking-review__head span,
.office-docking-review__meta span,
.office-docking-review__summary,
.office-docking-review__selection-hint {
  color: var(--app-text-muted, #667085);
  font-size: var(--app-font-size-caption, 12px);
}
.office-docking-review__icon-btn,
.office-docking-review__capsule,
.office-docking-review__picker button {
  border: 1px solid var(--app-border-color, #d7dde8);
  background: transparent;
  border-radius: 999px;
  cursor: pointer;
}
.office-docking-review__icon-btn { width: 28px; height: 28px; border: 0; }
.office-docking-review__capsule,
.office-docking-review__picker button { padding: 2px 10px; font-size: 12px; }
.office-docking-review__list { display: grid; gap: 8px; max-height: 260px; overflow: auto; }
.office-docking-review__item {
  border: 1px solid var(--app-border-color, #d7dde8);
  border-radius: 8px;
  padding: 10px;
  display: grid;
  gap: 8px;
}
.office-docking-review__item--error { border-color: #f5b5b5; }
.office-docking-review__summary,
.office-docking-review__error { margin: 0; }
.office-docking-review__error { color: #b42318; font-size: 12px; }
.office-docking-review__picker { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
