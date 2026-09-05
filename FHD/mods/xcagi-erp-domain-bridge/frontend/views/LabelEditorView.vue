<template>
  <div class="label-editor-page">
    <div class="editor-header">
      <h2><i class="fa fa-tag" aria-hidden="true"></i> 标签模板编辑器</h2>
      <div class="header-actions">
        <button class="btn btn-info" :disabled="!templateReady || isAnalyzing" @click="triggerFileInput"><i class="fa fa-upload" aria-hidden="true"></i> 上传识别</button>
        <button class="btn btn-secondary" @click="goBack"><i class="fa fa-arrow-left" aria-hidden="true"></i> 返回</button>
        <button class="btn btn-primary" :disabled="!canSave || savingTemplate" @click="saveTemplate"><i class="fa fa-save" aria-hidden="true"></i> {{ savingTemplate ? '正在保存…' : sourceTemplate ? '另存为新模板' : '保存新模板' }}</button>
      </div>
    </div>
    <input type="file" ref="fileInput" accept="image/*" @change="onFileSelected" hidden />
    <div v-if="loadingTemplate" class="analyze-status-bar" role="status">正在加载所选模板…</div>
    <div v-if="templateLoadError" class="analyze-status-bar is-error" role="alert">
      <span>{{ templateLoadError }}</span>
      <button class="btn btn-secondary" @click="loadTemplate">重新加载</button>
    </div>
    <div v-if="templateReady" class="template-name-row">
      <label>模板名称 <input v-model="templateName" aria-label="模板名称" /></label>
      <p v-if="sourceTemplate">当前模板：{{ sourceTemplate.name }}。将另存为「{{ saveName }}」，原模板保持不变。</p>
      <p>保存模板后，可在标签输出与打印页选择业务产品，生成标签 PDF 并核对后打印。</p>
    </div>
    <div v-if="saveError" class="analyze-status-bar is-error" role="alert">{{ saveError }}</div>

    <div v-show="templateReady" class="editor-toolbar">
      <div class="toolbar-group">
        <label>缩放：</label>
        <input type="range" v-model="zoom" min="0.5" max="2" step="0.1" />
        <span>{{ Math.round(zoom * 100) }}%</span>
      </div>
      <div class="toolbar-group">
        <button class="btn btn-sm" :class="showGrid ? 'btn-primary' : 'btn-secondary'" @click="showGrid = !showGrid">
          <i class="fa fa-th" aria-hidden="true"></i> 网格线
        </button>
        <button class="btn btn-sm" :class="showMerge ? 'btn-primary' : 'btn-secondary'" @click="showMerge = !showMerge">
          <i class="fa fa-link" aria-hidden="true"></i> 合并单元格
        </button>
      </div>
    </div>
    <div
      v-if="isAnalyzing || analyzeError || analyzeStage"
      class="analyze-status-bar"
      :class="{
        'is-loading': isAnalyzing,
        'is-error': !!analyzeError,
        'is-success': !isAnalyzing && !analyzeError && analyzeStage === '识别完成'
      }"
    >
      <div class="analyze-status-text">
        <i v-if="isAnalyzing" class="fa fa-spinner analyze-spinning" aria-hidden="true"></i>
        <i v-else-if="analyzeError" class="fa fa-exclamation-triangle" aria-hidden="true"></i>
        <i v-else-if="analyzeStage === '识别完成'" class="fa fa-check-circle" aria-hidden="true"></i>
        <span>{{ analyzeError || analyzeStage }}</span>
      </div>
      <div v-if="isAnalyzing" class="analyze-progress-track">
        <div class="analyze-progress-fill"></div>
      </div>
    </div>

    <div v-show="templateReady" class="editor-content">
      <div class="canvas-wrapper" :style="{ transform: `scale(${zoom})` }">
        <canvas
          ref="labelCanvas"
          :width="canvasWidth"
          :height="canvasHeight"
          @click="handleCanvasClick"
          @mousemove="handleMouseMove"
          @mousedown="handleMouseDown"
          @mouseup="handleMouseUp"
          @mouseleave="handleMouseLeave"
        ></canvas>
      </div>

      <LeFieldsPanel :tp="le" />
    </div>

  </div>
</template>

<script setup lang="ts">
import LeFieldsPanel from './label-editor/LeFieldsPanel.vue'
import { assembleLabelEditor } from './label-editor/assemble'

defineOptions({ name: 'LabelEditorView' })

const le = assembleLabelEditor()

const {
  fileInput, labelCanvas, canvasWidth, canvasHeight, zoom,
  showGrid, showMerge,
  isAnalyzing, analyzeError, analyzeStage,
  triggerFileInput, onFileSelected,
  handleCanvasClick, handleMouseMove, handleMouseDown, handleMouseUp, handleMouseLeave,
  saveTemplate, goBack,
  templateName, sourceTemplate, saveName, savingTemplate, saveError, canSave,
  templateReady, loadingTemplate, templateLoadError, loadTemplate,
} = le
</script>

<style scoped src="./label-editor/label-editor.css"></style>
