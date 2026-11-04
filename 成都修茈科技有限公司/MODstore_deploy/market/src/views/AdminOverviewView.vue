<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

const stats = ref<Record<string, unknown>>({})
const loading = ref(false)
const error = ref('')
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : '待核实'

async function load() {
  loading.value = true
  error.value = ''
  stats.value = {}
  try {
    const result = await api.adminStatus()
    if (result.ok !== true) throw new Error('市场概览暂时不可用')
    stats.value = result
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '市场概览加载失败，请重试'
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div class="admin-overview">
    <header><h1 class="page-title">智能生态市场总览</h1><button type="button" :disabled="loading" @click="load">刷新</button></header>
    <p>查看服务端全量市场目录与注册账号规模。</p>
    <p v-if="loading" role="status">正在加载市场概览…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <section v-else class="stats" aria-label="市场统计">
      <article><span>市场商品总数</span><strong>{{ count(stats.total_catalog_items) }}</strong></article>
      <article><span>注册用户</span><strong>{{ count(stats.total_users) }}</strong></article>
    </section>
    <router-link :to="{ name: 'admin-database' }">打开数据库明细 →</router-link>
  </div>
</template>

<style scoped>
.admin-overview { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 1rem; margin: 1.5rem 0; }
article { display: grid; gap: .5rem; padding: 1.25rem; border: 1px solid #8885; border-radius: 12px; background: #8881; }
strong { font-size: 2rem; }
[role="alert"] { color: #d43e3e; }
</style>
