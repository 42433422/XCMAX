<template>
  <div class="admin-db-view">
    <h1 class="page-title">数据库管理</h1>

    <div v-if="!isAdmin" class="access-denied">
      <p>需要管理员权限才能访问此页面</p>
      <router-link to="/" class="btn btn-primary">返回首页</router-link>
    </div>

    <template v-else>
      <div class="nav-back">
        <router-link to="/" class="btn btn-back">← 返回首页</router-link>
      </div>

      <div v-if="message" :class="['message', messageOk ? 'message-ok' : 'message-err']">{{ message }}</div>

      <div class="db-refresh">
        <button class="btn btn-refresh" @click="loadDatabase" :disabled="loadingDb">
          {{ loadingDb ? '加载中...' : '刷新数据' }}
        </button>
      </div>

      <div v-if="loadingDb" class="loading">加载数据库...</div>
      <template v-else>
        <!-- Users -->
        <div class="db-section">
          <h3 class="db-title">📋 用户表</h3>
          <p class="db-count">共 {{ dbUsers.length }} 个用户</p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>用户名</th><th>邮箱</th><th>管理员</th><th>注册时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="u in dbUsers" :key="u.id">
                <td>{{ u.id }}</td>
                <td class="username">{{ u.username }}</td>
                <td>{{ u.email || '—' }}</td>
                <td><span :class="['badge', u.is_admin ? 'badge-admin' : 'badge-user']">{{ u.is_admin ? '是' : '否' }}</span></td>
                <td class="time">{{ formatTime(u.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="dbUsers.length === 0" class="db-empty">暂无用户</p>
        </div>

        <!-- Wallets -->
        <div class="db-section">
          <h3 class="db-title">💰 钱包表</h3>
          <p class="db-count">共 {{ dbWallets.length }} 个钱包</p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>用户ID</th><th>余额</th><th>更新时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="w in dbWallets" :key="w.id">
                <td>{{ w.id }}</td>
                <td>{{ w.user_id }}</td>
                <td :class="['amount', w.balance >= 0 ? 'pos' : 'neg']">¥{{ w.balance.toFixed(2) }}</td>
                <td class="time">{{ formatTime(w.updated_at) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="dbWallets.length === 0" class="db-empty">暂无钱包</p>
        </div>

        <!-- Catalog -->
        <div class="db-section">
          <h3 class="db-title">📦 商品目录</h3>
          <p class="db-count">共 {{ dbCatalog.length }} 个商品</p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>名称</th><th>包ID</th><th>版本</th><th>价格</th><th>下载量</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in dbCatalog" :key="item.id">
                <td>{{ item.id }}</td>
                <td class="name">{{ item.name }}</td>
                <td class="pkg">{{ item.pkg_id }}</td>
                <td>{{ item.version }}</td>
                <td :class="['price', item.price <= 0 ? 'free' : 'paid']">{{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}</td>
                <td>{{ item.downloads || 0 }}</td>
                <td class="time">{{ formatTime(item.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="dbCatalog.length === 0" class="db-empty">暂无商品</p>
        </div>

        <!-- Transactions -->
        <div class="db-section">
          <h3 class="db-title">📝 交易记录</h3>
          <p class="db-count">共 {{ dbTransactions.length }} 条记录</p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>用户ID</th><th>金额</th><th>类型</th><th>状态</th><th>描述</th><th>时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in dbTransactions" :key="t.id">
                <td>{{ t.id }}</td>
                <td>{{ t.user_id }}</td>
                <td :class="['amount', t.amount >= 0 ? 'pos' : 'neg']">{{ t.amount >= 0 ? '+' : '' }}¥{{ t.amount.toFixed(2) }}</td>
                <td class="type">{{ t.txn_type }}</td>
                <td><span :class="['badge', t.status === 'completed' ? 'badge-ok' : 'badge-pending']">{{ t.status }}</span></td>
                <td class="desc">{{ t.description || '—' }}</td>
                <td class="time">{{ formatTime(t.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="dbTransactions.length === 0" class="db-empty">暂无交易记录</p>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const isAdmin = ref(false)
const loadingDb = ref(false)
const message = ref('')
const messageOk = ref(true)

const dbUsers = ref([])
const dbWallets = ref([])
const dbCatalog = ref([])
const dbTransactions = ref([])

function flash(msg, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 5000)
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

async function loadDatabase() {
  loadingDb.value = true
  try {
    const [usersRes, walletsRes, catalogRes, txnsRes] = await Promise.all([
      api.adminListUsers(),
      api.adminListWallets(),
      api.adminListCatalog(),
      api.adminListTransactions(),
    ])
    dbUsers.value = usersRes.users || []
    dbWallets.value = walletsRes.items || []
    dbCatalog.value = catalogRes.items || []
    dbTransactions.value = txnsRes.items || []
  } catch (e) {
    flash('加载数据库失败: ' + e.message, false)
  } finally {
    loadingDb.value = false
  }
}

onMounted(async () => {
  try {
    const me = await api.me()
    isAdmin.value = me.is_admin === true
    if (!isAdmin.value) return
    await loadDatabase()
  } catch {
    router.push('/login')
  }
})
</script>

<style scoped>
.admin-db-view {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-title {
  font-size: 1.75rem;
  margin-bottom: 1.5rem;
  color: #ffffff;
}

.access-denied {
  text-align: center;
  padding: 3rem;
  background: #111111;
  border-radius: 8px;
  border: 0.5px solid rgba(255,255,255,0.1);
}

.nav-back {
  margin-bottom: 1.5rem;
}

.btn-back {
  padding: 0.65rem 1.25rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255,255,255,0.7);
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-back:hover {
  background: rgba(255,255,255,0.06);
  color: #ffffff;
}

.db-refresh {
  margin-bottom: 1.5rem;
}

.btn-refresh {
  padding: 0.65rem 1.25rem;
  border: none;
  border-radius: 6px;
  background: #ffffff;
  color: #0a0a0a;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-refresh:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.message {
  padding: 0.75rem;
  border-radius: 6px;
  margin-bottom: 1rem;
}

.message-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.message-err {
  background: rgba(255,80,80,0.1);
  color: #ff6b6b;
}

.db-section {
  margin-bottom: 32px;
}

.db-title {
  font-size: 16px;
  color: #ffffff;
  margin-bottom: 8px;
}

.db-count {
  font-size: 13px;
  color: rgba(255,255,255,0.4);
  margin-bottom: 12px;
}

.db-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  background: #111111;
  border-radius: 8px;
  overflow: hidden;
  border: 0.5px solid rgba(255,255,255,0.1);
}

.db-table th {
  text-align: left;
  padding: 10px 12px;
  background: rgba(255,255,255,0.03);
  color: rgba(255,255,255,0.5);
  font-weight: 600;
  font-size: 12px;
  border-bottom: 0.5px solid rgba(255,255,255,0.1);
}

.db-table td {
  padding: 10px 12px;
  border-bottom: 0.5px solid rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.7);
}

.db-table tr:last-child td {
  border-bottom: none;
}

.username, .name {
  color: #ffffff;
  font-weight: 500;
}

.pkg {
  font-family: monospace;
  font-size: 12px;
  color: rgba(255,255,255,0.4);
}

.amount.pos { color: #4ade80; font-weight: 600; }
.amount.neg { color: #ff6b6b; font-weight: 600; }
.price.free { color: #4ade80; }
.price.paid { color: #ff6b6b; }
.time { font-size: 12px; color: rgba(255,255,255,0.4); }
.desc { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.db-empty {
  text-align: center;
  padding: 24px;
  color: rgba(255,255,255,0.3);
  font-size: 14px;
}

.loading {
  text-align: center;
  padding: 2rem;
  color: rgba(255,255,255,0.4);
}

@media (max-width: 768px) {
  .db-table {
    display: block;
    overflow-x: auto;
  }
}
</style>
