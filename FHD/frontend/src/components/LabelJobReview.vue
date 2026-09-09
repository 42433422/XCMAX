<template>
  <section class="card" aria-label="继续标签打印任务">
    <h3>标签预览与确认</h3>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取标签任务…</p>
    <template v-if="job">
      <p>{{ job.product_name }} · {{ job.template_name }} · {{ job.copies }} 张 · {{ job.paper_width_mm }} × {{ job.paper_height_mm }} mm</p>
      <p role="status">{{ job.message }}</p>
      <iframe v-if="preview" :src="preview" title="已有标签 PDF 预览" class="label-job-preview" />
      <a v-if="preview" :href="preview" :download="`labels-${job.id}.pdf`">下载标签 PDF</a>
      <button :disabled="!canConfirm" @click="prepare">准备打印</button>
      <div v-if="confirmation" role="dialog" aria-label="确认已有标签打印">
        <p>{{ confirmation.confirm_prompt }}</p>
        <button :disabled="busy" @click="submit">确认并提交打印</button>
        <button :disabled="busy" @click="confirmation = null">取消</button>
      </div>
    </template>
    <button :disabled="busy || loading" @click="reload">刷新任务状态</button>
    <p>提交打印队列后仍需现场核对出纸。结果未知时请先检查打印队列，避免重复出纸。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { printApi, type LabelJob, type LabelConfirmation } from '@/api/print'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useModsStore } from '@/stores/mods'

const props = defineProps<{ jobId: string }>()
const mods = useModsStore()
const job = ref<LabelJob | null>(null)
const confirmation = ref<LabelConfirmation | null>(null)
const preview = ref('')
const error = ref('')
const loading = ref(false)
const busy = ref(false)
let version = 0
const canConfirm = computed(() => !busy.value && !loading.value && !!preview.value && !!job.value && ['generated', 'failed'].includes(job.value.status))
function message(e: unknown) { return e instanceof Error ? e.message : '操作失败，请重试' }
function clear() {
  job.value = null; confirmation.value = null; error.value = ''; busy.value = false
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
}
async function reload() {
  const sequence = ++version
  clear()
  loading.value = true
  try {
    if (!/^[a-f0-9]{32}$/.test(props.jobId)) throw new Error('标签任务编号无效')
    const result = await printApi.getLabelJob(props.jobId)
    if (sequence !== version) return
    if (!result.success || result.job?.id !== props.jobId) throw new Error(result.message || '标签任务不可用')
    job.value = result.job
    const response = await printApi.downloadLabelJob(props.jobId)
    const blob = await response.blob()
    if (sequence !== version) return
    if (!blob.size || blob.size > 64 * 1024 * 1024 || !blob.type.includes('application/pdf')) throw new Error('标签 PDF 响应无效')
    preview.value = URL.createObjectURL(blob)
  } catch (e) { if (sequence === version) error.value = message(e) }
  finally { if (sequence === version) loading.value = false }
}
async function prepare() {
  if (!canConfirm.value || !job.value) return
  const sequence = version
  const id = job.value.id
  busy.value = true; error.value = ''; confirmation.value = null
  try {
    const result = await printApi.confirmLabelJob(id)
    if (sequence !== version) return
    if (!result.success || result.job?.id !== id || !result.confirm_token) throw new Error(result.message || '打印确认不可用')
    confirmation.value = result
  } catch (e) { if (sequence === version) error.value = message(e) }
  finally { if (sequence === version) busy.value = false }
}
async function submit() {
  if (!job.value || !confirmation.value || !canConfirm.value) return
  const sequence = version
  const id = job.value.id
  const token = confirmation.value.confirm_token
  confirmation.value = null; busy.value = true; error.value = ''
  job.value = { ...job.value, status: 'submitting', message: '正在提交打印队列，请勿重复提交' }
  try {
    const result = await printApi.submitLabelJob(id, token)
    if (sequence !== version) return
    if (!result.success || result.job?.id !== id) throw new Error(result.message || '提交回执无效')
    job.value = result.job
  } catch (e) {
    if (sequence === version && job.value) {
      job.value = { ...job.value, status: 'outcome_unknown', message: '提交结果待确认，请先检查打印队列' }
      error.value = message(e)
    }
  } finally { if (sequence === version) busy.value = false }
}
watch(() => [props.jobId, productReadAccountEpoch.value, mods.activeModId], () => { void reload() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { version++; clear() })
</script>

<style scoped>
.label-job-preview { width: 100%; min-height: 420px; border: 1px solid var(--border-color, #ddd); }
</style>
