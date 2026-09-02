<script setup lang="ts">
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import type { BatchAnalyzeCtx } from './assemble'

// 拆分自 BatchAnalyzeView.vue 模板（原第 381–457 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: BatchAnalyzeCtx }>()

const {
  showPreviewModal, previewGroupName, previewData, previewLoading,
} = props.tp
</script>

<template>
  <div v-if="showPreviewModal" class="modal active" @click.self="showPreviewModal = false">
    <div class="modal-content modal-lg">
      <div class="modal-header">
        <h4>模板预览 - {{ previewGroupName }}</h4>
        <span class="close" @click="showPreviewModal = false">×</span>
      </div>
      <div class="modal-body">
        <div v-if="previewLoading" class="loading-state">
          <span class="spinner"></span>
          正在提取网格数据...
        </div>
        <div v-else-if="previewData" class="preview-content">
          <div class="preview-info-card">
            <div class="preview-info-row">
              <span class="preview-info-label">分组名称：</span>
              <span class="preview-info-value">{{ previewData.groupInfo?.name }}</span>
            </div>
            <div class="preview-info-row">
              <span class="preview-info-label">模板类型：</span>
              <span class="preview-info-value">{{ previewData.groupInfo?.templateType }}</span>
            </div>
            <div class="preview-info-row">
              <span class="preview-info-label">匹配度：</span>
              <span class="preview-info-value score-{{ previewData.groupInfo?.matchScore >= 80 ? 'high' : previewData.groupInfo?.matchScore >= 60 ? 'medium' : 'low' }}">
                {{ previewData.groupInfo?.matchScore }}%
              </span>
            </div>
            <div class="preview-info-row">
              <span class="preview-info-label">工作表数量：</span>
              <span class="preview-info-value">{{ previewData.groupInfo?.sheetCount }} 个</span>
            </div>
            <div class="preview-info-row">
              <span class="preview-info-label">共性字段：</span>
              <span class="preview-info-value">{{ previewData.groupInfo?.commonFieldsCount }} 个</span>
            </div>
            <div class="preview-info-row">
              <span class="preview-info-label">差异字段：</span>
              <span class="preview-info-value diff-count">{{ previewData.groupInfo?.differenceFieldsCount }} 个</span>
            </div>
          </div>

          <div class="preview-source muted">
            来源：{{ previewData.preview_data?.file_name }} / {{ previewData.preview_data?.sheet_name }}
          </div>

          <ExcelPreview
            v-if="previewData.fields?.length"
            :fields="previewData.fields"
            :sample-rows="previewData.preview_data?.sample_rows || []"
            :title="previewGroupName"
            :grid-data="previewData.preview_data?.grid_preview || null"
            :rows="10"
            :columns="8"
          />

          <div v-if="previewData.groupInfo?.diffGridRows?.length > 0" class="diff-preview">
            <div class="diff-preview-title">差异字段预览：</div>
            <div class="diff-table-wrapper">
              <table class="diff-table">
                <tbody>
                  <tr v-for="(row, i) in previewData.groupInfo.diffGridRows" :key="i">
                    <td v-for="(cell, j) in row" :key="j" :class="{ 'diff-cell': i === 0 }">
                      {{ cell }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div v-else class="no-preview-data muted">
            暂无预览数据
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./batch-analyze.css"></style>
