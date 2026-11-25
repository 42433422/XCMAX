<template>
  <details class="memory-temporal-review" @toggle="onToggle">
    <summary>关系与时间查询</summary>
    <form @submit.prevent="runReview">
      <label>查询实体或关键词<input v-model.trim="query" required maxlength="2000" type="text" /></label>
      <label>关系跳数
        <select v-model.number="maxHops">
          <option :value="0">仅关键词</option>
          <option :value="1">直接关系</option>
          <option :value="2">两跳</option>
          <option :value="3">三跳</option>
        </select>
      </label>
      <label>截至记录时间（可选，含时区）
        <input v-model.trim="asOf" maxlength="64" placeholder="2026-11-24T08:00:00+08:00" />
      </label>
      <label>业务有效时间（可选，含时区）
        <input v-model.trim="effectiveAt" maxlength="64" placeholder="2026-11-24T08:00:00+08:00" />
      </label>
      <p class="review-hint">记录时间表示当时保存的版本，不等于业务事实的生效时间。此面板只读，不增加记忆权重。</p>
      <button type="submit" :disabled="loading || !query">{{ loading ? '查询中' : '查询' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="result" aria-live="polite">
      <p v-if="result.historical_review_only">历史或业务时间查询结果，仅供审核，不进入 AI 执行上下文。</p>
      <p v-if="result.coverage_complete === false">本次覆盖不完整，不能将未返回的内容视为不存在。时间信息不足：{{ result.temporal_unavailable_count || 0 }}；并发修订过滤：{{ result.revalidation_dropped || 0 }}。</p>
      <p v-if="result.relation_conflict_count">发现 {{ result.relation_conflict_count }} 组单值关系冲突，已从召回中隔离，请在当前记忆列表纠正或撤销。</p>
      <ul v-if="result.relation_conflicts?.length" class="review-results">
        <li v-for="(conflict, index) in result.relation_conflicts" :key="index">
          {{ conflict.predicate }} · {{ conflict.memory_ids }}
        </li>
      </ul>
      <p v-if="!result.memories.length">没有符合条件的可用记录。</p>
      <ul class="review-results">
        <li v-for="memory in result.memories" :key="memory.memory_id">
          <strong>{{ memory.statement }}</strong>
          <small>{{ memory.scope }} · 修订 {{ memory.revision || '未知' }} · {{ memory.memory_id }}</small>
          <small v-if="memory.recorded_from">记录区间：{{ memory.recorded_from }} 至 {{ memory.recorded_until || '当前' }}</small>
          <ol v-if="memory.relation_path?.length">
            <li v-for="(step, index) in memory.relation_path" :key="index">
              {{ step.statement }}（{{ step.identity_basis === 'recorded_id' ? '记录ID关联' : '名称候选关联' }}；修订 {{ step.revision }}）
            </li>
          </ol>
        </li>
      </ul>
    </section>
  </details>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { knowledgeBaseApi, type PersyMemoryQueryResponse, type PersyMemoryRecord } from '@/api/knowledgeBase'

const props = defineProps<{ datasetId: string; refreshKey: PersyMemoryRecord[] }>()
const query = ref('')
const maxHops = ref(2)
const asOf = ref('')
const effectiveAt = ref('')
const loading = ref(false)
const error = ref('')
const result = ref<PersyMemoryQueryResponse | null>(null)
let generation = 0

function clearReview(): void {
  generation++
  loading.value = false
  result.value = null
  error.value = ''
}
watch(() => [props.datasetId, props.refreshKey], clearReview)
onBeforeUnmount(clearReview)

function onToggle(event: Event): void {
  if (!(event.currentTarget as HTMLDetailsElement).open) clearReview()
}

async function runReview(): Promise<void> {
  if (!query.value || loading.value) return
  clearReview()
  const request = generation
  loading.value = true
  try {
    const response = await knowledgeBaseApi.queryMemories({
      datasetId: props.datasetId,
      query: query.value,
      maxHops: maxHops.value,
      ...(asOf.value ? { asOf: asOf.value } : {}),
      ...(effectiveAt.value ? { effectiveAt: effectiveAt.value } : {}),
      reinforce: false,
    })
    if (request !== generation) return
    if (!response.success) throw new Error(response.message || '查询失败')
    result.value = response
  } catch (cause) {
    if (request === generation) error.value = cause instanceof Error ? cause.message : '查询失败'
  } finally {
    if (request === generation) loading.value = false
  }
}
</script>

<style scoped>
.memory-temporal-review { margin: 12px 0; padding: 12px; border: 1px solid var(--border-color, #d7ded9); border-radius: 8px; }
.memory-temporal-review summary { cursor: pointer; font-weight: 600; }
form { display: grid; gap: 8px; margin: 12px 0; }
label { display: grid; gap: 4px; font-size: 12px; }
input, select { min-width: 0; padding: 6px; color: inherit; background: transparent; border: 1px solid var(--border-color, #d7ded9); border-radius: 4px; }
.review-hint, small { display: block; font-size: 11px; opacity: .75; overflow-wrap: anywhere; }
.review-results { padding-left: 18px; }
.review-results li { margin: 6px 0; overflow-wrap: anywhere; }
</style>
