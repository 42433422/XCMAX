<template>
  <section class="private-mod-center" aria-label="客户私有 Mod 生产中心">
    <header class="private-mod-center__header">
      <div>
        <div class="private-mod-center__eyebrow">客户定制交付</div>
        <h3>私有 Mod 生产中心</h3>
        <p>模块轨与员工轨分开推进；每条轨道上的节点各自显示制作进度。通用行业包不在此列表。</p>
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
          <section
            v-for="rail in trackRails"
            :key="rail.id"
            class="private-mod-track"
            :class="`private-mod-track--${rail.id}`"
          >
            <header class="private-mod-track__header">
              <div>
                <span class="private-mod-track__kicker">{{ rail.kicker }}</span>
                <h5>{{ rail.label }}</h5>
              </div>
              <span class="private-mod-track__rollup" :data-status="trackStatus(project, rail.id)">
                {{ stageLabel(project, rail.id, trackStatus(project, rail.id)) }}
              </span>
            </header>
            <p class="private-mod-track__summary">{{ rail.summary }}</p>

            <ol v-if="nodesOf(project, rail.id).length" class="private-mod-rail" :aria-label="`${rail.label}节点`">
              <li
                v-for="(node, index) in nodesOf(project, rail.id)"
                :key="node.id"
                class="private-mod-node"
                :data-status="node.status"
              >
                <div class="private-mod-node__index" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</div>
                <div class="private-mod-node__body">
                  <div class="private-mod-node__title">{{ node.label }}</div>
                  <small v-if="node.summary">{{ node.summary }}</small>
                </div>
                <select
                  class="private-mod-track__select"
                  :value="node.status || 'production'"
                  :disabled="savingStatus === `${project.mod_id}:${rail.id}:${node.id}`"
                  :aria-label="`${node.label}进度`"
                  @change="saveNodeStatus(project, rail.id, node.id, $event)"
                >
                  <option v-for="stage in stages" :key="stage" :value="stage">
                    {{ stageLabel(project, rail.id, stage) }}
                  </option>
                </select>
              </li>
            </ol>
            <div v-else class="private-mod-track__empty">{{ rail.empty }}</div>
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
  partial: '部分完成',
}
const trackRails = [
  {
    id: 'modules',
    kicker: '交付轨道 01 · 模块',
    label: '业务模块',
    summary: '每个模块节点独立显示制作进度（例如太阳鸟「考勤表转化」）。',
    empty: '当前定制包未声明模块节点。',
  },
  {
    id: 'employees',
    kicker: '交付轨道 02 · 员工',
    label: 'AI 员工',
    summary: '每个员工节点独立显示制作 / 测试 / 上岗进度。',
    empty: '当前定制包未声明员工节点。',
  },
]
const loading = ref(false)
const updating = ref('')
const savingStatus = ref('')
const error = ref('')
const remoteError = ref('')

function responseMessage(body, fallback) {
  return String(body?.detail || body?.message || body?.error || fallback).trim() || fallback
}

function nodesOf(project, track) {
  const nodes = project?.track_nodes?.[track]
  if (Array.isArray(nodes) && nodes.length) return nodes
  // 兼容旧字段
  if (track === 'modules' && Array.isArray(project?.business_modules)) {
    return project.business_modules.map((item) => ({
      ...item,
      status: 'production',
      status_label: '制作中',
    }))
  }
  if (track === 'employees' && Array.isArray(project?.ai_employees)) {
    return project.ai_employees.map((item) => ({
      ...item,
      status: 'production',
      status_label: '制作中',
    }))
  }
  return []
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
  const canonical = track === 'business' ? 'modules' : track
  return String(project?.tracks?.[canonical]?.status || project?.tracks?.business?.status || 'production')
}

function stageLabel(project, track, stage) {
  const canonical = track === 'business' ? 'modules' : track
  return String(
    project?.stage_labels?.[canonical]?.[stage]
      || project?.stage_labels?.business?.[stage]
      || defaultStageLabels[stage]
      || stage,
  )
}

