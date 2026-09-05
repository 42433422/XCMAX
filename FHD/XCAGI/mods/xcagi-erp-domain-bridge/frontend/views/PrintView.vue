<template>
  <div id="view-print" class="page-view">
    <div class="page-content">
      <div class="page-header"><h2>标签输出与打印</h2></div>
      <div class="card">
        <div class="card-header">1. 选择产品与标签模板</div>
        <p v-if="loadError" role="alert">{{ loadError }} <button @click="loadOptions">重新加载</button></p>
        <div class="form-group">
          <label for="label-search">查找业务产品</label>
          <input id="label-search" v-model="productKeyword" placeholder="输入产品名称或型号" :disabled="busy || productsLoading" @keyup.enter="loadProducts(true)">
          <button :disabled="busy || productsLoading" @click="loadProducts(true)">搜索产品</button>
          <label for="label-product">选择业务产品</label>
          <select id="label-product" v-model="productId" :disabled="busy">
            <option value="">请选择产品</option>
            <option v-for="product in products" :key="product.id" :value="String(product.id)">{{ product.name }} · {{ product.model_number || '无型号' }}{{ product.specification ? ` · ${product.specification}` : '' }} （编号 {{ product.id }}）</option>
          </select>
          <p>已显示 {{ products.length }} / {{ productsTotal }} 个产品，可按名称或型号搜索。</p>
          <button v-if="products.length < productsTotal" :disabled="busy || productsLoading" @click="loadProducts(false)">加载更多产品</button>
        </div>
        <div class="form-group">
          <label for="label-template">标签模板</label>
          <select id="label-template" v-model="templateId" :disabled="busy">
            <option value="">请选择已保存的标签模板</option>
            <option v-for="template in templates" :key="template.id" :value="template.id">{{ template.name }}</option>
          </select>
          <p>使用所选模板的字段与位置。动态字段需绑定产品名称、型号、规格、单价等真实产品数据。</p>
          <a :href="resolveErpPagePath('/label-editor?returnTo=print')">创建标签模板</a>
        </div>
        <p v-if="templateError" role="alert">{{ templateError }} <button @click="loadTemplate">重试模板加载</button></p>
        <div class="form-group">
          <label for="label-copies">标签张数（每页一张）</label>
          <input id="label-copies" v-model.number="copies" type="number" min="1" max="100" step="1" :disabled="busy">
        </div>
        <div class="form-group">
          <label for="label-width">纸张宽度（mm）</label>
          <input id="label-width" v-model.number="widthMm" type="number" min="10" max="500" step="0.1" :disabled="busy || paperLocked" @input="updateHeight">
          <label for="label-height">纸张高度（mm）</label>
          <input id="label-height" :value="heightMm" type="number" readonly>
          <p>{{ paperLocked ? '沿用模板保存的纸张尺寸。' : '模板未指定纸张尺寸，请输入实际标签宽度；高度按模板比例计算。' }}打印前请在打印机驱动中选择相同纸张规格。</p>
        </div>
        <button class="btn btn-primary" :disabled="!canGenerate" @click="generate">{{ busy ? '处理中…' : '生成标签 PDF' }}</button>
        <p v-if="error" role="alert">{{ error }}</p>
      </div>
      <div v-if="job" class="card">
        <div class="card-header">2. 预览与下载</div>
        <p>{{ job.product_name }} · {{ job.template_name }} · {{ job.copies }} 张 · {{ job.paper_width_mm }} × {{ job.paper_height_mm }} mm</p>
        <p role="status">{{ job.message }}</p>
        <p v-if="stale">选择已变更，重新生成后才能打印当前选择。</p>
        <iframe v-if="previewUrl" :src="previewUrl" title="生成的标签 PDF 预览" class="label-pdf-preview" />
        <p v-else>预览尚未载入，可重试加载文件。</p>
        <button :disabled="busy" @click="loadPreview">重新加载预览</button>
        <a v-if="previewUrl" :href="previewUrl" :download="`labels-${job.id}.pdf`">下载标签 PDF</a>
        <div class="card-header">3. 确认提交打印</div>
        <p>提交打印队列后仍需现场核对出纸结果。Windows 需要已安装的 Adobe PDF 打印程序；也可下载后手动打印。</p>
        <button :disabled="!canConfirm" @click="preparePrint">{{ job.status === 'failed' ? '重新确认打印' : '准备打印' }}</button>
        <button v-if="['submitting', 'outcome_unknown'].includes(job.status)" :disabled="busy" @click="refreshStatus">刷新任务状态</button>
        <div v-if="confirmation" role="dialog" aria-label="确认打印标签">
          <p>{{ confirmation.confirm_prompt }}</p>
          <button :disabled="busy" @click="submitPrint">确认并提交打印</button>
          <button :disabled="busy" @click="confirmation = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import printApi, { type LabelConfirmation, type LabelJob } from '@/api/print'
