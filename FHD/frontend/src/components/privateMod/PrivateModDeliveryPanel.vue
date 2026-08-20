<template src="./PrivateModDeliveryPanel.template.html"></template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

const projects = ref([])
const requests = ref([])
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
const requestError = ref('')
const submittingRequest = ref(false)
const requestBusy = ref('')
const reworkRequestId = ref(0)
const requestReworkNotes = ref({})
const requestKinds = [
  { id: 'module', label: '业务模块', summary: '生成可安装的私有 Mod 模块' },
  { id: 'employee', label: 'AI 员工', summary: '生成员工包、Skill 组和运行校验' },
  { id: 'bundle', label: 'Mod + 员工', summary: '交付模块与配套生产员工' },
]
const requestForm = ref({
  open: false,
  kind: 'bundle',
  title: '',
  suggestedId: '',
  requirements: '',
  acceptanceCriteria: '',
})
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

function customOf(item) {
  return item?.custom_delivery && typeof item.custom_delivery === 'object' ? item.custom_delivery : {}
}

function latestRun(item) {
  const runs = customOf(item).runs
  return Array.isArray(runs) && runs.length ? runs[runs.length - 1] : null
}

function kindLabel(kind) {
  return requestKinds.find((row) => row.id === kind)?.label || '客户定制'
}

function stepMessage(step) {
  const message = step?.message
  if (message && typeof message === 'object') return String(message.summary || '')
  return String(
    message ||
      {
        pending: '待执行',
        running: '执行中',
        done: '已通过',
        skipped: '不适用',
        error: '未通过',
      }[step?.status] ||
      '',
  )
}

async function submitCustomRequest() {
  const form = requestForm.value
  const title = String(form.title || '').trim()
  const requirements = String(form.requirements || '').trim()
  const acceptanceCriteria = String(form.acceptanceCriteria || '').trim()
  if (title.length < 2 || requirements.length < 8 || acceptanceCriteria.length < 4) {
    error.value = '请完整填写需求名称、需求说明和验收标准'
    return
  }
  submittingRequest.value = true
  error.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-delivery/requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: form.kind,
        title,
        requirements,
        acceptance_criteria: acceptanceCriteria,
        suggested_id: String(form.suggestedId || '').trim() || undefined,
      }),
      timeoutMs: 60_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `定制需求受理失败（HTTP ${response.status}）`))
    }
    requestForm.value = {
      open: false,
      kind: 'bundle',
      title: '',
      suggestedId: '',
      requirements: '',
      acceptanceCriteria: '',
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '定制需求受理失败'
  } finally {
    submittingRequest.value = false
  }
}

function toggleRequestRework(item) {
  reworkRequestId.value = reworkRequestId.value === item.id ? 0 : item.id
}

async function decideRequest(item, action) {
  const note = String(requestReworkNotes.value[item.id] || '').trim()
  if (action === 'rework' && note.length < 4) {
    error.value = '返工意见至少 4 个字'
    return
  }
  requestBusy.value = `${action}:${item.id}`
  error.value = ''
  try {
    const response = await apiFetch(`/api/mod-store/private-delivery/requests/${item.id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, note: note || undefined }),
      timeoutMs: 60_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `定制交付操作失败（HTTP ${response.status}）`))
    }
    reworkRequestId.value = 0
    delete requestReworkNotes.value[item.id]
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '定制交付操作失败'
  } finally {
    requestBusy.value = ''
  }
}

async function installRequestArtifact(item, artifact) {
  if (!artifact?.kind) return
  requestBusy.value = `install:${item.id}:${artifact.kind}`
  error.value = ''
  try {
    const response = await apiFetch(`/api/mod-store/private-delivery/requests/${item.id}/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artifact_kind: artifact.kind }),
      timeoutMs: 180_000,
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `定制产物安装失败（HTTP ${response.status}）`))
    }
    await loadDelivery()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '定制产物安装失败'
  } finally {
    requestBusy.value = ''
  }
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
  return nodes.every(
    (node) => pipelineDone(node, step) || (pipelineActive(node, step) && ['acceptance', 'delivered'].includes(node.status)),
  )
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
  requestError.value = ''
  try {
    const response = await apiFetch('/api/mod-store/private-delivery', { timeoutMs: 30_000 })
    const body = await response.json().catch(() => ({}))
    if (!response.ok || body?.success !== true) {
      throw new Error(responseMessage(body, `私有 Mod 状态读取失败（HTTP ${response.status}）`))
    }
    projects.value = (Array.isArray(body?.data?.projects) ? body.data.projects : []).filter((row) => {
      const mid = String(row?.mod_id || '').trim()
      if (!mid || mid.endsWith('-industry')) return false
      return true
    })
    requests.value = Array.isArray(body?.data?.requests) ? body.data.requests : []
    if (Array.isArray(body?.data?.happy_path) && body.data.happy_path.length) {
      happyPath.value = body.data.happy_path
    }
    if (body?.data?.stage_flow && typeof body.data.stage_flow === 'object') {
      stageFlow.value = body.data.stage_flow
    }
    remoteError.value = String(body?.data?.remote_error || '').trim()
    requestError.value = String(body?.data?.request_error || '').trim()
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
    fromFlow ||
      project?.stage_labels?.[canonical]?.[stage] ||
      project?.stage_labels?.business?.[stage] ||
      defaultStageLabels[stage] ||
      stage,
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

let deliveryPollTimer = null
onMounted(() => {
  loadDelivery()
  deliveryPollTimer = window.setInterval(() => {
    if (!loading.value && !submittingRequest.value && !requestBusy.value) loadDelivery()
  }, 15_000)
})
onBeforeUnmount(() => {
  if (deliveryPollTimer) window.clearInterval(deliveryPollTimer)
})
</script>

<style scoped src="./PrivateModDeliveryPanel.css"></style>
