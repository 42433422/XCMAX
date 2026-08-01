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
            <button
              v-if="selectedFile"
              type="button"
              class="clear-file-button"
              @click="clearSelectedFile"
            >
              移除文件
            </button>
          </template>

          <template v-else>
            <label class="field-label" for="persy-text">内容</label>
            <textarea
              id="persy-text"
              v-model="documentText"
              rows="14"
              :placeholder="textPlaceholder"
            ></textarea>
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

<style scoped>
.section-kicker {
  color: #738179;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid #d4ded9;
  border-radius: 7px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
}

.icon-button:disabled,
.drawer-submit:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.drawer-header h3 {
  margin: 2px 0 0;
  color: #17211d;
  font-size: 17px;
  line-height: 1.25;
}

.clear-file-button {
  border: 0;
  background: transparent;
  color: #1d6259;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.import-tabs,
.advanced-settings__row {
  display: flex;
  align-items: center;
}

.import-tabs {
  padding: 3px;
  border: 1px solid #d6dfda;
  border-radius: 8px;
  background: #eef2f0;
}

.import-tabs button {
  border: 0;
  background: transparent;
  color: #68766f;
  cursor: pointer;
  font: inherit;
}

.import-tabs button.active {
  color: #17211d;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(23, 33, 29, 0.12);
}

.drawer-scrim {
  position: absolute;
  z-index: 40;
  inset: 0;
  display: flex;
  justify-content: flex-end;
  background: rgba(23, 33, 29, 0.28);
}

.import-drawer {
  display: flex;
  width: min(430px, 100%);
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid #d1ddd7;
  background: #ffffff;
  box-shadow: -18px 0 42px rgba(23, 33, 29, 0.14);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid #e3e9e6;
}

.import-tabs {
  align-self: flex-start;
  margin: 16px 20px 0;
}

.import-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 88px;
  min-height: 32px;
  justify-content: center;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.import-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 20px;
}

.field-label {
  display: block;
  margin: 0 0 6px;
  color: #52625a;
  font-size: 11px;
  font-weight: 700;
}

.text-input,
.import-body textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid #cbd7d1;
  border-radius: 7px;
  outline: none;
  color: #17211d;
  background: #ffffff;
  font: inherit;
  font-size: 13px;
}

.text-input {
  min-height: 38px;
  padding: 0 10px;
  margin-bottom: 16px;
}

.import-body textarea {
  min-height: 250px;
  padding: 10px;
  resize: vertical;
  line-height: 1.55;
}

.text-input:focus,
.import-body textarea:focus {
  border-color: #4e8e77;
  box-shadow: 0 0 0 3px rgba(78, 142, 119, 0.13);
}

.drop-zone {
  display: flex;
  width: 100%;
  min-height: 190px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  border: 1px dashed #9eafa6;
  border-radius: 8px;
  background: #f7f9f8;
  color: #52625a;
  cursor: pointer;
}

.drop-zone.dragging,
.drop-zone.has-file {
  border-color: #4e8e77;
  background: #eef6f2;
}

.drop-zone__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  color: #ffffff;
  background: #268578;
  font-size: 17px;
}

.drop-zone strong {
  max-width: 100%;
  overflow: hidden;
  color: #27352f;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drop-zone > span:last-child {
  color: #7a8880;
  font-size: 10px;
}

.clear-file-button {
  margin-top: 9px;
  padding: 0;
  font-size: 11px;
}

.advanced-settings {
  margin-top: 18px;
  border-top: 1px solid #e3e9e6;
  border-bottom: 1px solid #e3e9e6;
}

.advanced-settings summary {
  padding: 11px 0;
  color: #67766e;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}

.advanced-settings__row {
  gap: 8px;
  padding-bottom: 12px;
}

.advanced-settings__row .text-input {
  margin: 0;
}

.secondary-button,
.drawer-submit {
  min-height: 36px;
  border: 1px solid #ccd7d2;
  border-radius: 7px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.secondary-button {
  padding: 0 13px;
}

.form-error {
  margin: 12px 0 0;
  color: #a43b32;
  font-size: 11px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  padding: 14px 20px;
  border-top: 1px solid #e3e9e6;
}

.drawer-submit {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border-color: #17211d;
  background: #17211d;
  color: #ffffff;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 180ms ease;
}

.drawer-enter-active .import-drawer,
.drawer-leave-active .import-drawer {
  transition: transform 220ms ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .import-drawer,
.drawer-leave-to .import-drawer {
  transform: translateX(100%);
}

@media (max-width: 767px) {
  .drawer-scrim {
    align-items: flex-end;
  }

  .import-drawer {
    width: 100%;
    max-height: 92%;
    border-top: 1px solid #d1ddd7;
    border-left: 0;
    border-radius: 8px 8px 0 0;
  }

  .drawer-enter-from .import-drawer,
  .drawer-leave-to .import-drawer {
    transform: translateY(100%);
  }
}
</style>
