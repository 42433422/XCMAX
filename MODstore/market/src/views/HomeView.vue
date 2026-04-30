<template>
  <div>
    <div class="toolbar">
      <input
        class="input search-input"
        v-model="query"
        placeholder="搜索 Mod..."
        @keyup.enter="loadCatalog"
      />
      <button class="btn btn-primary-solid" type="button" @click="loadCatalog">搜索</button>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <div v-else>
      <div class="grid">
        <div v-for="item in items" :key="item.id" class="mod-card">
          <div class="mod-card-header">
            <h3 class="mod-name">{{ item.name }}</h3>
            <span class="mod-price" :class="{ free: item.price <= 0 }">
              {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
            </span>
          </div>
          <p class="mod-desc">{{ item.description || '暂无描述' }}</p>
          <div class="mod-meta">
            <span class="mod-id">{{ item.pkg_id }}</span>
            <span class="mod-version">v{{ item.version }}</span>
          </div>
          <div class="mod-actions">
            <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn">详情</router-link>
            <template v-if="item.purchased">
              <span class="owned-badge">已拥有</span>
            </template>
            <template v-else>
              <button class="btn btn-primary-solid" type="button" @click="doBuy(item)" :disabled="buyingId === item.id">
                {{ buyingId === item.id ? '购买中...' : '购买' }}
              </button>
            </template>
          </div>
        </div>
      </div>
      <div v-if="items.length === 0" class="empty-state">暂无商品</div>
      <div class="pagination" v-if="total > limit">
        <button class="btn" type="button" :disabled="offset === 0" @click="goPrev">上一页</button>
        <span class="page-info">{{ offset / limit + 1 }} / {{ Math.ceil(total / limit) }}</span>
        <button class="btn" type="button" :disabled="offset + limit >= total" @click="goNext">下一页</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const items = ref([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const query = ref('')
const buyingId = ref(null)
const limit = 20
const offset = ref(0)

onMounted(() => loadCatalog())

async function loadCatalog() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.catalog(query.value, '', limit, offset.value)
    items.value = res.items
    total.value = res.total
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

async function doBuy(item) {
  if (!localStorage.getItem('modstore_token')) {
    window.location.href = '/login?redirect=/'
    return
  }
  buyingId.value = item.id
  try {
    const res = await api.buyItem(item.id)
    alert(res.message)
    await loadCatalog()
  } catch (e) {
    alert(e.message)
  } finally {
    buyingId.value = null
  }
}

function goPrev() {
  offset.value -= limit
  loadCatalog()
}
function goNext() {
  offset.value += limit
  loadCatalog()
}
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  max-width: 500px;
  margin-bottom: 24px;
}
.search-input {
  flex: 1;
}

.mod-card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  padding: 20px;
  display: flex;
  flex-direction: column;
}
.mod-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}
.mod-name {
  font-size: 16px;
  font-weight: 600;
  color: #1a1a2e;
}
.mod-price {
  font-size: 14px;
  font-weight: 700;
  color: #e74c3c;
  white-space: nowrap;
}
.mod-price.free {
  color: #2d6a4f;
}
.mod-desc {
  font-size: 13px;
  color: #666;
  margin-bottom: 12px;
  flex: 1;
  min-height: 36px;
}
.mod-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #999;
}
.mod-id {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 3px;
}
.mod-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.owned-badge {
  font-size: 13px;
  color: #2d6a4f;
  background: #d8f3dc;
  padding: 4px 10px;
  border-radius: 12px;
}

.loading {
  text-align: center;
  padding: 40px;
  color: #999;
}
.empty-state {
  text-align: center;
  padding: 40px;
  color: #999;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 24px;
}
.page-info {
  font-size: 14px;
  color: #666;
}
</style>
