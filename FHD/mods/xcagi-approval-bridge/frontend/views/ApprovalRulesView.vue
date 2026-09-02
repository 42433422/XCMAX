<template>
  <div class="approval-rules-view">
    <div class="view-header">
      <h2>审批流程规则</h2>
      <p class="subtitle">配置工作流中需要审批的操作节点</p>
    </div>

    <RlRulesPanel :tm="tm" />
    <RlPendingApprovals :tm="tm" />
    <RlEditModal :tm="tm" />
  </div>
</template>

<script setup>
// 原超大 SFC 已拆分至 ./approval-rules/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import RlRulesPanel from './approval-rules/RlRulesPanel.vue'
import RlPendingApprovals from './approval-rules/RlPendingApprovals.vue'
import RlEditModal from './approval-rules/RlEditModal.vue'
import { assembleApprovalRules } from './approval-rules/assemble'

const tm = assembleApprovalRules()
</script>

<style scoped src="./approval-rules/approval-rules.css"></style>