import templatePreviewApi from '@/api/templatePreview'
import { resolveErpPagePath } from '@/utils/erpPagePaths'

type Template = { id: string; name: string; category?: string; preview_data?: Record<string, unknown> }
const products = ref<{ id: number; name: string; model_number?: string; specification?: string }[]>([])
const templates = ref<Template[]>([])
const productId = ref('')
const productKeyword = ref('')
const appliedProductKeyword = ref('')
const productsTotal = ref(0)
const productsPage = ref(0)
const productsLoading = ref(false)
const templateId = ref('')
const copies = ref(1)
const widthMm = ref(90)
const heightMm = ref(60)
const ratio = ref(1.5)
const paperLocked = ref(false)
const templateReady = ref(false)
const busy = ref(false)
const loadError = ref('')
const templateError = ref('')
const error = ref('')
const job = ref<LabelJob | null>(null)
const confirmation = ref<LabelConfirmation | null>(null)
const previewUrl = ref('')
const selection = computed(() => JSON.stringify([productId.value, templateId.value, copies.value, widthMm.value, heightMm.value]))
const generatedSelection = ref('')
const stale = computed(() => generatedSelection.value !== selection.value)
const canGenerate = computed(() => !busy.value && templateReady.value && !!productId.value && Number.isInteger(copies.value) && copies.value >= 1 && copies.value <= 100 && widthMm.value >= 10 && widthMm.value <= 500 && heightMm.value >= 10 && heightMm.value <= 500)
const canConfirm = computed(() => !busy.value && !stale.value && !!previewUrl.value && !!job.value && ['generated', 'failed'].includes(job.value.status))
let templateRequest = 0
function message(e: unknown) { return e instanceof Error ? e.message : '操作失败，请重试' }
function updateHeight() { if (!paperLocked.value) heightMm.value = Math.round(widthMm.value / ratio.value * 100) / 100 }
function revokePreview() { if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }

