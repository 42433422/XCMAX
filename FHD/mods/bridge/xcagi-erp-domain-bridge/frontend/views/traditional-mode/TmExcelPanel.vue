<script setup lang="ts">
import ExcelPreview from '@/components/template/ExcelPreview.vue'
import type { TraditionalModeCtx } from './assemble'

// 拆分自 TraditionalModeView.vue 模板（原第 231–418 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: TraditionalModeCtx }>()

const {
  excelPanel, setExcelMainTab, saveExcelEdit, closeExcelPanel,
  editSheetNames, editActiveRows, updateEditCell, formatEditCell,
  onTraditionalExtractSheetChange,
  inductPurchaseUnit, inductPurchaseUnitOptions, inductTargetScope, inductScopeOptions,
  inductRowsLoading, reloadInductRows, inductPreviewLoading, runInductPreview,
  inductCommitLoading, onInductCommitClick, inductRows, traditionalExtractTitle,
  inductRowsError, inductPreviewMessage, inductPreviewHasMissing, inductLastPreview,
} = props.tm
</script>

<template>
    <div v-if="excelPanel.visible" class="excel-editor-panel traditional-excel-panel">
      <div class="excel-editor-header">
        <div class="excel-editor-title-wrap">
          <span class="excel-editor-title">{{ excelPanel.fileName }}</span>
          <div class="excel-main-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              class="excel-tab"
              :class="{ 'is-active': excelPanel.mainTab === 'edit' }"
              :aria-selected="excelPanel.mainTab === 'edit'"
              @click="setExcelMainTab('edit')"
            >
              直接编辑
            </button>
            <button
              type="button"
              role="tab"
              class="excel-tab"
              :class="{ 'is-active': excelPanel.mainTab === 'induct' }"
              :aria-selected="excelPanel.mainTab === 'induct'"
              @click="setExcelMainTab('induct')"
            >
              手动归纳
            </button>
          </div>
          <span class="excel-editor-sub">
            {{
              excelPanel.mainTab === 'edit'
                ? '在下方表格中修改单元格，保存后写回服务器上的文件（多工作表会一并保存）。'
                : '选择客户与目标业务库，解析全表行后校验主数据；缺失时可勾选新增再入库。'
            }}
          </span>
        </div>
        <div class="excel-editor-actions">
          <button
            v-if="excelPanel.mainTab === 'edit'"
            type="button"
            class="btn btn-sm btn-success"
            :disabled="excelPanel.editSaving || !excelPanel.editContent || excelPanel.editLoading || excelPanel.editTruncated"
            @click="saveExcelEdit"
          >
            {{ excelPanel.editSaving ? '保存中…' : '保存' }}
          </button>
          <button type="button" class="btn btn-sm btn-secondary" @click="closeExcelPanel">关闭</button>
        </div>
      </div>

      <template v-if="excelPanel.mainTab === 'edit'">
        <div v-if="editSheetNames.length" class="traditional-sheet-bar">
          <label for="traditional-edit-sheet">工作表</label>
          <select
            id="traditional-edit-sheet"
            class="form-control traditional-sheet-select"
            v-model="excelPanel.editActiveSheet"
            :disabled="excelPanel.editLoading"
          >
            <option v-for="s in editSheetNames" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>
        <div
          v-if="excelPanel.editTruncated && excelPanel.editTruncatedHint"
          class="excel-panel-state excel-panel-warn"
          role="status"
        >{{ excelPanel.editTruncatedHint }}</div>
        <div v-if="excelPanel.editLoading" class="excel-panel-state">正在加载工作簿…</div>
        <div v-else-if="excelPanel.editError" class="excel-panel-state excel-panel-error">{{ excelPanel.editError }}</div>
        <div v-else-if="excelPanel.editContent && editActiveRows.length" class="excel-editor-body traditional-edit-body">
          <table class="excel-table">
            <tbody>
              <tr v-for="(row, rIdx) in editActiveRows" :key="'er-' + excelPanel.editActiveSheet + '-' + rIdx">
                <td
                  v-for="(cell, cIdx) in row"
                  :key="'ec-' + rIdx + '-' + cIdx"
                  contenteditable="true"
                  spellcheck="false"
                  @blur="updateEditCell(rIdx, cIdx, $event)"
                >{{ formatEditCell(cell) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="excelPanel.editContent" class="excel-panel-state empty-excel">当前工作表无数据行</div>
      </template>

      <template v-else>
        <div v-if="excelPanel.sheetNames.length" class="traditional-sheet-bar">
          <label for="traditional-excel-sheet">工作表</label>
          <select
            id="traditional-excel-sheet"
            class="form-control traditional-sheet-select"
            v-model="excelPanel.selectedSheetName"
            :disabled="excelPanel.loading"
            @change="onTraditionalExtractSheetChange"
          >
            <option v-for="s in excelPanel.sheetNames" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>

        <div class="induct-toolbar" v-if="!excelPanel.loading && !excelPanel.error && excelPanel.extractResult">
          <div class="induct-toolbar-row">
            <label class="induct-label">客户</label>
            <input
              v-model.trim="inductPurchaseUnit"
              class="form-control induct-select"
              list="traditional-induct-pu-datalist"
              placeholder="从列表选择或直接输入新单位"
              autocomplete="off"
            >
            <datalist id="traditional-induct-pu-datalist">
              <option v-for="u in inductPurchaseUnitOptions" :key="'pu-dl-' + u" :value="u" />
            </datalist>
          </div>
          <div class="induct-toolbar-row">
            <label class="induct-label">目标业务库</label>
            <select v-model="inductTargetScope" class="form-control induct-select">
              <option v-for="opt in inductScopeOptions" :key="opt.key" :value="opt.key">
                {{ opt.label }}
              </option>
            </select>
          </div>
          <div class="induct-toolbar-actions">
            <button
              type="button"
              class="btn btn-sm btn-secondary"
              :disabled="inductRowsLoading || excelPanel.loading"
              @click="reloadInductRows"
            >
              {{ inductRowsLoading ? '加载行数据…' : '重新加载行数据' }}
            </button>
            <button
              type="button"
              class="btn btn-sm btn-primary"
              :disabled="inductPreviewLoading || inductRowsLoading || !inductRows.length"
              @click="runInductPreview"
            >
              {{ inductPreviewLoading ? '校验中…' : '校验数据' }}
            </button>
            <button
              type="button"
              class="btn btn-sm btn-success"
              :disabled="inductCommitLoading || inductRowsLoading || !inductRows.length || !inductLastPreview"
              @click="onInductCommitClick"
            >
              {{ inductCommitLoading ? '入库中…' : '确认入库' }}
            </button>
          </div>
          <div class="induct-meta muted" v-if="inductRows.length">
            已加载 {{ inductRows.length }} 行（当前 Sheet：{{ traditionalExtractTitle }}）
          </div>
          <div v-if="inductRowsError" class="excel-panel-error induct-inline-error">{{ inductRowsError }}</div>
          <div v-if="inductPreviewMessage" class="induct-preview-msg" :class="{ warn: inductPreviewHasMissing }">
            {{ inductPreviewMessage }}
          </div>
        </div>

        <div v-if="excelPanel.loading" class="excel-panel-state">
          <div class="extract-progress-title">正在提取网格…</div>
          <div class="extract-progress-track" role="progressbar" :aria-valuenow="excelPanel.extractProgressPercent" aria-valuemin="0" aria-valuemax="100">
            <div class="extract-progress-fill" :style="{ width: Math.min(100, Math.max(0, excelPanel.extractProgressPercent)) + '%' }" />
          </div>
          <div v-if="excelPanel.extractProgressStep" class="extract-progress-step muted">{{ excelPanel.extractProgressStep }}</div>
          <div class="induct-loading-hint muted">
            若刚启动后端，首次请求可能需数十秒（服务初始化/模型加载）。请确认已运行 <code>python run.py</code>（5000）且 Vite 代理指向该端口。
          </div>
        </div>
        <div v-else-if="excelPanel.error" class="excel-panel-state excel-panel-error">{{ excelPanel.error }}</div>
        <div v-else-if="excelPanel.extractResult" class="excel-editor-body traditional-excel-body">
          <div v-if="(excelPanel.extractResult.fields || []).length" class="traditional-field-strip">
            <div class="traditional-field-title">识别字段（{{ (excelPanel.extractResult.fields || []).length }}）</div>
            <ul class="traditional-field-list">
              <li v-for="(field, idx) in excelPanel.extractResult.fields" :key="(field.label || field.name || '') + '-' + idx">
                <span class="field-idx">{{ idx + 1 }}.</span>
                {{ field.label || field.name || '未命名' }}
              </li>
            </ul>
          </div>
          <ExcelPreview
            :fields="excelPanel.extractResult.fields || []"
            :sample-rows="excelPanel.extractResult?.preview_data?.sample_rows || []"
            :title="traditionalExtractTitle + ' 真实网格'"
            :grid-data="excelPanel.extractResult?.preview_data?.grid_preview || undefined"
            :rows="12"
            :columns="10"
          />
        </div>
      </template>
    </div>
</template>

<style scoped src="./traditional-mode.css"></style>
