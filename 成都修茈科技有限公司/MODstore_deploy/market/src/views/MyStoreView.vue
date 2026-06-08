<template>
  <div class="store-page">
    <h1 class="page-title">已购资产</h1>
    <p class="page-sub">您在市场中购买的 MOD、AI 员工、提示词、Skill、TTS 模型与设计素材等，可在此下载；自制上架请前往工作台。</p>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <div v-else>
      <div class="entitlement-card" v-if="myPlan">
        <h3>当前套餐：{{ myPlan.name }}</h3>
        <p class="plan-expire">到期时间：{{ formatDateTime(myPlan.expires_at) }}</p>
        <div class="quota-row" v-if="quotas.length">
          <span v-for="q in quotas" :key="q.quota_type" class="quota-pill">
            {{ quotaLabel(q.quota_type) }} {{ q.remaining }}/{{ q.total }}
          </span>
        </div>
      </div>
      <div v-if="items.length === 0" class="empty-state">
        <p>您还没有购买任何商品</p>
        <div class="empty-actions">
          <router-link :to="{ name: 'ai-store' }" class="btn btn-primary-solid">去 AI 市场逛逛</router-link>
          <router-link :to="{ name: 'workbench-employee' }" class="btn btn-secondary">工作台 · 员工制作</router-link>
        </div>
      </div>
      <div v-else class="grid">
        <div v-for="p in items" :key="p.purchase_id" class="mod-card">
          <div class="card-badges">
            <span class="artifact-badge" :class="'artifact-' + (p.artifact || 'mod')">{{ artifactLabel(p.artifact) }}</span>
          </div>
          <h3 class="mod-name">{{ p.name }}</h3>
          <p class="mod-meta">{{ p.pkg_id }} · v{{ p.version }}</p>
          <p class="mod-purchase-info">购买于 {{ formatDate(p.purchased_at) }} · ¥{{ Number(p.price_paid ?? 0).toFixed(2) }}</p>
          <button class="btn btn-success" @click="doDownload(p.catalog_id ?? p.purchase_id)">下载</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'

interface PurchasedItem {
  purchase_id: number | string
  catalog_id?: number | string
  artifact?: string
  name?: string
  pkg_id?: string
  version?: string
  purchased_at?: string
  price_paid?: number
}

interface PlanInfo {
  name?: string
  expires_at?: string
}

interface QuotaRow {
  quota_type: string
  remaining?: number
  total?: number
}

const items = ref<PurchasedItem[]>([])
const loading = ref(true)
const err = ref('')
const myPlan = ref<PlanInfo | null>(null)
const quotas = ref<QuotaRow[]>([])

function artifactLabel(a: string | undefined): string {
  const x = (a || 'mod').toLowerCase()
  if (x === 'employee_pack') return '员工包'
  if (x === 'bundle') return '组合包'
  return 'Mod'
}

onMounted(() => loadStore())

