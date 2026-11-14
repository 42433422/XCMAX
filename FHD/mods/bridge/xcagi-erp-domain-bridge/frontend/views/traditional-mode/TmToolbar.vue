<script setup lang="ts">
import { ref } from 'vue'
import type { TraditionalModeCtx } from './assemble'

// 拆分自 TraditionalModeView.vue 模板（原第 22–67 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: TraditionalModeCtx }>()

const {
  historyIndex, history, currentPath, loading, viewMode, setViewMode,
  goBack, goForward, goUp, refresh, showMkdirDialog, handleUpload,
} = props.tm

const fileInputRef = ref<HTMLInputElement | null>(null)
</script>

<template>
    <div class="toolbar explorer-toolbar">
      <div class="toolbar-group">
        <button type="button" class="toolbar-btn iconish" :disabled="historyIndex <= 0" @click="goBack" title="后退 (Alt+←)">◀</button>
        <button type="button" class="toolbar-btn iconish" :disabled="historyIndex >= history.length - 1" @click="goForward" title="前进 (Alt+→)">▶</button>
        <button type="button" class="toolbar-btn iconish" :disabled="!currentPath" @click="goUp" title="上级文件夹">↑</button>
        <button type="button" class="toolbar-btn iconish" @click="refresh" :disabled="loading" title="刷新">↻</button>
      </div>
      <div class="toolbar-divider tall"></div>
      <div class="toolbar-group">
        <button type="button" class="toolbar-btn" @click="showMkdirDialog = true" title="新建文件夹">新建文件夹</button>
        <label class="toolbar-btn" title="上传文件">
          上传
          <input ref="fileInputRef" type="file" style="display:none" multiple @change="handleUpload">
        </label>
      </div>
      <div class="toolbar-divider tall"></div>
      <div class="toolbar-group view-mode-group" role="group" aria-label="视图布局">
        <button
          type="button"
          class="toolbar-btn view-mode-btn"
          :class="{ 'is-active': viewMode === 'details' }"
          title="详细信息列表"
          @click="setViewMode('details')"
        >
          详细信息
        </button>
        <button
          type="button"
          class="toolbar-btn view-mode-btn"
          :class="{ 'is-active': viewMode === 'icons' }"
          title="中等图标（与资源管理器类似）"
          @click="setViewMode('icons')"
        >
          中等图标
        </button>
        <button
          type="button"
          class="toolbar-btn view-mode-btn"
          :class="{ 'is-active': viewMode === 'large' }"
          title="大图标"
          @click="setViewMode('large')"
        >
          大图标
        </button>
      </div>
    </div>
</template>

<style scoped src="./traditional-mode.css"></style>
