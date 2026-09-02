<script setup lang="ts">
import type { BatchAnalyzeCtx } from './assemble'

// 拆分自 BatchAnalyzeView.vue 模板（原第 459–487 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: BatchAnalyzeCtx }>()

const {
  showMoveModal, moveSourceSheet, moveSourceGroup, moveTargetGroups,
  closeMoveModal, moveSheetToGroup, createNewGroupAndMove,
} = props.tp
</script>

<template>
  <div v-if="showMoveModal" class="modal active" @click.self="closeMoveModal">
    <div class="modal-content modal-sm">
      <div class="modal-header">
        <h4>移动工作表</h4>
        <span class="close" @click="closeMoveModal">×</span>
      </div>
      <div class="modal-body">
        <div class="move-info">
          <p>将 <strong>{{ moveSourceSheet?.sheetName }}</strong> 从 <strong>{{ moveSourceGroup?.name }}</strong> 移动到：</p>
        </div>
        <div class="move-options">
          <div
            v-for="targetGroup in moveTargetGroups"
            :key="targetGroup.id"
            class="move-option-item"
            :class="{ disabled: targetGroup.id === moveSourceGroup?.id }"
            @click="targetGroup.id !== moveSourceGroup?.id && moveSheetToGroup(targetGroup.id)"
          >
            <span class="move-option-name">{{ targetGroup.name }}</span>
            <span class="move-option-count muted">{{ targetGroup.matchedSheets.length }} 个工作表</span>
          </div>
        </div>
        <div class="move-actions">
          <button class="btn btn-secondary btn-sm" @click="closeMoveModal">取消</button>
          <button class="btn btn-outline btn-sm" @click="createNewGroupAndMove">创建新分组</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./batch-analyze.css"></style>