async function loadStore() {
  loading.value = true
  err.value = ''
  try {
    const [res, planRes] = await Promise.all([api.myStore(), api.paymentMyPlan()])
    items.value = res.items
    myPlan.value = planRes.plan
    quotas.value = planRes.quotas || []
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
}

function quotaLabel(t: string): string {
  const m: Record<string, string> = {
    employee_count: '员工数',
    llm_calls: 'LLM 调用',
    storage_mb: '存储(MB)',
  }
  return m[t] || t
}

async function doDownload(id: number | string) {
  try {
    await api.downloadItem(id)
  } catch (e) {
    alert((e as Error)?.message || String(e))
  }
}

function formatDate(iso: string | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('zh-CN')
}

function formatDateTime(iso: string | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<style scoped>
.store-page {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding-inline: var(--layout-pad-x);
  box-sizing: border-box;
}
.page-title { font-size: 22px; margin-bottom: 8px; color: #ffffff; }
.page-sub { font-size: 13px; color: rgba(255,255,255,0.45); margin: 0 0 20px; line-height: 1.5; }
.entitlement-card { margin-bottom: 16px; border: 0.5px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 14px; background: rgba(255,255,255,0.03); }
.entitlement-card h3 { margin: 0 0 8px; font-size: 15px; }
.plan-expire { margin: 0 0 10px; color: rgba(255,255,255,0.55); font-size: 12px; }
.quota-row { display: flex; gap: 8px; flex-wrap: wrap; }
.quota-pill { font-size: 12px; padding: 4px 8px; border-radius: 999px; background: rgba(129,140,248,0.16); color: #c7d2fe; }
.mod-card { background: #111111; border-radius: 12px; border: 0.5px solid rgba(255,255,255,0.1); padding: 20px; }
.card-badges { margin-bottom: 10px; }
.artifact-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.65);
}
.artifact-employee_pack { background: rgba(129,140,248,0.15); color: #a5b4fc; }
.artifact-bundle { background: rgba(251,191,36,0.12); color: #fbbf24; }
.artifact-mod { background: rgba(96,165,250,0.12); color: #93c5fd; }
.mod-name { font-size: 16px; font-weight: 600; color: #ffffff; margin-bottom: 6px; }
.mod-meta { font-size: 13px; color: rgba(255,255,255,0.3); margin-bottom: 8px; }
.mod-purchase-info { font-size: 12px; color: rgba(255,255,255,0.5); margin-bottom: 12px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 17.5rem), 1fr));
  gap: 16px;
}
.flash { padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
.flash-err { background: rgba(255,80,80,0.1); color: #ff6b6b; }
.loading { text-align: center; padding: 40px; color: rgba(255,255,255,0.4); }
.empty-state { text-align: center; padding: 60px 20px; }
.empty-state > p:first-of-type { color: rgba(255,255,255,0.55); margin-bottom: 8px; font-size: 1.05rem; }
.empty-hint { font-size: 13px; color: rgba(255,255,255,0.35); margin-bottom: 24px; line-height: 1.5; }
.empty-actions { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; align-items: center; }
.btn { display: inline-block; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; text-decoration: none; border: none; cursor: pointer; }
.btn-primary-solid { background: #ffffff; color: #0a0a0a; }
.btn-secondary { background: transparent; color: rgba(255,255,255,0.75); border: 0.5px solid rgba(255,255,255,0.2); }
.btn-secondary:hover { background: rgba(255,255,255,0.06); color: #fff; }
.btn-success { background: rgba(74,222,128,0.15); color: #4ade80; border: none; cursor: pointer; }
.btn-success:hover { background: rgba(74,222,128,0.25); }

html[data-workbench-theme='light'] .store-page { background: #f5f5f7; color: #1d1d1f; }
html[data-workbench-theme='light'] .page-title { color: #1d1d1f; }
html[data-workbench-theme='light'] .page-sub { color: #86868b; }
html[data-workbench-theme='light'] .entitlement-card { border-color: rgba(0,0,0,0.08); background: #ffffff; }
html[data-workbench-theme='light'] .entitlement-card h3 { color: #1d1d1f; }
html[data-workbench-theme='light'] .plan-expire { color: #86868b; }
html[data-workbench-theme='light'] .quota-pill { background: rgba(0,113,227,0.08); color: #0071e3; }
html[data-workbench-theme='light'] .mod-card { background: #ffffff; border-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .artifact-badge { background: rgba(0,0,0,0.04); color: #86868b; }
html[data-workbench-theme='light'] .artifact-employee_pack { background: rgba(0,113,227,0.08); color: #0071e3; }
html[data-workbench-theme='light'] .artifact-bundle { background: rgba(245,158,11,0.08); color: #b45309; }
html[data-workbench-theme='light'] .artifact-mod { background: rgba(0,113,227,0.08); color: #0071e3; }
html[data-workbench-theme='light'] .mod-name { color: #1d1d1f; }
html[data-workbench-theme='light'] .mod-meta { color: rgba(0,0,0,0.3); }
html[data-workbench-theme='light'] .mod-purchase-info { color: #86868b; }
html[data-workbench-theme='light'] .flash-err { background: rgba(220,53,69,0.08); color: #dc2626; }
html[data-workbench-theme='light'] .loading { color: #86868b; }
html[data-workbench-theme='light'] .empty-state > p:first-of-type { color: #1d1d1f; }
html[data-workbench-theme='light'] .empty-hint { color: #86868b; }
html[data-workbench-theme='light'] .btn-primary-solid { background: #0071e3; color: #ffffff; }
html[data-workbench-theme='light'] .btn-secondary { color: #0071e3; border-color: rgba(0,113,227,0.3); }
html[data-workbench-theme='light'] .btn-secondary:hover { background: rgba(0,113,227,0.06); color: #005bb5; }
html[data-workbench-theme='light'] .btn-success { background: rgba(34,197,94,0.08); color: #16a34a; }
html[data-workbench-theme='light'] .btn-success:hover { background: rgba(34,197,94,0.15); }
</style>
