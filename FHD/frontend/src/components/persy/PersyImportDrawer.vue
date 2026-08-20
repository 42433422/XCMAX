<template>
  <Transition name="drawer">
    <div v-if="importOpen" class="drawer-scrim" @click.self="closeImport">
      <aside class="import-drawer" role="dialog" aria-modal="true" aria-labelledby="persy-import-title">
        <header class="drawer-header">
          <div>
            <span class="section-kicker">Grow Persy</span>
            <h3 id="persy-import-title">添加知识来源</h3>
          </div>
          <button type="button" class="icon-button" aria-label="关闭" title="关闭" @click="closeImport">
            <i class="fa fa-times" aria-hidden="true"></i>
          </button>
        </header>

        <div class="import-tabs" role="tablist" aria-label="导入方式">
          <button
            type="button"
            role="tab"
            :aria-selected="importMode === 'file'"
            :class="{ active: importMode === 'file' }"
            @click="importMode = 'file'"
          >
            <i class="fa fa-file-o" aria-hidden="true"></i>
            文件
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="importMode === 'text'"
            :class="{ active: importMode === 'text' }"
            @click="importMode = 'text'"
          >
            <i class="fa fa-clipboard" aria-hidden="true"></i>
            文本
          </button>
        </div>

        <div class="import-body">
          <label class="field-label" for="persy-source">名称</label>
          <input
            id="persy-source"
            v-model.trim="source"
            class="text-input"
            type="text"
            autocomplete="off"
            :placeholder="sourcePlaceholder"
          />

          <template v-if="importMode === 'file'">
            <input
              ref="fileInput"
              class="visually-hidden"
              type="file"
              accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.csv,.json,.log"
              @change="selectFile"
            />
            <button
              type="button"
              class="drop-zone"
              :class="{ 'has-file': selectedFile, dragging: draggingFile }"
              @click="openFilePicker"
              @dragenter.prevent="draggingFile = true"
              @dragover.prevent="draggingFile = true"
              @dragleave.prevent="draggingFile = false"
              @drop.prevent="dropFile"
            >
              <span class="drop-zone__icon">
                <i :class="selectedFile ? 'fa fa-check' : 'fa fa-cloud-upload'" aria-hidden="true"></i>
              </span>
              <strong>{{ selectedFile?.name || '选择或拖入资料' }}</strong>
              <span v-if="selectedFile">{{ fileSizeText(selectedFile.size) }}</span>
              <span v-else>PDF、Word、Excel、Markdown、CSV、JSON，最大 25 MB</span>
            </button>
            <button v-if="selectedFile" type="button" class="clear-file-button" @click="clearSelectedFile">移除文件</button>
          </template>

          <template v-else>
            <label class="field-label" for="persy-text">内容</label>
            <textarea id="persy-text" v-model="documentText" rows="14" :placeholder="textPlaceholder"></textarea>
          </template>

          <details class="advanced-settings">
            <summary>知识空间</summary>
            <div class="advanced-settings__row">
              <input
                v-model.trim="datasetIdModel"
                class="text-input"
                type="text"
                autocomplete="off"
                spellcheck="false"
                aria-label="数据集"
                @keyup.enter="emit('applyDataset')"
              />
              <button type="button" class="secondary-button" @click="emit('applyDataset')">切换</button>
            </div>
          </details>

          <p v-if="ingestError" class="form-error" role="alert">{{ ingestError }}</p>
        </div>

        <footer class="drawer-footer">
          <button type="button" class="secondary-button" @click="closeImport">取消</button>
          <button type="button" class="drawer-submit" :disabled="ingesting" @click="ingestDocument">
            <i :class="ingesting ? 'fa fa-circle-o-notch fa-spin' : 'fa fa-arrow-up'" aria-hidden="true"></i>
            {{ ingesting ? '正在形成节点' : '加入 Persy' }}
          </button>
        </footer>
      </aside>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { errorText, fileSizeText } from '@/composables/persyKnowledgeFormatters'

type ImportMode = 'file' | 'text'

const props = defineProps<{
  datasetId: string
  datasetIdInput: string
  sourcePlaceholder: string
  textPlaceholder: string
}>()

const emit = defineEmits<{
  'update:datasetIdInput': [value: string]
  applyDataset: []
  clearMessage: []
  ingested: [message: string]
}>()

const datasetIdModel = computed({
  get: () => props.datasetIdInput,
  set: (value: string) => emit('update:datasetIdInput', value),
})

const importOpen = ref(false)
const importMode = ref<ImportMode>('file')
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const draggingFile = ref(false)
const ingesting = ref(false)
const source = ref('Persy 系统资料')
const documentText = ref('')
const ingestError = ref('')

function open(mode: ImportMode): void {
  importMode.value = mode
  ingestError.value = ''
  importOpen.value = true
}

function closeImport(): void {
  if (ingesting.value) return
  importOpen.value = false
  draggingFile.value = false
}

async function ingestDocument(): Promise<void> {
  const text = documentText.value.trim()
  emit('clearMessage')
  ingestError.value = ''
  if (importMode.value === 'file' && !selectedFile.value) {
    ingestError.value = '请选择资料文件'
    return
  }
  if (importMode.value === 'text' && !text) {
    ingestError.value = '请输入资料内容'
    return
  }
  ingesting.value = true
  try {
    const result =
      importMode.value === 'file' && selectedFile.value
        ? await knowledgeBaseApi.uploadDocument({
            datasetId: props.datasetId,
            source: source.value.trim() || selectedFile.value.name,
            file: selectedFile.value,
          })
        : await knowledgeBaseApi.ingestDocument({
            datasetId: props.datasetId,
            source: source.value.trim() || 'Persy 手工资料',
            text,
            metadata: {
              scope: 'persy',
              entrypoint: 'persy_knowledge_view',
            },
          })
    if (!result.success) throw new Error(result.message || '资料入库失败')
    const chunks = result.chunk_count ?? result.document?.chunk_count ?? 0
    documentText.value = ''
    clearSelectedFile()
    importOpen.value = false
    emit('ingested', `已形成 ${chunks} 个知识节点`)
  } catch (error) {
    ingestError.value = errorText(error)
  } finally {
    ingesting.value = false
  }
}

function openFilePicker(): void {
  fileInput.value?.click()
}

function setSelectedFile(file: File | null): void {
  selectedFile.value = file
  if (file && (source.value === 'Persy 系统资料' || !source.value.trim())) source.value = file.name
}

function validateKnowledgeFile(file: File): string {
  const extension = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : ''
  if (!['.pdf', '.docx', '.xlsx', '.xls', '.txt', '.md', '.csv', '.json', '.log'].includes(extension)) {
    return `不支持的资料类型：${extension || '无扩展名'}`
  }
  if (file.size > 25 * 1024 * 1024) {
    return '资料文件不能超过 25 MB'
  }
  return ''
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (!file) {
    setSelectedFile(null)
    return
  }
  const error = validateKnowledgeFile(file)
  if (error) {
    ingestError.value = error
    clearSelectedFile()
    return
  }
  ingestError.value = ''
  setSelectedFile(file)
}

function dropFile(event: DragEvent): void {
  draggingFile.value = false
  const file = event.dataTransfer?.files?.[0] || null
  if (!file) return
  const error = validateKnowledgeFile(file)
  if (error) {
    ingestError.value = error
    return
  }
  ingestError.value = ''
  setSelectedFile(file)
}

function clearSelectedFile(): void {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

defineExpose({ open })
</script>

<style scoped src="./PersyImportDrawer.css"></style>
