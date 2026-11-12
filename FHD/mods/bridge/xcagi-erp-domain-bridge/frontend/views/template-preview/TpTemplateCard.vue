<script setup lang="ts">
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import LabelPreview from '@/components/template/LabelPreview.vue'
import type { TemplatePreviewCtx } from './assemble'
import type { TplRecord } from './tpTemplateMeta'

// 拆分自 TemplatePreviewView.vue 模板（原第 50–185 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: TemplatePreviewCtx; tpl: TplRecord }>()

const {
  getScopeIconClass, getTemplateScopeKey, getTemplateScopeLabel,
  canPreviewVirtualTemplate, getTemplateFields, getTemplateSampleRows, getExcelPreviewTitle,
  getTemplateGridData, getRequiredTermsByScope, getTemplateSourceLabel, getTemplateTypeLabel,
  getTemplateDisplayTermsText, getMatchedScopeLabels, getTemplateCoverage,
  startCreateForScope, previewTemplate, openTemplateTarget, editTemplate,
  openReplaceTemplateDialog, canDeleteTemplate, confirmDeleteTemplate,
} = props.tp
</script>

<template>
          <div
            class="template-preview-card"
            :class="{ 'template-preview-card--word': tpl.category === 'word' }"
            :data-template-id="tpl.id"
          >
            <div class="template-preview-card-icon" aria-hidden="true">
              <i
                class="fa"
                :class="
                  tpl.category === 'label'
                    ? 'fa-tag'
                    : tpl.category === 'word'
                      ? 'fa-file-word-o'
                      : getScopeIconClass(getTemplateScopeKey(tpl))
                "
              ></i>
            </div>
            <div class="template-preview-card-title">
              {{ tpl.name }}
              <span class="scope-badge">{{ getTemplateScopeLabel(tpl) }}</span>
            </div>

            <div class="template-preview-preview">
              <ExcelPreview
                v-if="tpl.category === 'excel' && (!tpl.virtual || canPreviewVirtualTemplate(tpl))"
                :fields="getTemplateFields(tpl, 'excel')"
                :sample-rows="getTemplateSampleRows(tpl)"
                :title="getExcelPreviewTitle(tpl)"
                :grid-data="getTemplateGridData(tpl)"
                :rows="6"
                :columns="6"
              />
              <div v-else-if="tpl.category === 'excel' && tpl.virtual" class="virtual-template-preview">
                <div class="virtual-template-title">待上传 Excel / Word 模板</div>
                <div class="virtual-template-terms">必备词条：{{ getRequiredTermsByScope(tpl.business_scope).join('、') }}</div>
              </div>
              <div v-else-if="tpl.category === 'word'" class="virtual-template-preview">
                <div class="virtual-template-title">Word 模板（.docx）</div>
                <div class="virtual-template-terms muted" style="font-size:12px;">
                  {{ tpl.filename || tpl.name }}<br>
                  请在资源管理器中打开文件进行编辑；本页仅做登记与路径展示。
                </div>
              </div>
              <LabelPreview v-else-if="tpl.category === 'label'" :fields="getTemplateFields(tpl, 'label')" />
            </div>

            <div class="template-preview-card-desc">
              <span>分类：{{ tpl.category === 'label' ? '标签打印' : tpl.category === 'word' ? 'Word' : 'Excel' }}</span>
              <br>
              <span>来源：{{ getTemplateSourceLabel(tpl) }}</span>
              <br v-if="tpl.virtual">
              <span v-if="tpl.virtual">状态：未配置（可上传模板创建）</span>
              <br v-if="tpl.template_type">
              <span v-if="tpl.template_type">类型：{{ getTemplateTypeLabel(tpl) }}</span>
              <template v-if="tpl.category === 'excel' && !tpl.virtual">
                <br>
                <span>模板词条：{{ getTemplateDisplayTermsText(tpl) }}</span>
                <br>
                <span v-if="getMatchedScopeLabels(tpl).length">
                  可对应业务：{{ getMatchedScopeLabels(tpl).join('、') }}
                </span>
                <span v-else class="unmatched-scope-text">
                  可对应业务：未匹配（词条不完整）
                </span>
                <template v-if="getTemplateCoverage(tpl)">
                  <br>
                <span>
                  词条完整度：{{ getTemplateCoverage(tpl)!.matchedCount }}/{{ getTemplateCoverage(tpl)!.requiredCount }}
                </span>
                <br v-if="getTemplateCoverage(tpl)!.missing.length">
                <span v-if="getTemplateCoverage(tpl)!.missing.length">
                  缺失：{{ getTemplateCoverage(tpl)!.missing.join('、') }}
                </span>
                </template>
              </template>
            </div>
            <div class="template-preview-actions">
              <button
                v-if="tpl.virtual"
                type="button"
                class="btn btn-success btn-sm template-preview-action"
                @click="startCreateForScope(tpl.business_scope)"
              >
                快速创建
              </button>
              <button
                v-if="!tpl.virtual"
                type="button"
                class="btn btn-primary btn-sm template-preview-action"
                :data-template-action="tpl.category === 'label' ? 'view-labels-export' : tpl.category === 'word' ? 'open-word-info' : 'open-excel-preview'"
                :data-template-id="tpl.id"
                @click="previewTemplate(tpl)"
              >
                查看
              </button>
              <button
                v-if="!tpl.virtual"
                type="button"
                class="btn btn-secondary btn-sm template-preview-action"
                :data-template-action="tpl.category === 'label' ? 'open-print' : tpl.category === 'word' ? 'open-word-info' : 'open-excel-preview'"
                :data-template-id="tpl.id"
                @click="openTemplateTarget(tpl)"
              >
                打开
              </button>
              <button
                v-if="!tpl.virtual"
                type="button"
                class="btn btn-info btn-sm template-preview-action"
                :data-template-id="tpl.id"
                @click="editTemplate(tpl)"
              >
                编辑
              </button>
              <button
                v-if="!tpl.virtual && tpl.category === 'excel'"
                type="button"
                class="btn btn-secondary btn-sm template-preview-action"
                :data-template-id="tpl.id"
                @click="openReplaceTemplateDialog(tpl)"
              >
                替代到...
              </button>
              <button
                v-if="!tpl.virtual && canDeleteTemplate(tpl)"
                type="button"
                class="btn btn-danger btn-sm template-preview-action"
                :data-template-id="tpl.id"
                @click="confirmDeleteTemplate(tpl)"
              >
                删除
              </button>
            </div>
          </div>
</template>

<style scoped src="./template-preview.css"></style>
