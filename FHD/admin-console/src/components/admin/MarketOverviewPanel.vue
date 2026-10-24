<template>
  <div class="market-overview-panel" data-testid="market-overview-panel">
    <header class="page-header">
      <div>
        <h2>智能生态市场总览</h2>
        <p class="muted">
          管理端正式入口：查看市场目录规模与注册账号等业务指标（非 Full-Pipeline / iframe 嵌套）。
        </p>
      </div>
      <div class="header-actions">
        <button type="button" class="btn btn-secondary" :disabled="loading" @click="load">
          {{ loading ? '读取中…' : '刷新指标' }}
        </button>
      </div>
    </header>

    <div v-if="loadError" class="admin-card overview-banner" role="alert">
      <strong>市场指标暂未能加载</strong>
      <p class="muted">{{ loadError }}</p>
      <button type="button" class="btn btn-primary" @click="load">重试</button>
    </div>

    <div v-else-if="loading" class="admin-card overview-banner" role="status">正在加载市场业务指标…</div>

    <template v-else>
      <section class="overview-kpis" aria-label="市场业务指标">
        <article class="admin-card kpi">
          <div class="kpi-num">{{ catalogLabel }}</div>
          <div class="kpi-label">市场商品总数</div>
        </article>
        <article class="admin-card kpi">
          <div class="kpi-num">{{ usersLabel }}</div>
          <div class="kpi-label">注册用户</div>
        </article>
        <article class="admin-card kpi kpi-wide">
          <div class="kpi-label">说明</div>
          <p class="kpi-text">
            指标来自市场管理接口 <code>/api/admin/status</code>（经管理端 market-proxy）。用于核对目录与账号规模是否完整。
          </p>
        </article>
      </section>

      <section class="admin-card overview-links" aria-label="相关入口">
        <h3>相关页面</h3>
        <ul>
          <li><router-link :to="{ name: 'admin-entitlements' }">用户与权益管理</router-link></li>
          <li><router-link :to="{ name: 'delivery-center' }">客户交付中心</router-link></li>
          <li><router-link :to="{ name: 'server-functions' }">服务器功能模块（含每日摘要存档）</router-link></li>
        </ul>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { xcmaxMarketProxy } from '@/api/xcmaxMarketProxy'
import {
  formatMetric,
  parseMarketOverviewStats,
  type MarketOverviewStats,
} from '../../utils/marketOverviewMetrics'

const loading = ref(true)
const loadError = ref('')
const stats = ref<MarketOverviewStats | null>(null)

const catalogLabel = computed(() => formatMetric(stats.value?.totalCatalogItems ?? null))
const usersLabel = computed(() => formatMetric(stats.value?.totalUsers ?? null))

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const payload = await xcmaxMarketProxy.adminMarketStatus()
    const parsed = parseMarketOverviewStats(payload)
    if (!parsed.ok) {
      loadError.value = '市场概览暂时不可用（接口未返回 ok）'
      stats.value = parsed
      return
    }
    stats.value = parsed
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '市场概览加载失败，请稍后重试'
    stats.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.market-overview-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.page-header h2 {
  margin: 0;
  color: var(--admin-text, #172033);
}
.muted {
  color: var(--admin-muted, #64748b);
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.5;
}
.overview-banner {
  padding: 16px;
  display: grid;
  gap: 8px;
}
.overview-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.kpi {
  padding: 16px;
}
.kpi-num {
  font-size: 28px;
  font-weight: 700;
  color: var(--admin-text, #172033);
  line-height: 1.2;
}
.kpi-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--admin-muted, #64748b);
}
.kpi-wide {
  grid-column: span 1;
}
.kpi-text {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--admin-text, #172033);
  line-height: 1.5;
}
.overview-links {
  padding: 16px;
}
.overview-links h3 {
  margin: 0 0 8px;
  font-size: 15px;
  color: var(--admin-text, #172033);
}
.overview-links ul {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
}
.overview-links a {
  color: var(--admin-primary, #1677ff);
}
</style>
