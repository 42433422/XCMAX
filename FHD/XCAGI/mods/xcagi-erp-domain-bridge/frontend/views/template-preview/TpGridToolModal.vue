<script setup lang="ts">
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import type { TemplatePreviewCtx } from './assemble'

// 拆分自 TemplatePreviewView.vue 模板（原第 388–409 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: TemplatePreviewCtx }>()

const {
  showGridToolModal, gridToolResult,
} = props.tp
</script>

<template>
    <div v-if="showGridToolModal" class="modal-overlay" @click.self="showGridToolModal = false">
      <div class="modal-content" style="max-width:920px;">
        <div class="modal-header">
          <h3><i class="fa fa-th" aria-hidden="true"></i> 网格提取结果 - {{ gridToolResult?.template_name }}</h3>
          <button type="button" class="modal-close" @click="showGridToolModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <ExcelPreview
            v-if="gridToolResult"
            :fields="gridToolResult.fields || []"
            :sample-rows="gridToolResult?.preview_data?.sample_rows || []"
            :title="(gridToolResult?.preview_data?.sheet_name || 'Sheet') + ' 真实网格'"
            :grid-data="gridToolResult?.preview_data?.grid_preview || null"
            :rows="10"
            :columns="8"
          />
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showGridToolModal = false">关闭</button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./template-preview.css"></style>
