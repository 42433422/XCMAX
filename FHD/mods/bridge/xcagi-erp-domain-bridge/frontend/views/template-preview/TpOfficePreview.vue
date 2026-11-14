<script setup lang="ts">
/**
 * 模板库原件预览：Word / PPT 使用 vue-office（@vue-office/docx、@vue-office/pptx）渲染，
 * PDF 交给 Chromium 内置阅读器（iframe 指向同源原件接口）。
 */
import { ref, shallowRef, watch } from 'vue'
import { apiFetch } from '@/utils/apiBase'

type OfficePreviewKind = 'docx' | 'pptx' | 'pdf'

const props = defineProps<{
  templateId: string
  kind: OfficePreviewKind
}>()

const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const error = ref('')
const buffer = shallowRef<ArrayBuffer | null>(null)
const renderer = shallowRef<{ default: unknown } | null>(null)
const fileUrl = ref('')

let requestSeq = 0

function templateFileUrl(templateId: string): string {
  return `/api/templates/${encodeURIComponent(templateId)}/file`
}

async function load() {
  const templateId = String(props.templateId || '').trim()
  if (!templateId) {
    status.value = 'error'
    error.value = '缺少模板标识'
    return
  }
  const current = ++requestSeq
  const url = templateFileUrl(templateId)
  fileUrl.value = url
  error.value = ''
  buffer.value = null
  renderer.value = null

  if (props.kind === 'pdf') {
    status.value = 'ready'
    return
  }

  status.value = 'loading'
  try {
    const response = await apiFetch(url, { credentials: 'same-origin' } as RequestInit)
    if (!response.ok) throw new Error(`原件读取失败（HTTP ${response.status}）`)
    const data = await response.arrayBuffer()
    if (current !== requestSeq) return

    const mod =
      props.kind === 'docx'
        ? await import('@vue-office/docx')
        : await import('@vue-office/pptx')
    if (current !== requestSeq) return

    renderer.value = mod as unknown as { default: unknown }
    buffer.value = data
    status.value = 'ready'
  } catch (err) {
    if (current !== requestSeq) return
    status.value = 'error'
    error.value = err instanceof Error ? err.message : '原件加载失败'
  }
}

watch(() => [props.templateId, props.kind], load, { immediate: true })
</script>

<template>
  <div class="tp-office-preview">
    <div v-if="status === 'loading'" class="tp-office-preview__state">原件加载中…</div>
    <div v-else-if="status === 'error'" class="tp-office-preview__state">{{ error }}</div>
    <iframe
      v-else-if="kind === 'pdf'"
      class="tp-office-preview__frame"
      :src="fileUrl"
      title="PDF 模板预览"
    />
    <component
      :is="renderer.default"
      v-else-if="renderer && buffer"
      class="tp-office-preview__doc"
      :src="buffer"
    />
  </div>
</template>

<style scoped>
.tp-office-preview {
  margin-top: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  overflow: hidden;
}

.tp-office-preview__state {
  padding: 24px;
  font-size: 13px;
  color: #64748b;
  text-align: center;
}

.tp-office-preview__frame {
  width: 100%;
  height: 68vh;
  border: 0;
  background: #fff;
}

.tp-office-preview__doc {
  max-height: 68vh;
  overflow: auto;
  padding: 12px;
  background: #fff;
}
</style>
