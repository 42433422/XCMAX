<template>
  <div class="page-view" id="view-template-preview">
    <div class="page-content">
      <div class="page-header">
        <h2>模板预览</h2>
        <p class="muted" style="margin:0;font-size:13px;">展示导出用 Excel 与 Word 模板：可按业务分组管理，也可选「自定义」自由新建任意模板；Word 若有「适用业务」或可从文件名推断则归入对应分组，否则在各分组中均显示。</p>
      </div>

      <div class="template-preview-toolbar" style="display:flex;gap:8px;align-items:center;margin:12px 0 16px;flex-wrap:wrap;">
        <button
          v-for="tab in scopeTabs"
          :key="tab.key"
          type="button"
          class="btn btn-sm"
          :class="activeScopeTab === tab.key ? 'btn-primary' : 'btn-secondary'"
          @click="activeScopeTab = tab.key"
        >
          {{ tab.label }}
        </button>
        <button type="button" class="btn btn-sm btn-secondary" @click="refreshTemplates">刷新</button>
        <button type="button" class="btn btn-sm btn-primary" @click="openCreateModal()">
          <i class="fa fa-plus" aria-hidden="true"></i> 创建模板
        </button>
      </div>
      <div class="template-rule-hint">
        模板替换会校验功能词条完整性：Excel 按表头/单元格词条；Word 按正文与页眉页脚中的占位符（如 <span v-pre>{{产品型号}}</span>）；须覆盖对应业务的全部必备词条后才允许保存。
      </div>
      <div class="grid-tool-card">
        <div class="grid-tool-title">Excel 网格映射工具</div>
        <div class="grid-tool-actions">
          <input ref="gridToolFileInput" type="file" accept=".xlsx,.xls" @change="onGridToolFileSelected">
          <button type="button" class="btn btn-sm btn-primary" :disabled="!gridToolFile || extractingGrid" @click="extractGridFromExcel">
            {{ extractingGrid ? '提取中...' : '上传提取模板网格' }}
          </button>
          <button v-if="gridToolResult" type="button" class="btn btn-sm btn-secondary" @click="openGridToolPreview">
            查看提取结果
          </button>
        </div>
        <div v-if="gridToolResult" class="muted" style="font-size:12px;margin-top:6px;">
          已提取：{{ gridToolResult.template_name || 'Excel模板' }} | 字段 {{ (gridToolResult.fields || []).length }} 项
        </div>
      </div>

      <div v-if="loading" class="muted">模板加载中...</div>
      <div v-else-if="error" class="muted">{{ error }}</div>
      <div v-else-if="filteredTemplates.length === 0" class="muted">当前业务范围暂无导出模板</div>

      <div v-else class="template-preview-section">
        <div class="template-preview-grid">
          <TpTemplateCard
            v-for="tpl in filteredTemplates"
            :key="tpl.id"
            :tp="tp"
            :tpl="tpl"
          />
        </div>
      </div>
    </div>

    <TpCreateModal :tp="tp" />
    <TpPreviewModal :tp="tp" />
    <TpEditModal :tp="tp" />
    <TpReplaceModal :tp="tp" />
    <TpGridToolModal :tp="tp" />
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./template-preview/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import TpTemplateCard from './template-preview/TpTemplateCard.vue'
import TpCreateModal from './template-preview/TpCreateModal.vue'
import TpPreviewModal from './template-preview/TpPreviewModal.vue'
import TpEditModal from './template-preview/TpEditModal.vue'
import TpReplaceModal from './template-preview/TpReplaceModal.vue'
import TpGridToolModal from './template-preview/TpGridToolModal.vue'
import { assembleTemplatePreview } from './template-preview/assemble'

defineOptions({ name: 'TemplatePreviewView' })

const tp = assembleTemplatePreview()

const {
  scopeTabs, activeScopeTab, refreshTemplates, openCreateModal,
  onGridToolFileSelected, gridToolFile, extractingGrid, extractGridFromExcel,
  gridToolResult, openGridToolPreview,
  loading, error, filteredTemplates,
} = tp
</script>

<style scoped src="./template-preview/template-preview.css"></style>
