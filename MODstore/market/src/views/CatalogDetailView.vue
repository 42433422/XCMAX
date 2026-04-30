<template>
  <div>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <template v-else-if="item">
      <div class="detail-header">
        <div>
          <h1>{{ item.name }}</h1>
          <p class="meta">{{ item.pkg_id }} · v{{ item.version }} · {{ item.artifact }}</p>
          <p v-if="item.description" class="desc">{{ item.description }}</p>
        </div>
        <div class="detail-actions">
          <span class="price-tag" :class="{ free: item.price <= 0 }">
            {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
          </span>
          <template v-if="item.purchased">
            <button class="btn btn-success" @click="doDownload">下载</button>
            <span class="owned-badge">已拥有</span>
          </template>
          <template v-else>
            <button class="btn btn-primary-solid" @click="doBuy" :disabled="buying">
              {{ buying ? '购买中...' : '购买' }}
            </button>
          </template>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const item = ref(null)
const loading = ref(true)
const err = ref('')
const buying = ref(false)

onMounted(async () => {
  try {
    item.value = await api.catalogDetail(route.params.id)
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
})

async function doBuy() {
  if (!localStorage.getItem('modstore_token')) {
    window.location.href = `/login?redirect=/catalog/${route.params.id}`
    return
  }
  buying.value = true
  try {
    const res = await api.buyItem(route.params.id)
    alert(res.message)
    item.value = await api.catalogDetail(route.params.id)
  } catch (e) {
    alert(e.message)
  } finally {
    buying.value = false
  }
}

async function doDownload() {
  try {
    await api.downloadItem(route.params.id)
  } catch (e) {
    alert(e.message)
  }
}
</script>

<style scoped>
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; }
.detail-header h1 { font-size: 24px; color: #1a1a2e; margin-bottom: 8px; }
.meta { font-size: 13px; color: #999; margin-bottom: 8px; }
.desc { font-size: 14px; color: #555; max-width: 600px; }
.detail-actions { display: flex; gap: 12px; align-items: center; flex-shrink: 0; }
.price-tag { font-size: 20px; font-weight: 700; color: #e74c3c; }
.price-tag.free { color: #2d6a4f; }
.owned-badge { font-size: 14px; color: #2d6a4f; background: #d8f3dc; padding: 6px 14px; border-radius: 12px; }
.loading { text-align: center; padding: 40px; color: #999; }
</style>
