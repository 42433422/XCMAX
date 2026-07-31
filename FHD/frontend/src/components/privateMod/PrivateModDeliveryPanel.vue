<template>
  <section class="private-mod-center" aria-label="客户私有 Mod 生产中心">
    <header class="private-mod-center__header">
      <div>
        <div class="private-mod-center__eyebrow">客户定制交付</div>
        <h3>私有 Mod 生产中心</h3>
        <p>
          模块轨与员工轨分开推进。每个节点是一条有先后约束的流程：
          制作 → 测试 → 验收 → 交付；不通过只能转返工，不能跨阶段跳跃。
        </p>
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

            <ol class="private-mod-flow" aria-label="主流程阶段">
              <li
                v-for="(step, stepIndex) in happyPath"
                :key="step"
                class="private-mod-flow__step"
                :data-done="flowStepDone(project, rail.id, step)"
              >
                <span class="private-mod-flow__num">{{ String(stepIndex + 1).padStart(2, '0') }}</span>
                <span class="private-mod-flow__name">{{ stageLabel(project, rail.id, step) }}</span>
                <small>{{ stageGoal(step) }}</small>
              </li>
            </ol>

            <ol v-if="nodesOf(project, rail.id).length" class="private-mod-rail" :aria-label="`${rail.label}节点`">
              <li
                v-for="(node, index) in nodesOf(project, rail.id)"
                :key="node.id"
                class="private-mod-node"
                :data-status="node.status"
              >
                <div class="private-mod-node__top">
                  <div class="private-mod-node__index" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</div>
                  <div class="private-mod-node__body">
                    <div class="private-mod-node__title">{{ node.label }}</div>
                    <small v-if="node.summary">{{ node.summary }}</small>
                  </div>
                  <span class="private-mod-node__badge">{{ node.status_label || stageLabel(project, rail.id, node.status) }}</span>
                </div>

                <div class="private-mod-node__pipeline" aria-hidden="true">
                  <span
                    v-for="step in happyPath"
                    :key="`${node.id}-${step}`"
                    class="private-mod-node__pip"
                    :data-active="pipelineActive(node, step)"
                    :data-done="pipelineDone(node, step)"
                    :data-rework="node.status === 'rework'"
                  >{{ stageLabel(project, rail.id, step) }}</span>
                </div>

                <p class="private-mod-node__goal">
                  目标：{{ node.goal || stageGoal(node.status) || '按流程推进到下一阶段' }}
                </p>

                <div class="private-mod-node__actions">
                  <button
                    v-for="next in (node.next_stages || [])"
                    :key="`${node.id}-${next}`"
                    type="button"
                    class="private-mod-node__action"
                    :class="{ 'private-mod-node__action--rework': next === 'rework' }"
                    :disabled="savingStatus === `${project.mod_id}:${rail.id}:${node.id}`"
                    @click="onAdvanceClick(project, rail.id, node, next)"
                  >
                    {{ nextActionLabel(project, rail.id, node.status, next) }}
                  </button>
                  <span v-if="!(node.next_stages || []).length" class="private-mod-node__done">流程已结束</span>
                </div>
                <p v-if="node.status === 'rework' && lastReworkNote(node)" class="private-mod-node__ticket">
                  {{ lastReworkNote(node) }}
                </p>
              </li>
            </ol>
            <div v-else class="private-mod-track__empty">{{ rail.empty }}</div>
          </section>
        </div>
      </article>
    </div>

    <div
      v-if="reworkDialog.open"
      class="private-mod-rework-mask"
      role="dialog"
      aria-modal="true"
      aria-label="填写返工问题"
      @click.self="closeReworkDialog"
    >
      <form class="private-mod-rework" @submit.prevent="submitRework">
        <header>
          <h4>转返工 · 填写问题</h4>
          <p>问题会开成客服变更工单（bug_fix），不另建工单系统。</p>
        </header>
        <div class="private-mod-rework__meta">
          <span>{{ reworkDialog.projectName }}</span>
          <code>{{ reworkDialog.nodeLabel }}</code>
        </div>
        <label class="private-mod-rework__label" for="private-mod-rework-problem">问题说明</label>
        <textarea
          id="private-mod-rework-problem"
          v-model="reworkDialog.problem"
          rows="5"
          maxlength="2000"
          placeholder="例如：考勤表转化后部门列错位，样例文件已附……"
          required
        />
        <footer class="private-mod-rework__footer">
          <button type="button" class="private-mod-rework__cancel" @click="closeReworkDialog">取消</button>
          <button type="submit" class="private-mod-node__action private-mod-node__action--rework" :disabled="!!savingStatus">
            {{ savingStatus ? '提交中…' : '开单并转返工' }}
          </button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

