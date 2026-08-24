<template>
  <section
    class="office-reading-card"
    :class="[`is-${progress.phase}`, { 'is-compact': compact }]"
    aria-live="polite"
    data-testid="office-docking-progress"
  >
    <div class="office-reading-card__header">
      <span class="office-reading-card__icon" aria-hidden="true">
        <i v-if="isActive" class="fa fa-circle-o-notch fa-spin"></i>
        <i v-else-if="progress.phase === 'completed'" class="fa fa-check"></i>
        <i v-else class="fa fa-stop"></i>
      </span>
      <div class="office-reading-card__heading">
        <strong>{{ title }}</strong>
        <span>{{ progress.completed }}/{{ progress.total }} · {{ elapsedText }}</span>
      </div>
      <button v-if="canCancel" type="button" class="office-reading-card__cancel" @click="$emit('cancel')">
        停止分析
      </button>
      <span v-else-if="progress.phase === 'stopping'" class="office-reading-card__stopping">正在停止…</span>
    </div>

    <div
      class="office-reading-card__track"
      role="progressbar"
      :aria-valuenow="progress.percent"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="`资料分析进度 ${progress.percent}%`"
    >
      <span :style="{ width: `${progress.percent}%` }"></span>
    </div>

    <div v-if="isActive && progress.currentFile" class="office-reading-card__current">
      <span>{{ currentStage }}</span>
      <strong :title="progress.currentFile">{{ progress.currentFile }}</strong>
    </div>

    <div class="office-reading-card__stats" aria-label="分析结果统计">
      <span class="is-success"><i class="fa fa-check-circle" aria-hidden="true"></i> 成功 {{ progress.success }}</span>
      <span class="is-failed"><i class="fa fa-exclamation-circle" aria-hidden="true"></i> 失败 {{ progress.failed }}</span>
      <span class="is-ignored"><i class="fa fa-minus-circle" aria-hidden="true"></i> 跳过 {{ progress.ignored.length }}</span>
    </div>

    <details v-if="progress.ignored.length" class="office-reading-card__ignored">
      <summary>查看跳过的文件和原因</summary>
      <ul>
        <li v-for="item in progress.ignored" :key="`${item.fileName}-${item.reason}`">
          <strong :title="item.fileName">{{ item.fileName }}</strong>
          <span>{{ item.reason }}</span>
        </li>
      </ul>
    </details>

    <details v-if="progress.failures.length" class="office-reading-card__failures" open>
      <summary>读取失败详情</summary>
      <ul>
        <li v-for="item in progress.failures" :key="`${item.fileName}-${item.reason}`">
          <strong :title="item.fileName">{{ item.fileName }}</strong>
          <span>{{ item.reason }}</span>
        </li>
      </ul>
    </details>

    <p class="office-reading-card__safety">
      <i class="fa fa-shield" aria-hidden="true"></i>
      当前只做内容指纹、结构与语义预演，不会归档模板，也不会写入数据库；知识库同样不会写入
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatOfficeDockingProgress } from '@/composables/useChatOfficeDocking'

