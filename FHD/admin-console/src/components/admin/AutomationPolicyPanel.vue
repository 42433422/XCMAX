<template>
  <div class="automation-policy-panel">
    <header class="page-header">
      <div>
        <h2>自动化方针</h2>
        <p class="muted">
          六线步骤主责与协作编制（SSOT：six_line_employee_map.json）。保留在服务器后台总览内查看。
        </p>
      </div>
      <div class="header-actions">
        <a
          class="btn"
          :href="openUrl"
          target="_blank"
          rel="noopener noreferrer"
        >
          <i class="fa fa-external-link" aria-hidden="true"></i>
          网页打开完整图谱
        </a>
      </div>
    </header>

    <div v-if="loadError" class="admin-card policy-banner" role="alert">
      <strong>编制映射暂未能加载</strong>
      <p class="muted">{{ loadError }}</p>
      <button type="button" class="btn btn-primary" @click="load">重试</button>
    </div>

    <div v-else-if="loading" class="admin-card policy-banner" role="status">正在加载六线编制映射…</div>

    <template v-else-if="doc">
      <section class="policy-kpis" aria-label="方针概览">
        <article class="admin-card kpi">
          <div class="kpi-num">{{ doc.linesInScope }}</div>
          <div class="kpi-label">目录六线</div>
        </article>
        <article class="admin-card kpi">
          <div class="kpi-num">{{ totalSteps }}</div>
          <div class="kpi-label">流程步骤</div>
        </article>
        <article class="admin-card kpi">
          <div class="kpi-num">{{ uniqueEmployees }}</div>
          <div class="kpi-label">涉及编制岗位</div>
        </article>
        <article class="admin-card kpi kpi-wide">
          <div class="kpi-label">说明</div>
          <p class="kpi-text">{{ doc.description || doc.coverageNote || '—' }}</p>
          <p v-if="doc.version" class="muted kpi-meta">映射版本 {{ doc.version }}</p>
        </article>
      </section>

      <section
        v-for="line in doc.lines"
        :key="line.key"
        class="admin-card policy-line"
      >
        <header class="policy-line__head">
          <h3>{{ line.label }}</h3>
          <span class="muted">{{ line.steps.length }} 个步骤 · {{ line.key }}</span>
        </header>
        <div class="policy-steps">
          <article v-for="step in line.steps" :key="step.id" class="policy-step">
            <div class="policy-step__id">{{ step.id }}</div>
            <div class="policy-step__body">
              <strong>{{ step.name }}</strong>
              <p>
                <span class="muted">主责</span>
                {{ formatIds(step.primary) }}
              </p>
              <p v-if="step.support.length">
                <span class="muted">协作</span>
                {{ formatIds(step.support) }}
              </p>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { YUANGON_PKG_ROLE_LABELS } from '@/domain/yuangonDutyRoster'
import {
  automationPolicyMapUrls,
  bundledAutomationPolicyDoc,
  parseAutomationPolicyDoc,
  type AutomationPolicyDoc,
} from '../../utils/automationPolicyLines'
import { xcmaxAutomationPolicyOpenUrl } from '@/constants/xcmaxDashboardEmbed'

const openUrl = xcmaxAutomationPolicyOpenUrl()
const loading = ref(true)
const loadError = ref('')
const doc = ref<AutomationPolicyDoc | null>(null)

const totalSteps = computed(() => (doc.value?.lines || []).reduce((n, l) => n + l.steps.length, 0))
const uniqueEmployees = computed(() => {
  const ids = new Set<string>()
  for (const line of doc.value?.lines || []) {
    for (const step of line.steps) {
      step.primary.forEach((id) => ids.add(id))
      step.support.forEach((id) => ids.add(id))
    }
  }
  return ids.size
})

function formatIds(ids: string[]): string {
  if (!ids.length) return '—'
  return ids.map((id) => YUANGON_PKG_ROLE_LABELS[id] || id).join('、')
}

async function load() {
  loading.value = true
  loadError.value = ''
  const urls = automationPolicyMapUrls()
  let lastErr = '未找到编制映射文件'
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: 'no-store', credentials: 'same-origin' })
      if (!res.ok) {
        lastErr = `HTTP ${res.status} @ ${url}`
        continue
      }
      const raw = await res.json()
      doc.value = parseAutomationPolicyDoc(raw)
      loading.value = false
      return
    } catch (e) {
      lastErr = e instanceof Error ? e.message : String(e)
    }
  }
  // 静态挂载失败时仍展示仓内 SSOT，避免方针页空白
  try {
    doc.value = bundledAutomationPolicyDoc()
    loadError.value = ''
  } catch {
    loadError.value = lastErr
  }
  loading.value = false
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.automation-policy-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.policy-banner {
  padding: 16px;
  display: grid;
  gap: 8px;
}
.policy-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}
.kpi {
  padding: 16px;
}
.kpi-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--admin-text, #172033);
  line-height: 1.3;
}
.kpi-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--admin-muted, #64748b);
}
.kpi-wide {
  grid-column: 1 / -1;
}
@media (min-width: 960px) {
  .kpi-wide {
    grid-column: span 2;
  }
}
.kpi-text {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--admin-text, #172033);
  line-height: 1.55;
}
.kpi-meta {
  margin: 6px 0 0;
  font-size: 12px;
}
.policy-line {
  padding: 16px 18px 18px;
}
.policy-line__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--admin-border, #d7dee9);
}
.policy-line__head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--admin-text, #172033);
}
.policy-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}
.policy-step {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--admin-border, #d7dee9);
  border-radius: var(--admin-control-radius, 8px);
  background: #f8fafc;
}
.policy-step__id {
  min-width: 40px;
  height: fit-content;
  padding: 4px 8px;
  border-radius: 6px;
  background: #e8f3ff;
  color: var(--admin-primary, #1677ff);
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}
.policy-step__body strong {
  display: block;
  margin-bottom: 6px;
  font-size: 14px;
  color: var(--admin-text, #172033);
}
.policy-step__body p {
  margin: 0 0 4px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--admin-text, #172033);
}
.policy-step__body .muted {
  margin-right: 6px;
}
</style>
