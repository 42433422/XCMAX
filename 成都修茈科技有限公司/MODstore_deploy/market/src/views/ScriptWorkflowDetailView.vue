<template>
  <div v-if="wf" class="swd">
    <header class="swd-head">
      <button class="swd-back" @click="goList">← 返回列表</button>
      <h1>{{ wf.name }}</h1>
      <span class="swd-badge" :class="`status-${wf.status}`">{{ statusLabel(wf.status) }}</span>
    </header>

    <div class="swd-meta">
      <p><strong>任务描述：</strong>{{ wf.brief?.goal || '(无)' }}</p>
      <p><strong>输出要求：</strong>{{ wf.brief?.outputs || '(无)' }}</p>
      <p><strong>验收标准：</strong>{{ wf.brief?.acceptance || '(无)' }}</p>
    </div>

    <div class="swd-actions">
      <button @click="editWithAi">用 AI 改进</button>
      <button v-if="wf.status === 'sandbox_testing'" @click="goSandbox">沙箱试用</button>
      <button v-if="wf.status === 'sandbox_testing' && canActivate" class="swd-activate" @click="activate">
        启用
      </button>
      <button v-if="wf.status === 'active'" @click="deactivate">停用</button>
      <button class="swd-danger" @click="del">删除</button>
    </div>

    <section class="swd-tabs">
      <button :class="{ active: tab === 'code' }" @click="tab = 'code'">脚本</button>
      <button :class="{ active: tab === 'runs' }" @click="tab = 'runs'">运行记录</button>
      <button :class="{ active: tab === 'versions' }" @click="tab = 'versions'">历史版本</button>
    </section>

    <div v-if="tab === 'code'" class="swd-code">
      <pre><code>{{ wf.script_text || '(脚本为空)' }}</code></pre>
    </div>

    <div v-else-if="tab === 'runs'" class="swd-runs">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>模式</th>
            <th>状态</th>
            <th>开始</th>
            <th>结束</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>#{{ r.id }}</td>
            <td>{{ runModeLabel(r.mode) }}</td>
            <td :class="`run-${r.status}`">{{ r.status }}</td>
            <td>{{ formatTime(r.started_at) }}</td>
            <td>{{ r.completed_at ? formatTime(r.completed_at) : '-' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="runs.length === 0" class="swd-empty">暂无运行记录</p>
    </div>

    <div v-else-if="tab === 'versions'" class="swd-versions">
      <ul>
        <li v-for="v in versions" :key="v.id">
          <strong>v{{ v.version_no }}</strong>
          <span v-if="v.is_current" class="cur">当前</span>
          <small>{{ formatTime(v.created_at) }}</small>
        </li>
      </ul>
      <p v-if="versions.length === 0" class="swd-empty">暂无历史版本</p>
    </div>
  </div>
  <p v-else class="swd-loading">加载中…</p>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const wf = ref<any>(null)
const runs = ref<any[]>([])
const versions = ref<any[]>([])
const tab = ref<'code' | 'runs' | 'versions'>('code')

const canActivate = computed(() =>
  runs.value.some((r) => r.mode === 'manual_sandbox' && r.status === 'success'),
)

function goList() {
  router.push({ name: 'workbench-script-workflows' })
}

function editWithAi() {
  router.push({ name: 'workbench-script-workflow-edit', params: { id: wf.value.id } })
}

function goSandbox() {
  router.push({ name: 'workbench-script-workflow-edit', params: { id: wf.value.id }, query: { tab: 'sandbox' } })
}

async function activate() {
  try {
    await api.activateScriptWorkflow(wf.value.id)
    await load()
  } catch (e: any) {
    alert('启用失败：' + (e.message || e))
  }
}

async function deactivate() {
  if (!confirm('停用后不再触发自动调度，确认？')) return
  try {
    await api.deactivateScriptWorkflow(wf.value.id)
    await load()
  } catch (e: any) {
    alert('失败：' + (e.message || e))
  }
}

async function del() {
  if (!confirm('确定删除？此操作不可恢复。')) return
  try {
    await api.deleteScriptWorkflow(wf.value.id)
    goList()
  } catch (e: any) {
    alert('删除失败：' + (e.message || e))
  }
}

function statusLabel(s: string) {
  return ({ draft: '草稿', sandbox_testing: '沙箱试用', active: '已启用', deprecated: '已废弃', failed: '失败' }[s] || s)
}

function runModeLabel(m: string) {
  return ({ auto: 'Agent 自动', manual_sandbox: '人工沙箱', production: '生产' }[m] || m)
}

function formatTime(t: string) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN')
  } catch {
    return t
  }
}

async function load() {
  const id = String(route.params.id || '')
  if (!id) return
  const [w, r, v]: any[] = await Promise.all([
    api.getScriptWorkflow(id),
    api.listScriptWorkflowRuns(id),
    api.listScriptWorkflowVersions(id),
  ])
  wf.value = w
  runs.value = r || []
  versions.value = v || []
}

onMounted(load)
</script>