const projects = ref([])
const happyPath = ref(['production', 'testing', 'acceptance', 'delivered'])
const stageFlow = ref({})
const defaultStageLabels = {
  production: '制作中',
  testing: '测试中',
  rework: '返工中',
  acceptance: '验收中',
  delivered: '已交付',
  partial: '部分完成',
}
const defaultGoals = {
  production: '完成开发与自测，进入可测状态',
  testing: '用例通过；不通过则返工',
  rework: '修复问题后重回测试',
  acceptance: '生产/客户验收通过后交付',
  delivered: '节点交付完成，流程结束',
}
const trackRails = [
  {
    id: 'modules',
    kicker: '交付轨道 01 · 模块',
    label: '业务模块',
    summary: '每个模块节点走完整交付流程（例：太阳鸟「考勤表转化」）。',
    empty: '当前定制包未声明模块节点。',
  },
  {
    id: 'employees',
    kicker: '交付轨道 02 · 员工',
    label: 'AI 员工',
    summary: '每个员工节点独立走制作 / 测试 / 验收 / 上岗流程。',
    empty: '当前定制包未声明员工节点。',
  },
]
const loading = ref(false)
const updating = ref('')
const savingStatus = ref('')
const error = ref('')
const remoteError = ref('')
const reworkDialog = ref({
  open: false,
  project: null,
  track: '',
  nodeId: '',
  projectName: '',
  nodeLabel: '',
  problem: '',
})

function responseMessage(body, fallback) {
  return String(body?.detail || body?.message || body?.error || fallback).trim() || fallback
}

function lastReworkNote(node) {
  const timeline = Array.isArray(node?.timeline) ? node.timeline : []
  for (let i = timeline.length - 1; i >= 0; i -= 1) {
    const row = timeline[i]
    if (row && row.status === 'rework' && row.note) return String(row.note)
  }
  return ''
}

function onAdvanceClick(project, track, node, status) {
  if (status === 'rework') {
    reworkDialog.value = {
      open: true,
      project,
      track,
      nodeId: node.id,
      projectName: project.name || project.mod_id,
      nodeLabel: node.label || node.id,
      problem: '',
    }
    return
  }
  advanceNode(project, track, node.id, status)
}

function closeReworkDialog() {
  reworkDialog.value = {
    open: false,
    project: null,
    track: '',
    nodeId: '',
    projectName: '',
    nodeLabel: '',
    problem: '',
  }
}

async function submitRework() {
  const dlg = reworkDialog.value
  const problem = String(dlg.problem || '').trim()
  if (problem.length < 4) {
    error.value = '转返工须填写问题说明（至少 4 个字）'
    return
  }
  if (!dlg.project) return
  await advanceNode(dlg.project, dlg.track, dlg.nodeId, 'rework', problem)
  if (!error.value) closeReworkDialog()
}

function nodesOf(project, track) {
  const nodes = project?.track_nodes?.[track]
  return Array.isArray(nodes) ? nodes : []
}

function stageGoal(stage) {
  const fromApi = stageFlow.value?.[stage]?.goal
  return String(fromApi || defaultGoals[stage] || '').trim()
}

function happyIndex(status) {
  const idx = happyPath.value.indexOf(status === 'rework' ? 'testing' : status)
  return idx
}

function pipelineDone(node, step) {
  const cur = String(node?.status || 'production')
  if (cur === 'delivered') return true
  if (cur === 'rework') return happyIndex('production') >= happyPath.value.indexOf(step) && step === 'production'
  const curIdx = happyIndex(cur)
  const stepIdx = happyPath.value.indexOf(step)
  return curIdx > stepIdx
}

function pipelineActive(node, step) {
  const cur = String(node?.status || 'production')
  if (cur === 'rework') return step === 'testing'
  return cur === step
}

function flowStepDone(project, track, step) {
  const nodes = nodesOf(project, track)
  if (!nodes.length) return false
  return nodes.every((node) => pipelineDone(node, step) || pipelineActive(node, step) && ['acceptance', 'delivered'].includes(node.status))
}

function nextActionLabel(project, track, current, next) {
  const curLabel = stageLabel(project, track, current)
  const nextLabel = stageLabel(project, track, next)
  if (next === 'rework') return `转返工`
  if (current === 'rework' && next === 'testing') return `返工完成，重回测试`
  return `推进到${nextLabel}`
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
    if (Array.isArray(body?.data?.happy_path) && body.data.happy_path.length) {
      happyPath.value = body.data.happy_path
    }
    if (body?.data?.stage_flow && typeof body.data.stage_flow === 'object') {
      stageFlow.value = body.data.stage_flow
    }
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
  const fromFlow = stageFlow.value?.[stage]?.label
  return String(
    fromFlow
      || project?.stage_labels?.[canonical]?.[stage]
      || project?.stage_labels?.business?.[stage]
      || defaultStageLabels[stage]
      || stage,
  )
}

