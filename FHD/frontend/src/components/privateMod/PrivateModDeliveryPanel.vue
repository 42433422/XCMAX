<template>
  <section class="private-mod-center" aria-label="客户私有 Mod 生产中心">
    <header class="private-mod-center__header">
      <div>
        <div class="private-mod-center__eyebrow">客户定制交付</div>
        <h3>私有 Mod 生产中心</h3>
        <p>业务模块与 AI 员工分别生产、测试、验收；私有版本不进入公共员工商店。</p>
      </div>
      <button type="button" class="private-mod-center__refresh" :disabled="loading || updating" @click="loadDelivery">
        {{ loading ? '同步中…' : '刷新私有状态' }}
      </button>
    </header>

    <div v-if="error" class="private-mod-center__notice private-mod-center__notice--error" role="alert">
      {{ error }}
    </div>
    <div v-else-if="remoteError" class="private-mod-center__notice private-mod-center__notice--muted">
      私有版本检查暂不可用：{{ remoteError }}
    </div>
    <div v-if="loading && !projects.length" class="private-mod-center__empty">正在读取客户私有 Mod…</div>
    <div v-else-if="!projects.length" class="private-mod-center__empty">
      当前账号还没有绑定客户私有 Mod。
    </div>

    <div v-else class="private-mod-center__projects">
      <article v-for="project in projects" :key="project.mod_id" class="private-mod-project">
        <header class="private-mod-project__header">
          <div>
            <h4>{{ project.name }}</h4>
            <div class="private-mod-project__meta">
              <code>{{ project.mod_id }}</code>
              <span>{{ project.current_version ? `当前 v${project.current_version}` : '尚未安装' }}</span>
              <span class="private-mod-project__overall" :data-status="project.overall_status">
                {{ project.overall_label }}
              </span>
            </div>
          </div>
          <div v-if="project.update_available" class="private-mod-project__update">
            <span>私有版本 v{{ project.latest_version }} 可更新</span>
            <button
              type="button"
              class="private-mod-center__update"
              :disabled="updating === project.mod_id"
              @click="updateProject(project)"
            >
              {{ updating === project.mod_id ? '更新中…' : '更新私有 Mod' }}
            </button>
          </div>
          <span v-else-if="project.latest_version" class="private-mod-project__latest">已是最新私有版本</span>
        </header>

        <p v-if="project.description" class="private-mod-project__description">{{ project.description }}</p>

        <div class="private-mod-project__tracks">
          <section class="private-mod-track private-mod-track--business">
            <header class="private-mod-track__header">
              <div>
                <span class="private-mod-track__kicker">交付轨道 01</span>
                <h5>业务模块</h5>
              </div>
              <select
                class="private-mod-track__select"
                :value="trackStatus(project, 'business')"
                :disabled="savingStatus === `${project.mod_id}:business`"
                aria-label="业务模块交付阶段"
                @change="saveStatus(project, 'business', $event)"
              >
                <option v-for="stage in stages" :key="stage" :value="stage">
                  {{ stageLabel(project, 'business', stage) }}
                </option>
              </select>
            </header>
            <p class="private-mod-track__summary">侧栏入口、工作台、页面、表单和业务流程。</p>
            <ul v-if="project.business_modules.length" class="private-mod-items">
              <li v-for="item in project.business_modules" :key="item.id">{{ item.label }}</li>
            </ul>
            <div v-else class="private-mod-track__empty">当前 Mod 未声明侧栏模块。</div>
          </section>

          <section class="private-mod-track private-mod-track--employees">
            <header class="private-mod-track__header">
              <div>
                <span class="private-mod-track__kicker">交付轨道 02</span>
                <h5>AI 员工</h5>
              </div>
              <select
                class="private-mod-track__select"
                :value="trackStatus(project, 'employees')"
                :disabled="savingStatus === `${project.mod_id}:employees`"
                aria-label="AI 员工交付阶段"
                @change="saveStatus(project, 'employees', $event)"
              >
                <option v-for="stage in stages" :key="stage" :value="stage">
                  {{ stageLabel(project, 'employees', stage) }}
                </option>
              </select>
            </header>
            <p class="private-mod-track__summary">角色、提示词、工具、工作流程和上岗验证。</p>
            <ul v-if="project.ai_employees.length" class="private-mod-items">
              <li v-for="item in project.ai_employees" :key="item.id">
                <span>{{ item.label }}</span>
                <small v-if="item.summary">{{ item.summary }}</small>
              </li>
            </ul>
            <div v-else class="private-mod-track__empty">当前 Mod 未声明 AI 员工。</div>
          </section>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

const projects = ref([])
const stages = ref(['production', 'testing', 'rework', 'acceptance', 'delivered'])
const defaultStageLabels = {
  production: '制作中',
  testing: '测试中',
  rework: '返工中',
  acceptance: '验收中',
  delivered: '已交付',
}
const loading = ref(false)
const updating = ref('')
const savingStatus = ref('')
const error = ref('')
const remoteError = ref('')

function responseMessage(body, fallback) {
  return String(body?.detail || body?.message || body?.error || fallback).trim() || fallback
}