<style scoped>
.swd { max-width: 1100px; margin: 0 auto; padding: 24px 24px 80px; color: #d8dde6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
.swd-loading { color: #6b7280; padding: 60px; text-align: center; }
.swd-head { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.swd-head h1 { margin: 0; font-size: 22px; flex: 1; }
.swd-back { background: transparent; color: #9aa3b2; border: 1px solid #2c333f; padding: 6px 12px; border-radius: 6px; cursor: pointer; }
.swd-badge { font-size: 11px; padding: 4px 10px; border-radius: 999px; }
.swd-badge.status-draft { background: #2c333f; color: #9aa3b2; }
.swd-badge.status-sandbox_testing { background: #4d3f0c; color: #f5d870; }
.swd-badge.status-active { background: #143b1f; color: #57c785; }
.swd-badge.status-deprecated { background: #1a1c20; color: #6b7280; }
.swd-badge.status-failed { background: #4a1a1a; color: #f57878; }

.swd-meta { background: #0f131a; border: 1px solid #2c333f; border-radius: 8px; padding: 14px 18px; margin-bottom: 16px; }
.swd-meta p { margin: 4px 0; color: #c2c8d4; line-height: 1.7; }
.swd-meta strong { color: #9aa3b2; font-weight: 500; margin-right: 6px; }

.swd-actions { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.swd-actions button { padding: 7px 16px; background: #2c333f; color: #d8dde6; border: none; border-radius: 6px; cursor: pointer; }
.swd-actions .swd-activate { background: #57c785; color: #0b0e14; font-weight: 600; }
.swd-actions .swd-danger { background: transparent; color: #f57878; border: 1px solid #f57878; }

.swd-tabs { display: flex; gap: 0; border-bottom: 1px solid #2c333f; margin-bottom: 12px; }
.swd-tabs button { padding: 10px 18px; background: transparent; border: none; color: #8b94a4; cursor: pointer; }
.swd-tabs button.active { color: #f5d870; border-bottom: 2px solid #f5d870; }

.swd-code pre { background: #0b0e14; color: #c2c8d4; padding: 16px; border-radius: 6px; font-size: 12px; line-height: 1.6; overflow-x: auto; max-height: 600px; }

.swd-runs table { width: 100%; border-collapse: collapse; font-size: 13px; }
.swd-runs th, .swd-runs td { padding: 8px 10px; border-bottom: 1px solid #2c333f; text-align: left; }
.swd-runs th { color: #9aa3b2; font-weight: 500; }
.run-success { color: #57c785; }
.run-failed, .run-timeout { color: #f57878; }
.run-running { color: #f5d870; }

.swd-versions ul { list-style: none; padding: 0; margin: 0; }
.swd-versions li { display: flex; gap: 12px; align-items: center; padding: 10px 12px; border-bottom: 1px solid #2c333f; }
.swd-versions .cur { background: #143b1f; color: #57c785; padding: 2px 8px; border-radius: 999px; font-size: 11px; }
.swd-versions small { margin-left: auto; color: #6b7280; }

.swd-empty { color: #6b7280; padding: 30px; text-align: center; }

html[data-workbench-theme='light'] .swd { color: #1d1d1f; }
html[data-workbench-theme='light'] .swd-loading { color: #86868b; }
html[data-workbench-theme='light'] .swd-head h1 { color: #1d1d1f; }
html[data-workbench-theme='light'] .swd-back { color: #86868b; border-color: rgba(0,0,0,0.1); }
html[data-workbench-theme='light'] .swd-back:hover { background: rgba(0,0,0,0.04); }
html[data-workbench-theme='light'] .swd-badge.status-draft { background: rgba(0,0,0,0.05); color: #86868b; }
html[data-workbench-theme='light'] .swd-badge.status-sandbox_testing { background: #fff8e1; color: #9a7b00; }
html[data-workbench-theme='light'] .swd-badge.status-active { background: #e8f8ef; color: #1a7f37; }
html[data-workbench-theme='light'] .swd-badge.status-deprecated { background: rgba(0,0,0,0.05); color: #86868b; }
html[data-workbench-theme='light'] .swd-badge.status-failed { background: #ffe5e5; color: #d32f2f; }
html[data-workbench-theme='light'] .swd-meta { background: #ffffff; border-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .swd-meta p { color: #1d1d1f; }
html[data-workbench-theme='light'] .swd-meta strong { color: #86868b; }
html[data-workbench-theme='light'] .swd-actions button { background: rgba(0,0,0,0.05); color: #1d1d1f; }
html[data-workbench-theme='light'] .swd-actions button:hover { background: rgba(0,0,0,0.08); }
html[data-workbench-theme='light'] .swd-actions .swd-activate { background: #34c759; color: #ffffff; }
html[data-workbench-theme='light'] .swd-actions .swd-danger { background: transparent; color: #ff3b30; border-color: #ff3b30; }
html[data-workbench-theme='light'] .swd-tabs { border-bottom-color: rgba(0,0,0,0.1); }
html[data-workbench-theme='light'] .swd-tabs button { color: #86868b; }
html[data-workbench-theme='light'] .swd-tabs button.active { color: #0071e3; border-bottom-color: #0071e3; }
html[data-workbench-theme='light'] .swd-code pre { background: #f5f5f7; color: #1d1d1f; }
html[data-workbench-theme='light'] .swd-runs th, html[data-workbench-theme='light'] .swd-runs td { border-bottom-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .swd-runs th { color: #86868b; }
html[data-workbench-theme='light'] .run-success { color: #1a7f37; }
html[data-workbench-theme='light'] .run-failed, html[data-workbench-theme='light'] .run-timeout { color: #d32f2f; }
html[data-workbench-theme='light'] .run-running { color: #9a7b00; }
html[data-workbench-theme='light'] .swd-versions li { border-bottom-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .swd-versions .cur { background: #e8f8ef; color: #1a7f37; }
html[data-workbench-theme='light'] .swd-versions small { color: #86868b; }
html[data-workbench-theme='light'] .swd-empty { color: #86868b; }
</style>
