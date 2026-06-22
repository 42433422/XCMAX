<template>
  <div class="page-view wf-viz-page" id="view-workflow-visualization">
    <div class="page-content wf-viz-inner">
      <header class="wf-viz-header">
        <div>
          <h2 class="wf-viz-title">流程可视化</h2>
          <p class="wf-viz-sub">以编制图谱为主源，可视化六部门员工、流程派发和执行回写是否在同一条链路上。</p>
        </div>
        <div class="wf-viz-header-actions">
          <router-link :to="{ name: 'duty-roster-graph', query: { view: 'department' } }" class="wf-viz-back">编制图谱</router-link>
          <router-link :to="{ name: 'workflow-employee-space' }" class="wf-viz-back">员工空间</router-link>
        </div>
      </header>

      <DutyRosterWorkflowLoopView surface="workflow-visualization" />
    </div>
  </div>
</template>

<script setup lang="ts">
import DutyRosterWorkflowLoopView from '@/components/workflow/DutyRosterWorkflowLoopView.vue'
</script>

<style scoped>
.wf-viz-page {
  background: #f8fafc;
  min-height: 100%;
}

.wf-viz-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 20px 20px 48px;
}

.wf-viz-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.wf-viz-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
}

.wf-viz-sub {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.55;
  max-width: 52rem;
}

.wf-viz-header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.wf-viz-back {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 700;
  color: #1d4ed8;
  text-decoration: none;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid #93c5fd;
  background: #fff;
}

.wf-viz-back:hover {
  background: #dbeafe;
}
</style>
