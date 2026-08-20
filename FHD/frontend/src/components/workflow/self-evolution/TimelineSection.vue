<script setup lang="ts">
import type { AnyRecord } from '@/composables/useLoopRuntimePanel'

export type RunTimeline = {
  runId: string
  open: boolean
  items: AnyRecord[]
} | null

defineProps<{
  timeline: RunTimeline
  reviewDimStatus: (item: AnyRecord, dimKey: string) => string
  reviewDimFailed: (item: AnyRecord, dimKey: string) => boolean
}>()
</script>

<template>
  <div v-if="timeline" class="selp-timeline" aria-label="自进化运行时间线">
    <div class="selp-timeline-head">
      <span>运行时间线</span>
      <strong>#{{ timeline.runId || '未知' }}{{ timeline.open ? ' · 运行中' : '' }}</strong>
    </div>
    <ol class="selp-timeline-list">
      <li v-for="(item, idx) in timeline.items" :key="`${item.phase}-${item.step}-${idx}`" class="selp-timeline-item">
        <span class="selp-timeline-index">{{ idx + 1 }}</span>
        <div class="selp-timeline-main">
          <strong>{{ item.label || item.step || item.phase || '事件' }}</strong>
          <span>
            <template v-if="item.employee_id">{{ item.employee_id }}</template>
            <template v-if="item.role_label"> · {{ item.role_label }}</template>
            <template v-if="item.status"> · {{ item.status }}</template>
          </span>
          <small
            v-if="item.roster_label || item.department_label"
            class="selp-timeline-roster"
            :class="{ 'selp-timeline-roster--outside': item.roster_status === 'out_of_roster' }"
          >
            {{ item.roster_label || item.roster_status || '排班未知' }}
            <template v-if="item.duty_registered_label"> · {{ item.duty_registered_label }}</template>
            <template v-if="item.department_label"> · {{ item.department_label }}</template>
          </small>
          <small>
            <template v-if="item.para_task_id">Para {{ item.para_task_id }}</template>
            <template v-if="item.branch"> · {{ item.branch }}</template>
            <template v-if="item.qa_verdict"> · QA {{ item.qa_verdict }}</template>
            <template v-if="item.review_max_severity"> · 审查 {{ item.review_max_severity }}</template>
            <template v-if="item.created_at"> · {{ item.created_at }}</template>
          </small>
          <div v-if="item.qa_verdict || item.review_max_severity" class="selp-report">
            <span
              v-if="item.qa_verdict"
              class="selp-report-pill"
              :class="item.qa_verdict === 'PASS' ? 'selp-report-pill--ok' : 'selp-report-pill--bad'"
            >
              QA {{ item.qa_verdict }}
            </span>
            <span v-if="item.qa_target_branch_available !== null && item.qa_target_branch_available !== undefined" class="selp-report-pill">
              分支 {{ item.qa_target_branch_available ? '正常' : '缺失' }}
            </span>
            <span v-if="item.qa_risk_class" class="selp-report-pill">风险 {{ item.qa_risk_class }}</span>
            <span v-if="item.review_max_severity" class="selp-report-pill">审查 {{ item.review_max_severity }}</span>
            <span v-if="Array.isArray(item.qa_tested_commands) && item.qa_tested_commands.length" class="selp-report-pill">
              测试 {{ item.qa_tested_commands.length }}
            </span>
            <span
              v-if="Array.isArray(item.qa_blocking_findings) && item.qa_blocking_findings.length"
              class="selp-report-pill selp-report-pill--bad"
            >
              阻断项 {{ item.qa_blocking_findings.length }}
            </span>
            <span v-if="Array.isArray(item.review_findings) && item.review_findings.length" class="selp-report-pill">
              发现 {{ item.review_findings.length }}
            </span>
            <span
              v-if="Array.isArray(item.review_blocking_findings) && item.review_blocking_findings.length"
              class="selp-report-pill selp-report-pill--bad"
            >
              审阻断 {{ item.review_blocking_findings.length }}
            </span>
            <template v-if="item.review_dimensions && typeof item.review_dimensions === 'object'">
              <span
                v-for="dimKey in ['security', 'business_logic', 'performance']"
                :key="`${item.run_id || ''}-${dimKey}`"
                class="selp-report-pill"
                :class="reviewDimFailed(item, dimKey) ? 'selp-report-pill--bad' : 'selp-report-pill--ok'"
              >
                {{ dimKey }} {{ reviewDimStatus(item, dimKey) }}
              </span>
            </template>
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.selp-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-timeline-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-timeline-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.selp-timeline-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--selp-accent) 13%, #fff);
  color: var(--selp-accent);
  font-size: 11px;
  font-weight: 900;
}

.selp-timeline-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-timeline-main strong {
  color: #0f172a;
  font-size: 12px;
}

.selp-timeline-main span,
.selp-timeline-main small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-report {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 3px;
}

.selp-report-pill {
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  padding: 3px 6px;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.selp-report-pill--ok {
  background: #dcfce7;
  color: #166534;
}

.selp-report-pill--bad {
  background: #fee2e2;
  color: #991b1b;
}

.selp-timeline-roster {
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #dcfce7;
  color: #166534;
  font-weight: 900;
}

.selp-timeline-roster--outside {
  background: #fef2f2;
  color: #991b1b;
}
</style>