async function loadDelivery() {
  loading.value = true
  error.value = ''
  remoteError.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-delivery', { timeoutMs: 30_000 })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `私有 Mod 状态读取失败（HTTP ${response.status}）`))
    }
    projects.value = (Array.isArray(body?.data?.projects) ? body.data.projects : []).filter(
      (row) => {
        const mid = String(row?.mod_id || '').trim()
        // 通用行业包不属于客户私有交付（后端也会过滤；前端兜底）
        if (!mid || mid.endsWith('-industry')) return false
        return true
      },
    )
    stages.value = Array.isArray(body?.data?.stages) && body.data.stages.length
      ? body.data.stages
      : stages.value
    remoteError.value = String(body?.data?.remote_error || '').trim()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '私有 Mod 状态读取失败'
  } finally {
    loading.value = false
  }
}

function trackStatus(project, track) {
  return String(project?.tracks?.[track]?.status || 'production')
}

function stageLabel(project, track, stage) {
  return String(project?.stage_labels?.[track]?.[stage] || defaultStageLabels[stage] || stage)
}

async function saveStatus(project, track, event) {
  const status = String(event?.target?.value || '').trim()
  if (!status) return
  const key = `${project.mod_id}:${track}`
  savingStatus.value = key
  error.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-delivery/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mod_id: project.mod_id, track, status }),
      timeoutMs: 30_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `交付阶段更新失败（HTTP ${response.status}）`))
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '交付阶段更新失败'
  } finally {
    savingStatus.value = ''
  }
}

async function updateProject(project) {
  if (!project?.mod_id || updating.value) return
  updating.value = project.mod_id
  error.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-mod/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mod_id: project.mod_id, latest_version: project.latest_version }),
      timeoutMs: 120_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `私有 Mod 更新失败（HTTP ${response.status}）`))
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '私有 Mod 更新失败'
  } finally {
    updating.value = ''
  }
}

onMounted(loadDelivery)
</script>

<style scoped>
.private-mod-center {
  width: min(1180px, 100%);
  margin: 0 auto;
  padding: 22px 24px 40px;
  box-sizing: border-box;
}
.private-mod-center__header,
.private-mod-project__header,
.private-mod-track__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.private-mod-center__eyebrow,
.private-mod-track__kicker {
  color: #d97706;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.private-mod-center h3,
.private-mod-project h4,
.private-mod-track h5 {
  margin: 4px 0;
  color: #172554;
}
.private-mod-center h3 { font-size: 24px; }
.private-mod-project h4 { font-size: 19px; }
.private-mod-track h5 { font-size: 16px; }
.private-mod-center__header p,
.private-mod-project__description,
.private-mod-track__summary {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
.private-mod-center__refresh,
.private-mod-center__update {
  border: 0;
  border-radius: 9px;
  padding: 9px 13px;
  color: #fff;
  background: #d97706;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}
.private-mod-center__refresh:disabled,
.private-mod-center__update:disabled { opacity: .55; cursor: wait; }
.private-mod-center__notice,
.private-mod-center__empty {
  margin-top: 18px;
  border-radius: 12px;
  padding: 14px 16px;
  color: #475569;
  background: #f8fafc;
  font-size: 13px;
}
.private-mod-center__notice--error { color: #b91c1c; background: #fef2f2; }
.private-mod-center__projects { display: grid; gap: 16px; margin-top: 20px; }
.private-mod-project {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 18px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(15, 23, 42, .05);
}
.private-mod-project__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
}
.private-mod-project__meta code { color: #475569; }
.private-mod-project__overall,
.private-mod-project__latest {
  border-radius: 999px;
  padding: 3px 8px;
  color: #166534;
  background: #dcfce7;
  font-weight: 700;
}
.private-mod-project__overall[data-status='partial'] { color: #92400e; background: #fef3c7; }
.private-mod-project__overall[data-status='rework'] { color: #b91c1c; background: #fee2e2; }
.private-mod-project__update { display: flex; align-items: center; gap: 10px; color: #92400e; font-size: 12px; font-weight: 700; }
.private-mod-project__latest { font-size: 12px; }
.private-mod-project__description { margin-top: 12px; }
.private-mod-project__tracks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
.private-mod-track { border-radius: 13px; padding: 15px; background: #f8fafc; }
.private-mod-track--business { border: 1px solid #dbeafe; }
.private-mod-track--employees { border: 1px solid #ede9fe; }
.private-mod-track__select { min-width: 92px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 7px 8px; color: #334155; background: #fff; font-size: 12px; }
.private-mod-items { display: grid; gap: 7px; margin: 13px 0 0; padding: 0; list-style: none; color: #334155; font-size: 13px; }
.private-mod-items li { border-radius: 8px; padding: 8px 10px; background: #fff; }
.private-mod-items small { display: block; margin-top: 3px; color: #64748b; font-size: 11px; line-height: 1.45; }
.private-mod-track__empty { margin-top: 13px; color: #94a3b8; font-size: 12px; }
@media (max-width: 760px) {
  .private-mod-center { padding: 18px 14px 30px; }
  .private-mod-center__header,
  .private-mod-project__header { flex-direction: column; }
  .private-mod-project__tracks { grid-template-columns: 1fr; }
  .private-mod-project__update { align-items: flex-start; flex-direction: column; }
}
</style>
