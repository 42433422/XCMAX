<template>
  <div class="approval-workspace-view">
    <div class="view-header">
      <h2>审批工作台</h2>
      <p class="subtitle">处理待审批事项，跟踪审批进度</p>
    </div>

    <AwStatsCards :tm="tm" />
    <AwPendingList :tm="tm" />
    <AwInitiatedList :tm="tm" />
    <AwDetailModal :tm="tm" />
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./approval-workspace/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import AwStatsCards from './approval-workspace/AwStatsCards.vue'
import AwPendingList from './approval-workspace/AwPendingList.vue'
import AwInitiatedList from './approval-workspace/AwInitiatedList.vue'
import AwDetailModal from './approval-workspace/AwDetailModal.vue'
import { assembleApprovalWorkspace } from './approval-workspace/assemble'

const tm = assembleApprovalWorkspace()
</script>

<style scoped src="./approval-workspace/approval-workspace.css"></style>
