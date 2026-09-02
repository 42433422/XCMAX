<script setup lang="ts">
import { useBatchAnalyzeStore, type SheetGroup } from '@/stores/batchAnalyze'
import type { BatchAnalyzeCtx } from './assemble'

// 拆分自 BatchAnalyzeView.vue 模板（原第 108–225、230–347 行，匹配/通用分组卡片结构相同）；模板逐字迁移，行为不变。
const props = defineProps<{
  tp: BatchAnalyzeCtx
  group: SheetGroup
  unknown?: boolean
}>()

const store = useBatchAnalyzeStore()

const {
  showAllGroups, scoreClass, selectedGroupIds, toggleGroupSelect,
  editGroupName, availableTemplates, onTemplateChange,
  previewGroup, viewGroupDetail, selectGroup, showMoveSheetDialog,
} = props.tp
</script>

<template>
  <div
    class="group-card"
    :class="{
      'unknown-group-card': unknown,
      selected: store.selectedGroupId === group.id,
      'group-selected': selectedGroupIds.includes(group.id)
    }"
    @click="selectGroup(group.id)"
  >
    <div class="group-header">
      <div class="group-select" @click.stop>
        <input
          type="checkbox"
          :checked="selectedGroupIds.includes(group.id)"
          @change="toggleGroupSelect(group.id)"
        >
      </div>
      <div class="group-info">
        <span class="group-name" @click.stop="editGroupName(group)">{{ group.name }}</span>
        <span class="group-badge" :class="`category-${group.category}`">
          {{ group.templateType }}
        </span>
        <span class="match-score" :class="scoreClass(group.matchScore)">
          {{ group.matchScore }}% 匹配
        </span>
      </div>
      <div class="group-meta muted">
        {{ group.matchedSheets.length }} 个工作表
      </div>
    </div>

    <div v-if="showAllGroups || store.selectedGroupId === group.id" class="group-body">
      <div class="sheet-list">
        <div class="list-title muted">来源工作表：</div>
        <div
          v-for="(sheet, idx) in group.matchedSheets"
          :key="idx"
          class="sheet-item"
        >
          <span class="sheet-icon">📄</span>
          <span class="sheet-file">{{ sheet.fileName }}</span>
          <span class="sheet-arrow">→</span>
          <span class="sheet-name">{{ sheet.sheetName }}</span>
          <span class="sheet-rows muted">({{ sheet.rowCount }} 行)</span>
          <button
            class="btn btn-xs btn-outline move-btn"
            title="移动到其他分组"
            @click.stop="showMoveSheetDialog(group, sheet, idx)"
          >
            移动
          </button>
        </div>
      </div>

      <div class="fields-section">
        <div class="common-fields">
          <div class="fields-title">共性字段：</div>
          <div class="field-tags">
            <span
              v-for="field in group.commonFields"
              :key="field"
              class="field-tag common"
            >
              {{ field }}
            </span>
          </div>
        </div>

        <div v-if="group.differenceFields.length > 0" class="diff-fields">
          <div class="fields-title">差异字段：</div>
          <div class="field-tags">
            <span
              v-for="field in group.differenceFields"
              :key="field"
              class="field-tag diff"
            >
              {{ field }}
            </span>
          </div>
        </div>
      </div>

      <div class="template-section">
        <div class="template-select-row">
          <label>推荐模板：</label>
          <select
            v-model="group.recommendedTemplateId"
            class="form-control"
            @change="onTemplateChange(group)"
          >
            <option value="">-- 选择模板 --</option>
            <option
              v-for="tmpl in availableTemplates"
              :key="tmpl.id"
              :value="tmpl.id"
            >
              {{ tmpl.name }} ({{ tmpl.templateType }})
            </option>
          </select>
          <span v-if="group.recommendedTemplateName" class="template-name">
            {{ group.recommendedTemplateName }}
          </span>
        </div>
      </div>

      <div class="group-actions">
        <button class="btn btn-sm btn-primary" @click.stop="previewGroup(group)">
          提取预览
        </button>
        <button class="btn btn-sm btn-secondary" @click.stop="viewGroupDetail(group)">
          查看详情
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="./batch-analyze.css"></style>
