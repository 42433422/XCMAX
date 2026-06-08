<template>
  <div class="swl">
    <header class="swl-head">
      <h1>脚本工作流</h1>
      <p class="swl-tip">每个工作流就是一个独立的 Python 脚本。AI 帮你写、沙箱跑通、你点启用。</p>
      <button class="swl-new" @click="goNew">+ 新建脚本工作流</button>
    </header>

    <div class="swl-filter">
      <button v-for="t in tabs" :key="t.value" :class="{ active: filter === t.value }" @click="filter = t.value">
        {{ t.label }}
        <span v-if="counts[t.value] !== undefined" class="swl-count">{{ counts[t.value] }}</span>
      </button>
    </div>

    <p v-if="loading" class="swl-empty">加载中…</p>
    <p v-else-if="visible.length === 0" class="swl-empty">
      还没有脚本工作流，点击右上角「新建」开始用 AI 写一个吧。
    </p>

    <ul class="swl-list">
      <li v-for="wf in visible" :key="wf.id" class="swl-card" @click="goDetail(wf.id)">
        <header>
          <h2>{{ wf.name }}</h2>
          <span class="swl-badge" :class="`status-${wf.status}`">{{ statusLabel(wf.status) }}</span>
        </header>
        <p class="swl-goal">{{ formatBriefGoalForDisplay(wf.brief?.goal) }}</p>
        <footer>
          <small>更新于 {{ formatTime(wf.updated_at) }}</small>
          <small v-if="wf.migrated_from_workflow_id">迁移自旧工作流 #{{ wf.migrated_from_workflow_id }}</small>
        </footer>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { formatBriefGoalForDisplay } from '../utils/planMdDisplay'

interface Wf {
  id: number
  name: string
  status: string
  brief: any
  updated_at: string
  migrated_from_workflow_id: number | null
}

const router = useRouter()
const list = ref<Wf[]>([])
const loading = ref(true)
const filter = ref<string>('')

const tabs = [
  { label: '全部', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '沙箱试用', value: 'sandbox_testing' },
  { label: '已启用', value: 'active' },
  { label: '已废弃', value: 'deprecated' },
  { label: '失败', value: 'failed' },
]

const counts = computed<Record<string, number>>(() => {
  const c: Record<string, number> = { '': list.value.length }
  for (const wf of list.value) c[wf.status] = (c[wf.status] || 0) + 1
  return c
})

const visible = computed(() => {
  if (!filter.value) return list.value
  return list.value.filter((wf) => wf.status === filter.value)
})

function goNew() {
  router.push({ name: 'workbench-script-workflow-new' })
}

function goDetail(id: number) {
  router.push({ name: 'workbench-script-workflow-detail', params: { id } })
}

function statusLabel(status: string) {
  return (
    {
      draft: '草稿',
      sandbox_testing: '沙箱试用',
      active: '已启用',
      deprecated: '已废弃',
      failed: '失败',
    }[status] || status
  )
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
  loading.value = true
  try {
    const rows: any = await api.listScriptWorkflows()
    list.value = rows || []
  } catch (e: any) {
    alert('加载失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.swl { max-width: 1100px; margin: 0 auto; padding: 24px 24px 80px; color: #d8dde6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
.swl-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 16px; margin-bottom: 16px; }
.swl-head h1 { margin: 0; font-size: 22px; flex: 1; }
.swl-tip { color: #9aa3b2; flex-basis: 100%; margin: 0 0 12px; }
.swl-new { background: #f5d870; color: #0b0e14; font-weight: 600; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; }

.swl-filter { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
.swl-filter button { padding: 6px 14px; background: transparent; color: #9aa3b2; border: 1px solid #2c333f; border-radius: 999px; cursor: pointer; font-size: 13px; }
.swl-filter button.active { color: #f5d870; border-color: #f5d870; }
.swl-count { display: inline-block; margin-left: 6px; padding: 1px 8px; background: #2c333f; color: #c2c8d4; border-radius: 999px; font-size: 11px; }

.swl-empty { color: #6b7280; padding: 40px; text-align: center; background: #0f131a; border: 1px dashed #2c333f; border-radius: 8px; }
.swl-list { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.swl-card { background: #0f131a; border: 1px solid #2c333f; border-radius: 8px; padding: 16px; cursor: pointer; transition: border-color 0.2s; }
.swl-card:hover { border-color: #f5d870; }
.swl-card header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.swl-card h2 { margin: 0; font-size: 15px; color: #d8dde6; }
.swl-badge { font-size: 11px; padding: 2px 10px; border-radius: 999px; }
.swl-badge.status-draft { background: #2c333f; color: #9aa3b2; }
.swl-badge.status-sandbox_testing { background: #4d3f0c; color: #f5d870; }
.swl-badge.status-active { background: #143b1f; color: #57c785; }
.swl-badge.status-deprecated { background: #1a1c20; color: #6b7280; }
.swl-badge.status-failed { background: #4a1a1a; color: #f57878; }
.swl-goal { color: #9aa3b2; font-size: 13px; line-height: 1.6; margin: 0; max-height: 4.8em; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.swl-card footer { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; color: #6b7280; font-size: 11px; }

html[data-workbench-theme='light'] .swl { color: #1d1d1f; }
html[data-workbench-theme='light'] .swl-head h1 { color: #1d1d1f; }
html[data-workbench-theme='light'] .swl-tip { color: #86868b; }
html[data-workbench-theme='light'] .swl-new { background: #0071e3; color: #ffffff; }
html[data-workbench-theme='light'] .swl-filter button { color: #86868b; border-color: rgba(0,0,0,0.1); }
html[data-workbench-theme='light'] .swl-filter button.active { color: #0071e3; border-color: #0071e3; }
html[data-workbench-theme='light'] .swl-count { background: rgba(0,0,0,0.06); color: #86868b; }
html[data-workbench-theme='light'] .swl-empty { color: #86868b; background: #ffffff; border-color: rgba(0,0,0,0.08); }
html[data-workbench-theme='light'] .swl-card { background: #ffffff; border-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .swl-card:hover { border-color: #0071e3; }
html[data-workbench-theme='light'] .swl-card h2 { color: #1d1d1f; }
html[data-workbench-theme='light'] .swl-badge.status-draft { background: rgba(0,0,0,0.05); color: #86868b; }
html[data-workbench-theme='light'] .swl-badge.status-sandbox_testing { background: #fff8e1; color: #9a7b00; }
html[data-workbench-theme='light'] .swl-badge.status-active { background: #e8f8ef; color: #1a7f37; }
html[data-workbench-theme='light'] .swl-badge.status-deprecated { background: rgba(0,0,0,0.05); color: #86868b; }
html[data-workbench-theme='light'] .swl-badge.status-failed { background: #ffe5e5; color: #d32f2f; }
html[data-workbench-theme='light'] .swl-goal { color: #86868b; }
html[data-workbench-theme='light'] .swl-card footer { color: #86868b; }
</style>
