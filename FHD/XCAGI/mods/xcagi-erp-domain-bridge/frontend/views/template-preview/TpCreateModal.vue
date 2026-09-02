<script setup lang="ts">
import FileUploadStep from '@/components/template/FileUploadStep.vue'
import FieldEditor from '@/components/template/FieldEditor.vue'
import type { TemplatePreviewCtx } from './assemble'

// 拆分自 TemplatePreviewView.vue 模板（原第 190–294 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: TemplatePreviewCtx }>()

const {
  showCreateModal, closeCreateModal, createStep, templateScope, scopeOptions, isCustomScope,
  customScopeLabel, customTemplateType, selectedScopeRequiredTerms, templateName, selectedFile,
  uploadValidationResult, editorFields, editorTemplateType, analyzing, progressMessage,
  progressPercent, progressStep, prevStep, canProceedStep1, nextStep, saveTemplate,
  onUpdateField, onDeleteField, onAddField, onFieldsChange, onFileSelected,
} = props.tp
</script>

<template>
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
        <div class="modal-content" style="max-width:900px;">
          <div class="modal-header">
            <h3><i class="fa fa-folder-open-o" aria-hidden="true"></i> 创建新模板</h3>
            <button type="button" class="modal-close" @click="closeCreateModal">&times;</button>
          </div>
          <div class="modal-body">
            <div v-if="createStep === 1" class="create-step">
              <div class="scope-selector-row">
                <label>适用业务</label>
                <select v-model="templateScope" class="form-control">
                  <option v-for="option in scopeOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
                <div v-if="isCustomScope" class="custom-scope-fields">
                  <input
                    v-model="customScopeLabel"
                    type="text"
                    class="form-control"
                    placeholder="自定义业务名称（可选），如：考勤汇总、合同审批"
                  />
                  <input
                    v-model="customTemplateType"
                    type="text"
                    class="form-control"
                    placeholder="模板类型（可选），默认用模板名称"
                  />
                  <div class="muted scope-required-terms">自定义业务不强制必备词条，可自由上传各类模板。</div>
                </div>
                <div v-else class="muted scope-required-terms">
                  必备词条：{{ selectedScopeRequiredTerms.length ? selectedScopeRequiredTerms.join('、') : '无' }}
                  <span v-if="selectedScopeRequiredTerms.length">（缺少时可选择仍继续创建）</span>
                </div>
              </div>
              <FileUploadStep
                ref="uploadStep"
                :template-name="templateName"
                :selected-file="selectedFile"
                @update:template-name="templateName = $event"
                @update:selected-file="selectedFile = $event"
                @file-selected="onFileSelected"
              />
              <div v-if="uploadValidationResult && !uploadValidationResult.valid" class="validation-warning">
                当前模板缺少词条：{{ uploadValidationResult.missing.join('、') }}
              </div>
            </div>

            <div v-else-if="createStep === 2" class="create-step" style="min-height: 650px;">
              <FieldEditor
                ref="fieldEditor"
                :fields="editorFields"
                :template-type="editorTemplateType"
                @update-field="onUpdateField"
                @delete-field="onDeleteField"
                @add-field="onAddField"
                @fields-change="onFieldsChange"
              />
            </div>
          </div>

          <!-- 分析进度条 -->
          <div v-if="analyzing" class="analyzing-progress">
            <div class="progress-info">
              <span>{{ progressMessage }}</span>
              <span>{{ progressPercent }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
            </div>
            <div class="progress-steps">
              <div :class="['step', { active: progressStep >= 1 }]">
                <span class="step-icon" aria-hidden="true"><i class="fa fa-upload"></i></span>
                <span class="step-label">上传</span>
              </div>
              <div :class="['step', { active: progressStep >= 2 }]">
                <span class="step-icon" aria-hidden="true"><i class="fa fa-search"></i></span>
                <span class="step-label">分析结构</span>
              </div>
              <div :class="['step', { active: progressStep >= 3 }]">
                <span class="step-icon" aria-hidden="true"><i class="fa fa-th"></i></span>
                <span class="step-label">生成预览</span>
              </div>
              <div :class="['step', { active: progressStep >= 4 }]">
                <span class="step-icon" aria-hidden="true"><i class="fa fa-check-circle-o"></i></span>
                <span class="step-label">完成</span>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button v-if="createStep > 1" type="button" class="btn btn-secondary" @click="prevStep">
              <i class="fa fa-arrow-left" aria-hidden="true"></i> 上一步
            </button>
            <button type="button" class="btn btn-secondary" @click="closeCreateModal">取消</button>
            <button v-if="createStep === 1" type="button" class="btn btn-primary" @click="nextStep" :disabled="!canProceedStep1 || analyzing">
              <span v-if="analyzing">分析中...</span>
              <span v-else>下一步 <i class="fa fa-arrow-right" aria-hidden="true"></i></span>
            </button>
            <button v-else-if="createStep === 2" type="button" class="btn btn-success" @click="saveTemplate">
              <i class="fa fa-check" aria-hidden="true"></i> 保存模板
            </button>
          </div>
        </div>
      </div>
</template>

<style scoped src="./template-preview.css"></style>
