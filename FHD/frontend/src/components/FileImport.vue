<template>
  <div class="file-import-overlay" v-if="modelValue" @click.self="handleClose">
    <div class="file-import-modal">
      <div class="file-import-header">
        <h4>{{ title }}</h4>
        <button class="close-btn" @click="handleClose" title="关闭">
          <i class="fas fa-times"></i>
        </button>
      </div>

      <div class="file-import-body">
        <div
          class="drop-zone"
          :class="{
            dragover: isDragOver,
            uploading: uploading,
          }"
          @dragenter.prevent="handleDragEnter"
          @dragover.prevent="handleDragOver"
          @dragleave.prevent="handleDragLeave"
          @drop.prevent="handleDrop"
          @click="triggerFileInput"
        >
          <div class="drop-zone-content">
            <i class="fas fa-cloud-upload-alt"></i>
            <p class="drop-zone-title">点击或拖拽文件到此处</p>
            <p class="drop-zone-hint">{{ hint }}</p>
            <p class="drop-zone-supported">支持：Excel、CSV、图片、PDF、Word</p>
          </div>
          <input
            ref="fileInputRef"
            type="file"
            class="file-input"
            :accept="acceptFormats"
            :multiple="multiple"
            @change="handleFileChange"
          />
        </div>

        <div class="import-progress" v-if="uploading || progress > 0">
          <div class="progress-header">
            <span class="progress-text">{{ progressText }}</span>
            <span class="progress-percent">{{ progress }}%</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progress + '%' }" :class="{ 'progress-animated': uploading }"></div>
          </div>
        </div>

        <div class="import-status" v-if="status.show" :class="status.type">
          <i :class="statusIcon"></i>
          <span>{{ status.message }}</span>
        </div>

        <div class="file-list" v-if="selectedFiles.length > 0">
          <div class="file-list-header">
            <span>已选择文件 ({{ selectedFiles.length }})</span>
            <button class="clear-btn" @click="clearFiles" v-if="!uploading"><i class="fas fa-trash"></i> 清空</button>
          </div>
          <div class="file-items">
            <div class="file-item" v-for="(file, index) in selectedFiles" :key="index">
              <i :class="getFileIcon(file.type)" class="file-icon"></i>
              <div class="file-info">
                <span class="file-name">{{ file.name }}</span>
                <span class="file-size">{{ formatFileSize(file.size) }}</span>
              </div>
              <span class="file-type-tag">{{ file.fileType }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="file-import-footer">
        <button class="btn btn-secondary" @click="handleClose" :disabled="uploading">取消</button>
        <button class="btn btn-primary" @click="handleUpload" :disabled="selectedFiles.length === 0 || uploading">
          <i class="fas fa-upload" v-if="!uploading"></i>
          <i class="fas fa-spinner fa-spin" v-else></i>
          {{ uploading ? '上传中...' : '开始导入' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import useFileImport, { FILE_EXTENSIONS } from '../composables/useFileImport'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: '文件导入',
  },
  purpose: {
    type: String,
    default: 'general',
    validator: (value) => ['general', 'product_import', 'customers_import', 'order_parse', 'materials_import'].includes(value),
  },
  hint: {
    type: String,
    default: '支持 Excel、CSV、图片等格式，自动识别并分析',
  },
  acceptFormats: {
    type: String,
    default: '.xlsx,.xls,.csv,.jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx',
  },
  multiple: {
    type: Boolean,
    default: true,
  },
  autoUpload: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'uploaded', 'error', 'progress', 'file-complete'])

const fileInputRef = ref(null)
const isDragOver = ref(false)
const selectedFiles = ref([])

const { uploading, progress, progressText, status, detectFileType, resetState, uploadFile, uploadMultipleFiles } = useFileImport()

const computedHint = computed(() => {
  if (props.purpose === 'customers_import') {
    return '请上传购买单位列表 .xlsx（需含「单位名称」列），将校验格式并更新联系人/电话/地址'
  }
  if (props.purpose === 'product_import') {
    return '产品导入模式：支持任意文件，自动识别并分析'
  }
  if (props.purpose === 'order_parse') {
    return '订单解析模式：上传后自动提取订单关键信息'
  }
  if (props.purpose === 'materials_import') {
    return '原材料导入模式：支持 Excel/CSV 格式'
  }
  return props.hint
})

const statusIcon = computed(() => {
  if (status.type === 'success') return 'fas fa-check-circle'
  if (status.type === 'error') return 'fas fa-exclamation-circle'
  return 'fas fa-info-circle'
})

function getFileIcon(fileType) {
  const icons = {
    excel: 'fas fa-file-excel',
    csv: 'fas fa-file-csv',
    image: 'fas fa-file-image',
    pdf: 'fas fa-file-pdf',
    word: 'fas fa-file-word',
    other: 'fas fa-file',
  }
  return icons[fileType] || icons.other
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}

function triggerFileInput() {
  if (!uploading.value && fileInputRef.value) {
    fileInputRef.value.click()
  }
}

function handleDragEnter(e) {
  if (!uploading.value) {
    isDragOver.value = true
  }
}

function handleDragOver(e) {
  if (!uploading.value) {
    isDragOver.value = true
  }
}

function handleDragLeave(e) {
  if (e.relatedTarget === null || !e.currentTarget.contains(e.relatedTarget)) {
    isDragOver.value = false
  }
}

function handleDrop(e) {
  isDragOver.value = false
  if (uploading.value) return

  const files = e.dataTransfer.files
  if (files.length > 0) {
    handleFiles(files)
  }
}

function handleFileChange(e) {
  const files = e.target.files
  if (files.length > 0) {
    handleFiles(files)
  }
}

function handleFiles(fileList) {
  const newFiles = []
  for (let i = 0; i < fileList.length; i++) {
    const file = fileList[i]
    const fileType = detectFileType(file)
    newFiles.push({
      ...file,
      fileType,
    })
  }

  if (props.multiple) {
    selectedFiles.value = [...selectedFiles.value, ...newFiles]
  } else {
    selectedFiles.value = [newFiles[0]]
  }

  if (props.autoUpload && newFiles.length > 0) {
    handleUpload()
  }
}

function clearFiles() {
  selectedFiles.value = []
  resetState()
}

async function handleUpload() {
  if (selectedFiles.value.length === 0 || uploading.value) return

  const filesToUpload = selectedFiles.value.map((f) => {
    const newFile = new File([f], f.name, { type: f.type })
    return newFile
  })

  try {
    if (filesToUpload.length === 1) {
      const result = await uploadFile(filesToUpload[0], props.purpose, (percent, fileName) => {
        emit('progress', { percent, fileName, totalFiles: 1 })
      })

      if (result) {
        emit('uploaded', {
          file: selectedFiles.value[0],
          result,
        })
      } else {
        emit('error', {
          file: selectedFiles.value[0],
          error: status.message,
        })
      }
    } else {
      const results = await uploadMultipleFiles(filesToUpload, props.purpose, (fileResult, completed, total) => {
        emit('file-complete', {
          file: fileResult,
          completed,
          total,
        })
      })

      emit('uploaded', {
        files: selectedFiles.value,
        results,
      })
    }
  } catch (err) {
    console.error('Upload error:', err)
    emit('error', {
      error: err.message,
    })
  }
}

function handleClose() {
  if (!uploading.value) {
    emit('update:modelValue', false)
    selectedFiles.value = []
    resetState()
  }
}

watch(
  () => props.modelValue,
  (newVal) => {
    if (!newVal) {
      selectedFiles.value = []
      resetState()
    }
  },
)
</script>

<style scoped src="./FileImport.css"></style>
