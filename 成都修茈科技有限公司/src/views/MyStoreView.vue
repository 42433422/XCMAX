<template>
  <div>
    <h1 class="page-title">我的商店</h1>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <div v-else>
      <div v-if="items.length === 0" class="empty-state">
        <p>你还没有购买任何 Mod</p>
        <router-link to="/" class="btn btn-primary-solid">去市场逛逛</router-link>
      </div>
      <div v-else class="grid">
        <div v-for="p in items" :key="p.purchase_id" class="mod-card">
          <h3 class="mod-name">{{ p.name }}</h3>
          <p class="mod-meta">{{ p.pkg_id }} · v{{ p.version }}</p>
          <p class="mod-purchase-info">购买于 {{ formatDate(p.purchased_at) }} · ¥{{ p.price_paid.toFixed(2) }}</p>
          <button class="btn btn-success" @click="doDownload(p.catalog_id)">下载</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'

const items = ref([])
const loading = ref(true)
const err = ref('')

onMounted(() => loadStore())

async function loadStore() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.myStore()
    items.value = res.items
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

async function doDownload(id) {
  try {
    await api.downloadItem(id)
  } catch (e) {
    alert(e.message)
  }
}

function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #ffffff; }
.mod-card { background: #111111; border-radius: 12px; border: 0.5px solid rgba(255,255,255,0.1); padding: 20px; }
.mod-name { font-size: 16px; font-weight: 600; color: #ffffff; margin-bottom: 6px; }
.mod-meta { font-size: 13px; color: rgba(255,255,255,0.3); margin-bottom: 8px; }
.mod-purchase-info { font-size: 12px; color: rgba(255,255,255,0.5); margin-bottom: 12px; }
.loading { text-align: center; padding: 40px; color: rgba(255,255,255,0.4); }
.empty-state { text-align: center; padding: 60px 20px; }
.empty-state p { color: rgba(255,255,255,0.4); margin-bottom: 16px; }
</style>