async function advanceNode(project, track, nodeId, status, note = '') {
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
        note: note || undefined,
      }),
      timeoutMs: 30_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `流程推进失败（HTTP ${response.status}）`))
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '流程推进失败'
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
.private-mod-node__top {
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
.private-mod-track__summary,
.private-mod-node__goal {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.55;
}
.private-mod-center__refresh,
.private-mod-center__update,
.private-mod-node__action {
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
.private-mod-center__update:disabled,
.private-mod-node__action:disabled { opacity: .55; cursor: wait; }
.private-mod-node__action--rework { background: #b45309; }
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
.private-mod-track__rollup,
.private-mod-node__badge {
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
.private-mod-node[data-status='acceptance'] .private-mod-node__badge { color: #92400e; background: #fef3c7; }
.private-mod-project__overall[data-status='rework'],
.private-mod-track__rollup[data-status='rework'],
.private-mod-node[data-status='rework'] .private-mod-node__badge { color: #b91c1c; background: #fee2e2; }
.private-mod-project__update { display: flex; align-items: center; gap: 10px; color: #92400e; font-size: 12px; font-weight: 700; }
.private-mod-project__latest { font-size: 12px; }
.private-mod-project__description { margin-top: 12px; }
.private-mod-project__tracks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 16px; }
.private-mod-track { border-radius: 13px; padding: 15px; background: #f8fafc; }
.private-mod-track--modules { border: 1px solid #dbeafe; }
.private-mod-track--employees { border: 1px solid #ede9fe; }
.private-mod-flow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}
.private-mod-flow__step {
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  border: 1px dashed #cbd5e1;
}
.private-mod-flow__step[data-done='true'] { border-style: solid; border-color: #86efac; background: #f0fdf4; }
.private-mod-flow__num { display: block; color: #94a3b8; font-size: 11px; font-weight: 700; }
.private-mod-flow__name { display: block; margin-top: 4px; color: #0f172a; font-size: 13px; font-weight: 700; }
.private-mod-flow__step small { display: block; margin-top: 4px; color: #64748b; font-size: 11px; line-height: 1.4; }
.private-mod-rail {
  display: grid;
  gap: 12px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}
.private-mod-node {
  border-radius: 12px;
  padding: 12px;
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
.private-mod-node__pipeline {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 12px;
}
.private-mod-node__pip {
  border-radius: 8px;
  padding: 6px 4px;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  background: #f1f5f9;
}
.private-mod-node__pip[data-done='true'] { color: #047857; background: #d1fae5; }
.private-mod-node__pip[data-active='true'] { color: #1d4ed8; background: #dbeafe; box-shadow: inset 0 0 0 1px #93c5fd; }
.private-mod-node__pip[data-rework='true'][data-active='true'] { color: #b45309; background: #ffedd5; box-shadow: inset 0 0 0 1px #fdba74; }
.private-mod-node__actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.private-mod-node__done { color: #059669; font-size: 12px; font-weight: 700; align-self: center; }
.private-mod-node__ticket {
  margin: 10px 0 0;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
  line-height: 1.45;
}
.private-mod-track__empty { margin-top: 13px; color: #94a3b8; font-size: 12px; }
.private-mod-rework-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgba(15, 23, 42, .45);
}
.private-mod-rework {
  width: min(520px, 100%);
  border-radius: 16px;
  padding: 18px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(15, 23, 42, .25);
}
.private-mod-rework h4 { margin: 0; font-size: 18px; }
.private-mod-rework header p { margin: 6px 0 0; color: #64748b; font-size: 12px; line-height: 1.5; }
.private-mod-rework__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  color: #475569;
  font-size: 12px;
}
.private-mod-rework__meta code { color: #0f172a; }
.private-mod-rework__label {
  display: block;
  margin-top: 14px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}
.private-mod-rework textarea {
  display: block;
  width: 100%;
  margin-top: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  resize: vertical;
  font: inherit;
  color: #0f172a;
  box-sizing: border-box;
}
.private-mod-rework__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.private-mod-rework__cancel {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 14px;
  background: #fff;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

@media (max-width: 1100px) {
  .private-mod-project__tracks,
  .private-mod-flow,
  .private-mod-node__pipeline { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
  .private-mod-center { padding: 18px 14px 30px; }
  .private-mod-center__header,
  .private-mod-project__header { flex-direction: column; }
  .private-mod-project__tracks { grid-template-columns: 1fr; }
  .private-mod-project__update { align-items: flex-start; flex-direction: column; }
}
</style>
