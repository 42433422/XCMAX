<script setup lang="ts">
import { AUTONOMY_L4_READINESS, type AutonomyGapStatus, type AutonomyMaturityGap } from '@/constants/autonomyL4Readiness'

defineProps<{
  gaps: AutonomyMaturityGap[]
  p0Count: number
  blockedCount: number
  autoDispatchDeploy: boolean | null
  gapTone: (status: AutonomyGapStatus) => string
}>()
</script>

<template>
  <section class="selp-l4" aria-label="通往 L4 成熟度">
    <div class="selp-l4__head">
      <div>
        <p class="selp-kicker">L4 Readiness · 管理端</p>
        <strong>{{ AUTONOMY_L4_READINESS.currentLabel }} → {{ AUTONOMY_L4_READINESS.targetLevel }}</strong>
        <small>{{ AUTONOMY_L4_READINESS.updatedNote }}</small>
      </div>
      <div class="selp-l4__badges">
        <span class="selp-report-pill selp-report-pill--bad">P0 未清 {{ p0Count }}</span>
        <span class="selp-report-pill" :class="autoDispatchDeploy ? 'selp-report-pill--ok' : 'selp-report-pill--bad'">
          部署自动派发 {{ autoDispatchDeploy === null ? '未知' : autoDispatchDeploy ? '开' : '关' }}
        </span>
        <span class="selp-report-pill">阻断项 {{ blockedCount }}</span>
      </div>
    </div>
    <ol class="selp-l4__steps">
      <li v-for="step in AUTONOMY_L4_READINESS.steps" :key="step.id">
        <strong>{{ step.title }}</strong>
      </li>
    </ol>
    <ul class="selp-l4__gaps">
      <li v-for="gap in gaps" :key="gap.id" :class="`selp-l4__gap--${gapTone(gap.status)}`">
        <div class="selp-l4__gap-top">
          <span class="selp-report-pill">{{ gap.severity }}</span>
          <strong>{{ gap.title }}</strong>
          <em>{{ gap.status }}</em>
        </div>
        <p>{{ gap.impact }}</p>
        <p class="selp-l4__next">下一步：{{ gap.nextStep }}</p>
        <div v-if="gap.actions?.length" class="selp-l4__actions">
          <a v-for="action in gap.actions" :key="action.label" :href="action.href" target="_blank" rel="noopener noreferrer">{{
            action.label
          }}</a>
        </div>
      </li>
    </ul>
    <details class="selp-l4__l5">
      <summary>L5 结构性差距（平台 vs 自愈脚本）</summary>
      <ul>
        <li v-for="item in AUTONOMY_L4_READINESS.l5StructuralGaps" :key="item.id">
          <strong>{{ item.title }}</strong>
          <span>{{ item.detail }}</span>
        </li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.selp-kicker {
  margin: 0 0 4px;
  color: var(--selp-accent);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.04em;
  text-transform: uppercase;
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

.selp-l4 {
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: linear-gradient(180deg, rgba(255, 248, 235, 0.95), rgba(255, 255, 255, 0.92));
}

.selp-l4__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.selp-l4__head strong {
  display: block;
  margin: 2px 0 4px;
  color: #0f172a;
  font-size: 14px;
}

.selp-l4__head small {
  display: block;
  color: #64748b;
  line-height: 1.45;
  font-size: 12px;
}

.selp-l4__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.selp-l4__steps {
  margin: 10px 0 0;
  padding-left: 18px;
  color: #334155;
  font-size: 12px;
}

.selp-l4__gaps {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.selp-l4__gaps li {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.selp-l4__gap--bad {
  border-color: rgba(185, 28, 28, 0.28);
  background: rgba(254, 242, 242, 0.9);
}

.selp-l4__gap--warn {
  border-color: rgba(180, 83, 9, 0.28);
  background: rgba(255, 251, 235, 0.92);
}

.selp-l4__gap--ok {
  border-color: rgba(4, 120, 87, 0.24);
}

.selp-l4__gap-top {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.selp-l4__gap-top strong {
  color: #0f172a;
  font-size: 13px;
}

.selp-l4__gap-top em {
  margin-left: auto;
  font-style: normal;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.selp-l4__gaps p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.selp-l4__next {
  color: #0f172a !important;
  font-weight: 700;
}

.selp-l4__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.selp-l4__actions a {
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 800;
}

.selp-l4__l5 {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}

.selp-l4__l5 ul {
  margin: 6px 0 0;
  padding-left: 16px;
}

.selp-l4__l5 li {
  margin: 4px 0;
}

.selp-l4__l5 strong {
  display: inline;
  margin-right: 6px;
  color: #334155;
}

@media (max-width: 760px) {
  .selp-l4__head {
    flex-direction: column;
  }
}
</style>
