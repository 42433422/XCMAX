<script setup lang="ts">
import { ref, useId } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import LabelPreview from '@/components/template/LabelPreview.vue'
import type { TemplatePreviewCtx } from './assemble'

const props = defineProps<{ tp: TemplatePreviewCtx }>()

const {
  showPreviewModal, closePreviewModal, previewingTemplate,
  canPreviewVirtualTemplate, getTemplateFields, getTemplateSampleRows, getExcelPreviewTitle,
  getTemplateGridData,
} = props.tp
const panel = ref<HTMLElement | null>(null)
const titleId = useId()
useDialogFocus(panel, () => showPreviewModal.value, closePreviewModal)
</script>

<template>
    <div v-if="showPreviewModal" class="modal-overlay" @click.self="closePreviewModal">
      <div ref="panel" class="modal-content" style="max-width:800px;" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1">
        <div class="modal-header">
          <h3 :id="titleId"><i class="fa fa-file-text-o" aria-hidden="true"></i> 模板预览 - {{ previewingTemplate?.name }}</h3>
          <button type="button" class="modal-close" aria-label="关闭模板预览" @click="closePreviewModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="preview-modal-content">
            <ExcelPreview
              v-if="previewingTemplate?.category === 'excel' && (!previewingTemplate?.virtual || canPreviewVirtualTemplate(previewingTemplate))"
              :fields="getTemplateFields(previewingTemplate, 'excel')"
              :sample-rows="getTemplateSampleRows(previewingTemplate)"
              :title="getExcelPreviewTitle(previewingTemplate)"
              :grid-data="getTemplateGridData(previewingTemplate)"
              :rows="8"
              :columns="6"
            />
            <div v-else-if="previewingTemplate?.category === 'excel' && previewingTemplate?.virtual" class="virtual-template-preview">
              <div class="virtual-template-title">该模板尚未上传</div>
              <div class="virtual-template-terms">请点击「快速创建」上传 Excel 或 Word 模板并完成必备词条配置。</div>
            </div>
            <div v-else-if="previewingTemplate?.category === 'word'" class="virtual-template-preview">
              <div class="virtual-template-title">Word 模板</div>
              <div class="virtual-template-terms muted" style="font-size:13px;">
                {{ previewingTemplate?.filename || previewingTemplate?.name }}<br>
                <span v-if="previewingTemplate?.file_path || previewingTemplate?.path">路径：{{ previewingTemplate?.file_path || previewingTemplate?.path }}</span>
              </div>
            </div>
            <LabelPreview v-else-if="previewingTemplate?.category === 'label'" :fields="getTemplateFields(previewingTemplate, 'label')" :width="400" :height="280" />
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closePreviewModal">关闭</button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./template-preview.css"></style>
