<template>
  <div class="admin-view">
    <h1 class="page-title">智能生态市场总览</h1>
    <p class="intro">查看市场目录与账号规模。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="loading" role="status">正在加载市场概览…</p>
    <section v-else class="stats" aria-label="市场统计">
      <article class="stat-card">
        <span>市场商品总数</span>
        <strong>{{ stats.total_catalog_items ?? '—' }}</strong>
      </article>
      <article class="stat-card">
        <span>注册用户</span>
        <strong>{{ stats.total_users ?? '—' }}</strong>
      </article>
    </section>
    <div class="admin-links">
      <router-link to="/admin/database" class="admin-card">
        <span aria-hidden="true">📊</span>
        <span>打开数据库明细 →</span>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

const stats = ref<{ total_catalog_items?: number; total_users?: number }>({})
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    stats.value = await api.adminStatus()
  } catch (e) {
    error.value = e instanceof Error ? `市场概览加载失败：${e.message}` : '市场概览加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.admin-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-title {
  font-size: 1.75rem;
  margin-bottom: 0.5rem;
  color: #ffffff;
}

.intro {
  color: rgba(255, 255, 255, 0.62);
  margin-bottom: 1.5rem;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.stat-card,
.admin-card {
  padding: 1.25rem;
  background: #111;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
}
.stat-card {
  display: grid;
  gap: 0.5rem;
  color: rgba(255, 255, 255, 0.65);
}
.stat-card strong {
  color: #fff;
  font-size: 2rem;
}
.loading {
  color: rgba(255, 255, 255, 0.65);
  padding: 1rem 0;
}
.error {
  color: #ffb4b4;
  padding: 1rem;
  background: rgba(180, 35, 35, 0.16);
  border-radius: 8px;
}
.admin-links {
  margin-top: 1rem;
}

.admin-card {
  display: flex;
  gap: 0.7rem;
  align-items: center;
  text-decoration: none;
  color: #fff;
}
</style>
