<template>
  <section class="aw-etl-auto-ingest" aria-label="数据对接自动入库">
    <div class="aw-etl-auto-ingest__head">
      <h3>数据对接自动入库</h3>
      <button type="button" :disabled="loading" @click="reload">刷新</button>
    </div>
    <p class="aw-etl-auto-ingest__hint">选模板保存后自动写入知识库与对应业务域；此处可撤回整批。</p>
    <p v-if="loading" role="status">正在读取入库批次…</p>
    <p v-else-if="error" role="alert">{{ error }} <button type="button" @click="reload">重试</button></p>
    <p v-else-if="!items.length">暂无自动入库批次。</p>
    <ul v-else class="aw-etl-auto-ingest__list">
      <li v-for="item in items" :key="String(item.batch_id)">
        <div>
          <strong>{{ item.file_name || item.batch_id }}</strong>
          <span> · {{ item.status }}</span>
          <span v-if="item.detection?.target_type"> · 业务域 {{ item.detection.target_type }}</span>
          <span v-if="item.knowledge?.match_ref"> · KB {{ item.knowledge.match_ref }}</span>
          <span v-if="item.business?.run_id"> · ETL {{ item.business.run_id }}</span>
        </div>
        <button
          type="button"
          :disabled="busyId === item.batch_id || item.status === 'withdrawn'"
          @click="withdraw(String(item.batch_id))"
        >
          {{ item.status === 'withdrawn' ? '已撤回' : '撤回' }}
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { eltApi } from '@/api/elt'

type Batch = {
  batch_id?: string
  file_name?: string
  status?: string
  detection?: { target_type?: string }
  knowledge?: { match_ref?: string }
  business?: { run_id?: string; target_type?: string }
}

const items = ref<Batch[]>([])
const loading = ref(false)
const error = ref('')
const busyId = ref('')

async function reload() {
  loading.value = true
  error.value = ''
  try {
    items.value = (await eltApi.autoIngestBatches(50, true)) as Batch[]
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取入库批次失败'
  } finally {
    loading.value = false
  }
}

async function withdraw(batchId: string) {
  if (!batchId || busyId.value) return
  busyId.value = batchId
  error.value = ''
  try {
    await eltApi.withdrawAutoIngestBatch(batchId)
    await reload()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '撤回失败'
  } finally {
    busyId.value = ''
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
