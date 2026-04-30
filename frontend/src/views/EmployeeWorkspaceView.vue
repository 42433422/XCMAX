<template>
  <div class="page-view" id="view-workflow-employee-space">
    <div class="page-content">
      <header class="ews-page-head">
        <div>
          <h2 class="ews-page-title">员工空间</h2>
          <p class="ews-page-sub">像素入口与工位实况；数据与副窗工作流开关、智能对话任务快照同步。</p>
        </div>
        <router-link :to="{ name: 'other-tools' }" class="btn btn-secondary btn-sm">返回员工工作流管理</router-link>
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.ews-page-title {
  margin: 0 0 6px;
  font-size: 1.35rem;
  font-weight: 700;
  color: #111827;
}

.ews-page-sub {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #6b7280;
  max-width: 52rem;
}
</style>
