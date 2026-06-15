<template>
  <div class="admin-view">
    <h1 class="page-title">管理员面板</h1>
    <div class="admin-links">
      <router-link to="/admin/database" class="admin-card">
        <div class="admin-card-icon">📊</div>
        <h2 class="admin-card-title">数据库管理</h2>
        <p class="admin-card-desc">查看所有用户、钱包、商品和交易记录</p>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const isAdmin = ref(false)

onMounted(async () => {
  try {
    const me = await api.me()
    isAdmin.value = me.is_admin === true
    if (!isAdmin.value) {
      router.push('/')
      return
    }
  } catch {
    router.push('/login')
  }
})
</script>

<style scoped>
.admin-view {
  max-width: 600px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-title {
  font-size: 1.75rem;
  margin-bottom: 1.5rem;
  color: #ffffff;
}

.admin-links {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.admin-card {
  display: block;
  padding: 1.5rem;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  text-decoration: none;
  transition: all 0.2s;
}

.admin-card:hover {
  background: rgba(255,255,255,0.03);
  border-color: rgba(255,255,255,0.2);
}

.admin-card-icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.admin-card-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.25rem;
}

.admin-card-desc {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.4);
  margin: 0;
}
</style>
