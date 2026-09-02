<template>
  <div class="approval-flow-management">
    <div class="view-header">
      <h2>审批流程管理</h2>
      <p class="subtitle">创建和管理多级审批流程</p>
    </div>

    <FmFlowList :tm="tm" />
    <FmFlowModal :tm="tm" />
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./approval-flow-management/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import FmFlowList from './approval-flow-management/FmFlowList.vue'
import FmFlowModal from './approval-flow-management/FmFlowModal.vue'
import { assembleApprovalFlowManagement } from './approval-flow-management/assemble'

const tm = assembleApprovalFlowManagement()
</script>

<style scoped src="./approval-flow-management/approval-flow-management.css"></style>
