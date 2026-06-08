<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api'

interface GraphNode {
  local_id: number
  node_type: string
  name: string
  config: Record<string, unknown>
  position_x: number
  position_y: number
}

interface GraphEdge {
  source_local_id: number
  target_local_id: number
  condition: string
}

interface TemplateDetail {
  id: number
  pkg_id: string
  name: string
  description: string
  version: string
  price: number
  industry: string
  template_category: string
  template_difficulty: string
  difficulty_label: string
  install_count: number
  created_at: string | null
  graph: {
    name: string
    description: string
    nodes: GraphNode[]
    edges: GraphEdge[]
    node_count: number
    edge_count: number
  }
}

const route = useRoute()
const router = useRouter()

const detail = ref<TemplateDetail | null>(null)
const loading = ref(false)
const errMsg = ref('')
const installing = ref(false)

const templateId = computed(() => Number(route.params.id || 0))

async function load() {
  if (!templateId.value) return
  loading.value = true
  errMsg.value = ''
  try {
    detail.value = (await api.templateDetail(templateId.value)) as TemplateDetail
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function install() {
  if (!templateId.value) return
  if (!confirm('一键安装此模板到你的工作流？将创建一个新的可编辑副本。')) return
  installing.value = true
  try {
    const r: any = await api.templateInstall(templateId.value)
    if (r?.workflow_id) {
      router.push({ name: 'workflow-v2-editor', params: { id: String(r.workflow_id) } })
    }
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '安装失败'
  } finally {
    installing.value = false
  }
}

function nodeKindLabel(kind: string): string {
  const m: Record<string, string> = {
    start: '开始',
    end: '结束',
    employee: 'AI 员工',
    condition: '条件分支',
    openapi_operation: 'OpenAPI 调用',
    knowledge_search: '知识检索',
    webhook_trigger: 'Webhook 触发器',
    cron_trigger: '定时触发器',
    variable_set: '变量赋值',
  }
  return m[kind] || kind
}
</script>

<template>
  <main class="td">
    <header class="td__crumbs">
      <button class="td__crumb" type="button" @click="router.push({ name: 'templates' })">
        ← 返回模板市场
      </button>
    </header>

    <div v-if="loading" class="td__placeholder">加载中…</div>
    <div v-else-if="errMsg" class="td__err">{{ errMsg }}</div>
    <div v-else-if="!detail" class="td__placeholder">模板不存在或已下架</div>

    <article v-else class="td__main">
      <header class="td__head">
        <div class="td__chips">
          <span class="td__chip td__chip--cat">{{ detail.template_category || '通用' }}</span>
          <span v-if="detail.difficulty_label" class="td__chip td__chip--diff">{{ detail.difficulty_label }}</span>
          <span class="td__chip td__chip--mute">{{ detail.industry || '通用' }}</span>
          <span class="td__chip td__chip--mute">v{{ detail.version }}</span>
        </div>
        <h1 class="td__name">{{ detail.name }}</h1>
        <p class="td__desc">{{ detail.description || '该模板暂无描述' }}</p>
        <div class="td__metrics">
          <span><strong>{{ detail.install_count }}</strong> 次安装</span>
          <span :class="{ 'td__metric--paid': detail.price > 0 }">
            {{ detail.price > 0 ? `¥ ${detail.price.toFixed(2)}` : '免费' }}
          </span>
          <span class="td__spacer" />
          <button class="td__btn td__btn--primary" type="button" :disabled="installing" @click="install">
            {{ installing ? '安装中…' : '一键安装到工作流' }}
          </button>
        </div>
      </header>

      <section class="td__section">
        <h2>包含的节点（{{ detail.graph.node_count }} 个）</h2>
        <ul class="td__nodes">
          <li v-for="n in detail.graph.nodes" :key="n.local_id" class="td__node">
            <span class="td__node-kind">{{ nodeKindLabel(n.node_type) }}</span>
            <span class="td__node-name">{{ n.name }}</span>
          </li>
        </ul>
      </section>

      <section class="td__section">
        <h2>连线（{{ detail.graph.edge_count }} 条）</h2>
        <p v-if="!detail.graph.edges.length" class="td__hint">该模板还没有连线</p>
        <ul v-else class="td__edges">
          <li v-for="(e, idx) in detail.graph.edges" :key="idx" class="td__edge">
            <code>{{ e.source_local_id }} → {{ e.target_local_id }}</code>
            <span v-if="e.condition" class="td__edge-cond">条件：{{ e.condition }}</span>
          </li>
        </ul>
      </section>

      <section class="td__section">
        <h2>安装后会发生什么</h2>
        <ul class="td__steps">
          <li>1. 在你的工作流列表创建一个名为 "<strong>{{ detail.name }} (来自模板)</strong>" 的副本</li>
          <li>2. 自动跳转到 v2 可视化编辑器，节点位置和连线已就位</li>
          <li>3. 你可以替换 AI 员工 / 修改判断表达式 / 配置 webhook，无需从零搭起</li>
        </ul>
      </section>
    </article>
  </main>
</template>

<style scoped>
.td {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 24px 72px;
  color: #0f172a;
}

.td__crumbs {
  margin-bottom: 12px;
}

.td__crumb {
  background: transparent;
  border: 0;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
  padding: 0;
}

.td__crumb:hover {
  color: #4f46e5;
}

.td__placeholder,
.td__err {
  padding: 48px 16px;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  color: #64748b;
}

.td__err {
  border-color: #fecaca;
  color: #991b1b;
  background: #fef2f2;
}

.td__main {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 28px 32px;
}

.td__head {
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 18px;
  margin-bottom: 18px;
}

.td__chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.td__chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
}

.td__chip--cat {
  background: #eef2ff;
  color: #3730a3;
  font-weight: 500;
}

.td__chip--diff {
  background: #fef3c7;
  color: #92400e;
}

.td__chip--mute {
  background: #f1f5f9;
  color: #64748b;
}

.td__name {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
}

.td__desc {
  margin: 8px 0 14px;
  color: #475569;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.td__metrics {
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 13px;
  color: #475569;
  flex-wrap: wrap;
}

.td__metrics strong {
  color: #0f172a;
}

.td__metric--paid {
  color: #16a34a;
  font-weight: 600;
}

.td__spacer {
  flex: 1;
}

.td__btn {
  font-size: 13px;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
}

.td__btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.td__btn--primary {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #fff;
}

.td__btn--primary:hover:not(:disabled) {
  background: #4338ca;
}

.td__section {
  margin: 18px 0;
}

.td__section h2 {
  margin: 0 0 10px;
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}

.td__hint {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}

.td__nodes {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.td__node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
}

.td__node-kind {
  font-size: 11px;
  background: #eef2ff;
  color: #3730a3;
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.td__node-name {
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.td__edges {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.td__edge {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
}

.td__edge code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: transparent;
  color: #334155;
}

.td__edge-cond {
  color: #92400e;
  font-size: 11px;
}

.td__steps {
  margin: 0;
  padding: 0;
  list-style: none;
}

.td__steps li {
  padding: 6px 10px;
  border-left: 3px solid #4f46e5;
  background: #f8fafc;
  margin-bottom: 6px;
  font-size: 13px;
  color: #334155;
}
</style>
