<script setup lang="ts">
import { ref, useId } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import LabelPreview from '@/components/template/LabelPreview.vue'
import TpOfficePreview from './TpOfficePreview.vue'
import type { TemplatePreviewCtx } from './assemble'
import type { TplRecord } from './tpTemplateMeta'

const props = defineProps<{ tp: TemplatePreviewCtx }>()

const OFFICE_CATEGORY_TO_KIND = { word: 'docx', pptx: 'pptx', pdf: 'pdf' } as const

function isOfficeCategory(tpl: TplRecord | null): boolean {
  const category = String(tpl?.category || '').trim().toLowerCase()
  return category in OFFICE_CATEGORY_TO_KIND
}

function officePreviewKind(tpl: TplRecord | null): 'docx' | 'pptx' | 'pdf' {
  const category = String(tpl?.category || '').trim().toLowerCase()
  return OFFICE_CATEGORY_TO_KIND[category as keyof typeof OFFICE_CATEGORY_TO_KIND] || 'pdf'
}

const {
  showPreviewModal, closePreviewModal, previewingTemplate,
  canPreviewVirtualTemplate, getTemplateFields, getTemplateSampleRows, getExcelPreviewTitle,
  getTemplateGridData, getTemplateCategoryLabel, isGridTemplateCategory,
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
              v-if="isGridTemplateCategory(previewingTemplate) && (!previewingTemplate?.virtual || canPreviewVirtualTemplate(previewingTemplate))"
              :fields="getTemplateFields(previewingTemplate, 'excel')"
              :sample-rows="getTemplateSampleRows(previewingTemplate)"
              :title="getExcelPreviewTitle(previewingTemplate)"
              :grid-data="getTemplateGridData(previewingTemplate)"
              :rows="8"
              :columns="6"
            />
            <div v-else-if="isGridTemplateCategory(previewingTemplate) && previewingTemplate?.virtual" class="virtual-template-preview">
              <div class="virtual-template-title">该模板尚未上传</div>
              <div class="virtual-template-terms">请点击「快速创建」上传 Excel、Word、PPT、PDF 或 CSV 模板并完成必备词条配置。</div>
            </div>
            <div v-else-if="isOfficeCategory(previewingTemplate)" class="virtual-template-preview">
              <div class="virtual-template-title">{{ getTemplateCategoryLabel(previewingTemplate) }} 模板</div>
              <div class="virtual-template-terms muted" style="font-size:13px;">
                {{ previewingTemplate?.filename || previewingTemplate?.name }}<br>
                <span v-if="previewingTemplate?.file_path || previewingTemplate?.path">路径：{{ previewingTemplate?.file_path || previewingTemplate?.path }}</span>
              </div>
              <TpOfficePreview
                :template-id="String(previewingTemplate?.id || previewingTemplate?.db_id || '')"
                :kind="officePreviewKind(previewingTemplate)"
              />
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
