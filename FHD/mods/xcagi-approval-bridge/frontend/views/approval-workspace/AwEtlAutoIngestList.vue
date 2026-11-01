<template>
  <section class="aw-etl-auto-ingest" aria-label="数据对接自动入库">
    <div class="aw-etl-auto-ingest__head">
      <h3>数据对接自动入库</h3>
      <button type="button" :disabled="loading" @click="reload">刷新</button>
    </div>
    <p class="aw-etl-auto-ingest__hint">导入时先选择候选模板，再点「使用此模板并入库」保存并启动知识库与业务写入；此处撤回本批写入，原件与已保存模板保留。</p>
    <p v-if="loading" role="status">正在读取入库批次…</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="reload">重试</button></p>
    <p v-else-if="!loading && !items.length">暂无自动入库批次。</p>
    <ul v-if="!loading && items.length" class="aw-etl-auto-ingest__list">
      <li v-for="item in items" :key="String(item.batch_id)">
        <div>
          <strong>{{ item.file_name || item.batch_id }}</strong>
          <span> · {{ autoIngestStatusLabel(item.status) }}</span>
          <span v-if="item.detection?.target_type"> · 业务域 {{ targetLabel(item.detection.target_type) }}</span>
          <span v-if="item.business?.summary"> · 已写入 {{ item.business.summary.executed || 0 }} 行</span>
          <details><summary>查看技术回执</summary><pre>{{ JSON.stringify(item, null, 2) }}</pre></details>
        </div>
        <button
          type="button"
          :disabled="!!busyId || item.status !== 'applied'"
          @click="withdraw(String(item.batch_id))"
        >
          {{ item.status === 'withdrawn' ? '已撤回' : '撤回' }}
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { eltApi } from '@/api/elt'
import { appConfirm } from '@/utils/appDialog'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { autoIngestStatusLabel, targetLabel } from '@/views/eltCenter/eltCenterShared'

type Batch = {
  batch_id?: string
  file_name?: string
  status?: string
  detection?: { target_type?: string }
  knowledge?: { match_ref?: string }
  business?: { run_id?: string; target_type?: string; summary?: { executed?: number } }
}

const items = ref<Batch[]>([])
const loading = ref(false)
const error = ref('')
const busyId = ref('')
let active = true
let readGeneration = 0
onBeforeUnmount(() => { active = false })
watch([getAuthSessionEpoch, productReadAccountEpoch], () => {
  items.value = []; error.value = ''; busyId.value = ''
  void reload()
}, { flush: 'sync' })

async function reload() {
  const sessionCurrent = captureAuthSession()
  const generation = ++readGeneration
  const current = () => active && sessionCurrent() && generation === readGeneration
  loading.value = true
  error.value = ''
  try {
    const result = await eltApi.autoIngestBatches(50, true) as Batch[]
    if (current()) items.value = result
  } catch (err) {
    if (current()) error.value = err instanceof Error ? err.message : '读取入库批次失败'
  } finally {
    if (current()) loading.value = false
  }
}

async function withdraw(batchId: string) {
  const batch = items.value.find(item => item.batch_id === batchId)
  if (!batchId || busyId.value || batch?.status !== 'applied') return
  const sessionCurrent = captureAuthSession()
  const current = () => active && sessionCurrent()
  busyId.value = batchId
  error.value = ''
  try {
    if (!(await appConfirm(`撤回「${batch.file_name || batchId}」本批知识与业务写入？将按回执回退已写入记录，原件和已保存模板保留。`, { danger: true })) || !current()) return
    await eltApi.withdrawAutoIngestBatch(batchId)
    if (current()) await reload()
  } catch (err) {
    if (current()) error.value = err instanceof Error ? err.message : '撤回失败'
  } finally {
    if (current()) busyId.value = ''
  }
}

onMounted(reload)
</script>

<style scoped>
.aw-etl-auto-ingest { margin: 1rem 0; padding: 1rem; border: 1px solid #e5e7eb; border-radius: 8px; }
.aw-etl-auto-ingest__head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }
.aw-etl-auto-ingest__hint { color: #6b7280; font-size: 0.9rem; }
.aw-etl-auto-ingest__list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.75rem; }
.aw-etl-auto-ingest__list li { display: flex; justify-content: space-between; gap: 1rem; align-items: center; }
</style>