async function saveNodeStatus(project, track, nodeId, event) {
  const status = String(event?.target?.value || '').trim()
  if (!status || !nodeId) return
  const key = `${project.mod_id}:${track}:${nodeId}`
  savingStatus.value = key
  error.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-delivery/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mod_id: project.mod_id,
        track,
        node_id: nodeId,
        status,
      }),
      timeoutMs: 30_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `节点进度更新失败（HTTP ${response.status}）`))
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '节点进度更新失败'
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
      body: JSON.stringify({
        mod_id: project.mod_id,
        expected_version: project.latest_version || '',
      }),
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
  padding: 22px 22px 36px;
  color: #0f172a;
}
.private-mod-center__header,
.private-mod-project__header,
.private-mod-track__header,
.private-mod-node {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}
.private-mod-center__eyebrow,
.private-mod-track__kicker {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.private-mod-center h3,
.private-mod-project h4,
.private-mod-track h5 {
  margin: 4px 0 0;
  font-weight: 750;
}
.private-mod-center h3 { font-size: 24px; }
.private-mod-project h4 { font-size: 19px; }
.private-mod-track h5 { font-size: 16px; }
.private-mod-center__header p,
.private-mod-project__description,
.private-mod-track__summary {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.55;
}
.private-mod-center__refresh,
.private-mod-center__update {
  border: 0;
  border-radius: 10px;
  padding: 10px 14px;
  background: #0f172a;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.private-mod-center__refresh:disabled,
.private-mod-center__update:disabled { opacity: .55; cursor: wait; }
.private-mod-center__notice,
.private-mod-center__empty {
  margin-top: 16px;
  border-radius: 12px;
  padding: 12px 14px;
  background: #f8fafc;
  color: #475569;
  font-size: 13px;
}
.private-mod-center__notice--error { color: #b91c1c; background: #fef2f2; }
.private-mod-center__projects { display: grid; gap: 16px; margin-top: 20px; }
.private-mod-project {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 18px;
  background: #fff;
}
.private-mod-project__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}
.private-mod-project__meta code { color: #475569; }
.private-mod-project__overall,
.private-mod-project__latest,
.private-mod-track__rollup {
  border-radius: 999px;
  padding: 4px 9px;
  background: #ecfdf5;
  color: #047857;
  font-size: 12px;
  font-weight: 700;
}
.private-mod-project__overall[data-status='partial'],
.private-mod-track__rollup[data-status='partial'],
.private-mod-track__rollup[data-status='testing'],
.private-mod-track__rollup[data-status='acceptance'],
.private-mod-node[data-status='testing'],
.private-mod-node[data-status='acceptance'] { color: #92400e; background: #fef3c7; }
.private-mod-project__overall[data-status='rework'],
.private-mod-track__rollup[data-status='rework'],
.private-mod-node[data-status='rework'] { color: #b91c1c; background: #fee2e2; }
.private-mod-project__update { display: flex; align-items: center; gap: 10px; color: #92400e; font-size: 12px; font-weight: 700; }
.private-mod-project__latest { font-size: 12px; }
.private-mod-project__description { margin-top: 12px; }
.private-mod-project__tracks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
.private-mod-track { border-radius: 13px; padding: 15px; background: #f8fafc; }
.private-mod-track--modules { border: 1px solid #dbeafe; }
.private-mod-track--employees { border: 1px solid #ede9fe; }
.private-mod-track__select { min-width: 92px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 7px 8px; color: #334155; background: #fff; font-size: 12px; }
.private-mod-rail {
  display: grid;
  gap: 10px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}
.private-mod-node {
  align-items: center;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
}
.private-mod-node__index {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.private-mod-node__body { flex: 1 1 auto; min-width: 0; }
.private-mod-node__title { color: #0f172a; font-size: 13px; font-weight: 700; }
.private-mod-node small { display: block; margin-top: 3px; color: #64748b; font-size: 11px; line-height: 1.45; }
.private-mod-track__empty { margin-top: 13px; color: #94a3b8; font-size: 12px; }

@media (max-width: 900px) {
  .private-mod-center { padding: 18px 14px 30px; }
  .private-mod-center__header,
  .private-mod-project__header { flex-direction: column; }
  .private-mod-project__tracks { grid-template-columns: 1fr; }
  .private-mod-project__update { align-items: flex-start; flex-direction: column; }
  .private-mod-node { flex-wrap: wrap; }
}
</style>