async function loadProducts(reset = true) {
  if (productsLoading.value) return
  productsLoading.value = true
  loadError.value = ''
  if (reset) { appliedProductKeyword.value = productKeyword.value.trim(); products.value = []; productsTotal.value = 0; productsPage.value = 0; productId.value = '' }
  try {
    const page = productsPage.value + 1
    const data = await printApi.getLabelProducts({ keyword: appliedProductKeyword.value, page, per_page: 50 })
    if (!data.success) throw new Error(data.message || '加载业务产品失败')
    products.value = [...products.value, ...(data.data || []).filter(p => Number.isInteger(p.id) && p.id > 0)]
    productsTotal.value = Number(data.total ?? products.value.length)
    productsPage.value = page
    if (!products.value.length) loadError.value = '未找到业务产品，请调整关键词或先在业务产品库中创建。'
  } catch (e) { loadError.value = message(e) }
  finally { productsLoading.value = false }
}
async function loadOptions() {
  loadError.value = ''
  await Promise.allSettled([loadProducts(true), (async () => {
    try {
      const data = await templatePreviewApi.listTemplates() as { success: boolean; templates?: Template[]; message?: string }
      if (!data.success) throw new Error(data.message || '加载标签模板失败')
      templates.value = (data.templates || []).filter(t => t.category === 'label' && /^(?:db:)?[1-9][0-9]*$/.test(String(t.id))).map(t => ({ ...t, id: String(t.id) }))
      if (!templates.value.length) loadError.value = '暂无已保存的标签模板，请先在标签编辑器中创建。'
    } catch (e) { loadError.value = message(e) }
  })()])
}
async function loadTemplate() {
  const sequence = ++templateRequest
  templateReady.value = false
  templateError.value = ''
  if (!templateId.value) return
  try {
    const data = await templatePreviewApi.getTemplateDetail(templateId.value) as { success: boolean; template?: Template; message?: string }
    if (sequence !== templateRequest) return
    if (!data.success || !data.template || String(data.template.id) !== templateId.value || data.template.category !== 'label') throw new Error(data.message || '所选标签模板载入失败')
    const preview = data.template.preview_data || {}
    const size = preview.image_size as { width?: number; height?: number } | undefined
    const width = Number(size?.width ?? 900), height = Number(size?.height ?? 600)
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) throw new Error('模板画布尺寸无效，请编辑模板')
    ratio.value = width / height
    const paper = (preview.paper_size || preview.layout || {}) as { width_mm?: number; height_mm?: number; paper_width_mm?: number; paper_height_mm?: number }
    const savedWidth = Number(paper.width_mm ?? paper.paper_width_mm), savedHeight = Number(paper.height_mm ?? paper.paper_height_mm)
    paperLocked.value = Number.isFinite(savedWidth) && Number.isFinite(savedHeight) && savedWidth > 0 && savedHeight > 0
    widthMm.value = paperLocked.value ? savedWidth : 90
    heightMm.value = paperLocked.value ? savedHeight : Math.round(90 / ratio.value * 100) / 100
    templateReady.value = true
  } catch (e) { if (sequence === templateRequest) templateError.value = message(e) }
}
async function loadPreview() {
  if (!job.value) return
  error.value = ''
  try {
    const id = job.value.id
    const response = await printApi.downloadLabelJob(id)
    const blob = await response.blob()
    if (job.value?.id !== id) return
    if (!blob.size || !blob.type.includes('application/pdf')) throw new Error('标签文件响应无效')
    revokePreview()
    previewUrl.value = URL.createObjectURL(blob)
  } catch (e) { error.value = `预览加载失败：${message(e)}` }
}
async function generate() {
  if (!canGenerate.value) return
  busy.value = true
  error.value = ''
  confirmation.value = null
  const snapshot = selection.value
  job.value = null
  revokePreview()
  try {
    const data = await printApi.generateLabelJob({ product_id: Number(productId.value), template_id: templateId.value, copies: copies.value, paper_width_mm: widthMm.value, paper_height_mm: heightMm.value })
    if (!data.success || !data.job) throw new Error(data.message || '标签生成失败')
    revokePreview()
    job.value = data.job
    generatedSelection.value = snapshot
    await loadPreview()
  } catch (e) { error.value = message(e) } finally { busy.value = false }
}
async function preparePrint() {
  if (!canConfirm.value || !job.value) return
  busy.value = true; error.value = ''
  try { confirmation.value = await printApi.confirmLabelJob(job.value.id) }
  catch (e) { error.value = message(e) } finally { busy.value = false }
}
async function submitPrint() {
  if (!job.value || !confirmation.value || busy.value) return
  const token = confirmation.value.confirm_token
  confirmation.value = null
  busy.value = true; error.value = ''
  job.value = { ...job.value, status: 'submitting', message: '正在提交打印队列，请勿重复提交' }
  try { job.value = (await printApi.submitLabelJob(job.value.id, token)).job }
  catch (e) { error.value = `提交结果待确认：${message(e)}。请刷新任务状态并检查打印队列。` }
  finally { busy.value = false }
}
async function refreshStatus() {
  if (!job.value || busy.value) return
  busy.value = true; error.value = ''
  try { job.value = (await printApi.getLabelJob(job.value.id)).job }
  catch (e) { error.value = message(e) } finally { busy.value = false }
}
watch(templateId, loadTemplate)
watch(selection, () => { confirmation.value = null })
onMounted(loadOptions)
onBeforeUnmount(() => { templateRequest++; revokePreview() })
</script>

<style scoped>
.label-pdf-preview { display: block; width: 100%; height: 420px; border: 1px solid #ccc; margin: 12px 0; }
.card { margin-bottom: 16px; padding: 16px; }
.form-group { margin-bottom: 12px; }
label { display: block; margin-bottom: 4px; }
button, a { margin-right: 12px; }
[role="alert"] { color: #a52424; }
[role="dialog"] { margin-top: 12px; padding: 16px; border: 1px solid #888; }
</style>
