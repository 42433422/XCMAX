<template>
  <div class="page-view" id="view-workflow-employee-space">
    <div class="page-content">
      <header class="ews-page-head">
        <div class="ews-page-head-text">
          <h2 class="ews-page-title">员工空间</h2>
          <p class="ews-page-sub">像素入口与工位实况；数据与副窗工作流开关、智能对话任务快照同步。</p>
        </div>
      </header>

      <EmployeeWorkspaceScene />
    </div>
  </div>
</template>

<script setup lang="ts">
import EmployeeWorkspaceScene from '@/components/workflow/EmployeeWorkspaceScene.vue'
</script>

<style scoped>
.ews-page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.ews-page-title {
  margin: 0 0 6px;
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
}

.ews-page-sub {
  margin: 0;
  font-size: 13px;
  line-height: 1.45;
  color: #64748b;
  max-width: 52rem;
}
</style>