const props = withDefaults(
  defineProps<{
    progress: ChatOfficeDockingProgress
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

defineEmits<{
  cancel: []
}>()

const activePhases = ['inventory', 'reading', 'reasoning', 'planning']
const isActive = computed(() => activePhases.includes(props.progress.phase) || props.progress.phase === 'stopping')
const canCancel = computed(() => activePhases.includes(props.progress.phase))

const currentStage = computed(() => {
  if (props.progress.phase === 'inventory') return '内容指纹与去重'
  if (props.progress.phase === 'reasoning') return '结构与语义分析'
  if (props.progress.phase === 'planning') return '生成三路处理方案'
  return `正在分析第 ${props.progress.currentIndex} 个`
})

const title = computed(() => {
  if (props.progress.phase === 'inventory') return `正在清点${props.progress.sourceLabel}`
  if (props.progress.phase === 'reading') return `正在阅读${props.progress.sourceLabel}`
  if (props.progress.phase === 'reasoning') return '正在分析工作表与业务关系'
  if (props.progress.phase === 'planning') return '正在形成数据库、知识库和模板方案'
  if (props.progress.phase === 'stopping') return '正在安全停止分析'
  if (props.progress.phase === 'cancelled') return '分析已停止'
  return props.progress.failed ? '分析完成，部分文件需要处理' : '全部分析完成'
})

const elapsedText = computed(() => {
  const seconds = Math.max(0, props.progress.elapsedSeconds)
  if (seconds < 60) return `用时 ${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  return `用时 ${minutes} 分 ${seconds % 60} 秒`
})
</script>

<style scoped>
.office-reading-card {
  width: min(760px, 100%);
  flex-shrink: 0;
  padding: 18px;
  border: 1px solid rgba(45, 123, 214, 0.2);
  border-radius: 16px;
  background: radial-gradient(circle at 100% 0, rgba(95, 166, 235, 0.14), transparent 38%), rgba(255, 255, 255, 0.92);
  box-shadow: 0 12px 30px rgba(31, 70, 116, 0.09);
  color: #24364b;
}

.office-reading-card.is-compact {
  width: auto;
  margin: 12px;
  padding: 14px;
  border-radius: 13px;
  box-shadow: 0 6px 18px rgba(31, 70, 116, 0.08);
}

.office-reading-card__header {
  display: flex;
  align-items: center;
  gap: 11px;
}

.office-reading-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 12px;
  color: #176bc0;
  background: #e9f4ff;
}

.is-completed .office-reading-card__icon {
  color: #147a55;
  background: #e8f7f1;
}

.is-cancelled .office-reading-card__icon {
  color: #68778a;
  background: #eef2f6;
}

.office-reading-card__heading {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.office-reading-card__heading strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 650;
  color: #1d3550;
}

.office-reading-card__heading span {
  font-size: 12px;
  color: #718197;
}

.office-reading-card__cancel {
  flex: 0 0 auto;
  border: 1px solid #ccd9e8;
  border-radius: 9px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.86);
  color: #49627d;
  font-size: 12px;
  cursor: pointer;
}

.office-reading-card__cancel:hover {
  color: #1b5f9f;
  border-color: #75a9db;
  background: #f4f9ff;
}

.office-reading-card__stopping {
  color: #68778a;
  font-size: 12px;
}

.office-reading-card__track {
  height: 7px;
  margin-top: 15px;
  overflow: hidden;
  border-radius: 99px;
  background: #e8eef5;
}

.office-reading-card__track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #176bc0, #5fa6eb);
  transition: width 260ms ease;
}

.office-reading-card__current {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-top: 13px;
  padding: 9px 11px;
  border-radius: 10px;
  background: rgba(232, 243, 255, 0.72);
  font-size: 12px;
}

.office-reading-card__current span {
  color: #5e7188;
}

.office-reading-card__current strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: #244f7c;
}

.office-reading-card__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.office-reading-card__stats span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 99px;
  background: #f2f5f8;
  color: #5e6c7d;
  font-size: 12px;
}

.office-reading-card__stats .is-success {
  color: #147a55;
  background: #eaf7f2;
}
.office-reading-card__stats .is-failed {
  color: #b44949;
  background: #fff0f0;
}
.office-reading-card__stats .is-ignored {
  color: #667386;
  background: #eef2f6;
}

.office-reading-card__ignored {
  margin-top: 10px;
  font-size: 12px;
  color: #62748a;
}

.office-reading-card__failures {
  margin-top: 10px;
  font-size: 12px;
  color: #8c4545;
}

.office-reading-card__ignored summary {
  width: fit-content;
  cursor: pointer;
  color: #376eaa;
}

.office-reading-card__failures summary {
  width: fit-content;
  cursor: pointer;
  color: #a84646;
}

.office-reading-card__ignored ul {
  max-height: 120px;
  margin: 8px 0 0;
  padding: 8px 10px;
  overflow: auto;
  list-style: none;
  border-radius: 9px;
  background: #f7f9fc;
}

.office-reading-card__failures ul {
  max-height: 140px;
  margin: 8px 0 0;
  padding: 8px 10px;
  overflow: auto;
  list-style: none;
  border-radius: 9px;
  background: #fff5f5;
}

.office-reading-card__ignored li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 4px 0;
}

.office-reading-card__failures li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: 8px;
  padding: 4px 0;
}

.office-reading-card__ignored li strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.office-reading-card__failures li strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.office-reading-card__safety {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 12px 0 0;
  color: #6d7b8d;
  font-size: 12px;
}

.is-compact .office-reading-card__safety,
.is-compact .office-reading-card__ignored,
.is-compact .office-reading-card__failures {
  margin-top: 9px;
}

@media (max-width: 720px) {
  .office-reading-card__current,
  .office-reading-card__ignored li,
  .office-reading-card__failures li {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>
