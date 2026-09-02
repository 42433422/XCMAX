<script setup lang="ts">
// 拆分自 SelfEvolutionLoopRuntimePanel.vue 模板（原 run 时间线区块）；模板逐字迁移，行为不变。
defineProps<{
  runTimeline: any
}>()
</script>

<template>
    <div v-if="runTimeline" class="selp-timeline" aria-label="自进化 run 时间线">
      <div class="selp-timeline-head">
        <span>Run 时间线</span>
        <strong>#{{ runTimeline.runId || 'unknown' }}{{ runTimeline.open ? ' · 运行中' : '' }}</strong>
      </div>
      <ol class="selp-timeline-list">
        <li v-for="(item, idx) in runTimeline.items" :key="`${item.phase}-${item.step}-${idx}`" class="selp-timeline-item">
          <span class="selp-timeline-index">{{ idx + 1 }}</span>
          <div class="selp-timeline-main">
            <strong>{{ item.label || item.step || item.phase || '事件' }}</strong>
            <span>
              <template v-if="item.employee_id">{{ item.employee_id }}</template>
              <template v-if="item.role_label"> · {{ item.role_label }}</template>
              <template v-if="item.status"> · {{ item.status }}</template>
            </span>
            <small v-if="item.roster_label || item.department_label" class="selp-timeline-roster" :class="{ 'selp-timeline-roster--outside': item.roster_status === 'out_of_roster' }">
              {{ item.roster_label || item.roster_status || '编制未知' }}
              <template v-if="item.duty_registered_label"> · {{ item.duty_registered_label }}</template>
              <template v-if="item.department_label"> · {{ item.department_label }}</template>
            </small>
            <small>
              <template v-if="item.para_task_id">Para {{ item.para_task_id }}</template>
              <template v-if="item.branch"> · {{ item.branch }}</template>
              <template v-if="item.qa_verdict"> · QA {{ item.qa_verdict }}</template>
              <template v-if="item.review_max_severity"> · Review {{ item.review_max_severity }}</template>
              <template v-if="item.created_at"> · {{ item.created_at }}</template>
            </small>
            <div v-if="item.qa_verdict || item.review_max_severity" class="selp-report">
              <span v-if="item.qa_verdict" class="selp-report-pill" :class="item.qa_verdict === 'PASS' ? 'selp-report-pill--ok' : 'selp-report-pill--bad'">
                QA {{ item.qa_verdict }}
              </span>
              <span v-if="item.qa_target_branch_available !== null && item.qa_target_branch_available !== undefined" class="selp-report-pill">
                branch {{ item.qa_target_branch_available ? 'ok' : 'missing' }}
              </span>
              <span v-if="item.qa_risk_class" class="selp-report-pill">risk {{ item.qa_risk_class }}</span>
              <span v-if="item.review_max_severity" class="selp-report-pill">review {{ item.review_max_severity }}</span>
              <span v-if="Array.isArray(item.qa_tested_commands) && item.qa_tested_commands.length" class="selp-report-pill">
                tests {{ item.qa_tested_commands.length }}
              </span>
              <span v-if="Array.isArray(item.qa_blocking_findings) && item.qa_blocking_findings.length" class="selp-report-pill selp-report-pill--bad">
                blockers {{ item.qa_blocking_findings.length }}
              </span>
              <span v-if="Array.isArray(item.review_findings) && item.review_findings.length" class="selp-report-pill">
                findings {{ item.review_findings.length }}
              </span>
              <span v-if="Array.isArray(item.review_blocking_findings) && item.review_blocking_findings.length" class="selp-report-pill selp-report-pill--bad">
                review blockers {{ item.review_blocking_findings.length }}
              </span>
              <template v-if="item.review_dimensions && typeof item.review_dimensions === 'object'">
                <span
                  v-for="dimKey in ['security', 'business_logic', 'performance']"
                  :key="`${item.run_id || ''}-${dimKey}`"
                  class="selp-report-pill"
                  :class="String(item.review_dimensions?.[dimKey]?.status || '').toLowerCase() === 'fail' ? 'selp-report-pill--bad' : 'selp-report-pill--ok'"
                >
                  {{ dimKey }} {{ item.review_dimensions?.[dimKey]?.status || 'n/a' }}
                </span>
              </template>
            </div>
          </div>
        </li>
      </ol>
    </div>
</template>

<style scoped src="./self-evolution-loop-runtime.css"></style>
