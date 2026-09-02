<template>
  <!-- 自 WorkflowView.vue 机械迁出的沙盒报告只读展示块（行为不变） -->
  <div class="sandbox-report">
    <div class="sandbox-report-row">
      <span :class="['sandbox-pill', sandboxReport.ok ? 'ok' : 'err']">{{ sandboxReport.ok ? '通过' : '未通过' }}</span>
      <span v-if="sandboxReport.validate_only" class="muted">仅校验模式</span>
      <span v-if="lastRunMeta.mode === 'real'" class="sandbox-pill sm">Real</span>
      <span v-else-if="lastRunMeta.mode === 'mock'" class="sandbox-pill sm">Mock</span>
    </div>
    <div v-if="lastRunMeta.mode === 'real'" class="sandbox-block">
      <h4>真实测试前置检查</h4>
      <p class="muted">{{ realPrecheckSummary }}</p>
      <ul v-if="lastRunMeta.precheck?.issues?.length">
        <li v-for="(it, i) in lastRunMeta.precheck.issues" :key="'pc' + i">{{ it }}</li>
      </ul>
    </div>
    <div v-if="sandboxReport.errors?.length" class="sandbox-block">
      <h4>错误</h4>
      <ul><li v-for="(err, i) in sandboxReport.errors" :key="'e'+i">{{ err }}</li></ul>
    </div>
    <div v-if="sandboxReport.warnings?.length" class="sandbox-block">
      <h4>提示</h4>
      <ul><li v-for="(w, i) in sandboxReport.warnings" :key="'w'+i">{{ w }}</li></ul>
    </div>
    <div v-if="sandboxReport.steps?.length" class="sandbox-block">
      <h4>执行轨迹（{{ sandboxReport.steps.length }} 步）</h4>
      <div v-for="st in sandboxReport.steps" :key="st.order" class="sandbox-step">
        <div class="sandbox-step-h">
          <span class="mono">#{{ st.order }}</span>
          <span>{{ st.node_name }}</span>
          <span class="muted mono">{{ st.node_type }}</span>
          <span v-if="st.duration_ms != null" class="muted">{{ st.duration_ms }} ms</span>
          <span v-if="st.mock_employee" class="sandbox-pill sm">Mock</span>
        </div>
        <details class="sandbox-details">
          <summary>变量快照 / 输出</summary>
          <pre class="sandbox-pre">{{ JSON.stringify({ input: st.input_snapshot, output_delta: st.output_delta, edge: st.edge_taken, branches: st.condition_branches }, null, 2) }}</pre>
        </details>
      </div>
    </div>
    <div v-if="sandboxReport.output && Object.keys(sandboxReport.output).length" class="sandbox-block">
      <h4>最终上下文（可序列化摘要）</h4>
      <pre class="sandbox-pre">{{ JSON.stringify(sandboxReport.output, null, 2) }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { WorkflowSandboxResponse } from '../../types/api'
import type { RealPrecheck } from './workflowTypes'

defineProps<{
  sandboxReport: WorkflowSandboxResponse
  lastRunMeta: { mode: string; startedAt: string; precheck: RealPrecheck | null }
  realPrecheckSummary: string
}>()
</script>
