<template>
  <div class="db-viewer">
    <h1 class="page-title">数据库查看</h1>

    <!-- Users 表 -->
    <section class="db-section">
      <h2 class="db-title">📋 用户表 (users)</h2>
      <p class="db-count">共 {{ users.length }} 个用户</p>
      <table class="db-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>邮箱</th>
            <th>管理员</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td>
            <td class="username">{{ user.username }}</td>
            <td>{{ user.email || '—' }}</td>
            <td>
              <span :class="['badge', user.is_admin ? 'badge-yes' : 'badge-no']">
                {{ user.is_admin ? '是' : '否' }}
              </span>
            </td>
            <td class="time">{{ formatTime(user.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="users.length === 0" class="db-empty">暂无用户</p>
    </section>

    <!-- Wallets 表 -->
    <section class="db-section">
      <h2 class="db-title">💰 钱包表 (wallets)</h2>
      <p class="db-count">共 {{ wallets.length }} 个钱包</p>
      <table class="db-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户 ID</th>
            <th>余额</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in wallets" :key="w.id">
            <td>{{ w.id }}</td>
            <td>{{ w.user_id }}</td>
            <td :class="['balance', w.balance >= 0 ? 'pos' : 'neg']">¥{{ w.balance.toFixed(2) }}</td>
            <td class="time">{{ formatTime(w.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="wallets.length === 0" class="db-empty">暂无钱包</p>
    </section>

    <!-- Catalog 表 -->
    <section class="db-section">
      <h2 class="db-title">📦 商品目录表 (catalog_items)</h2>
      <p class="db-count">共 {{ catalog.length }} 个商品</p>
      <table class="db-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>包 ID</th>
            <th>版本</th>
            <th>价格</th>
            <th>下载量</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in catalog" :key="item.id">
            <td>{{ item.id }}</td>
            <td class="name">{{ item.name }}</td>
            <td class="pkg">{{ item.pkg_id }}</td>
            <td>{{ item.version }}</td>
            <td :class="['price', item.price <= 0 ? 'free' : 'paid']">
              {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
            </td>
            <td>{{ item.downloads || 0 }}</td>
            <td class="time">{{ formatTime(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="catalog.length === 0" class="db-empty">暂无商品</p>
    </section>

    <!-- Transactions 表 -->
    <section class="db-section">
      <h2 class="db-title">📝 交易记录表 (transactions)</h2>
      <p class="db-count">共 {{ transactions.length }} 条记录</p>
      <table class="db-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户 ID</th>
            <th>金额</th>
            <th>类型</th>
            <th>状态</th>
            <th>描述</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.id">
            <td>{{ txn.id }}</td>
            <td>{{ txn.user_id }}</td>
            <td :class="['amount', txn.amount >= 0 ? 'pos' : 'neg']">
              {{ txn.amount >= 0 ? '+' : '' }}¥{{ txn.amount.toFixed(2) }}
            </td>
            <td class="type">{{ txn.txn_type }}</td>
            <td>
              <span :class="['badge', txn.status === 'completed' ? 'badge-ok' : 'badge-pending']">
                {{ txn.status }}
              </span>
            </td>
            <td class="desc">{{ txn.description || '—' }}</td>
            <td class="time">{{ formatTime(txn.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="transactions.length === 0" class="db-empty">暂无交易记录</p>
    </section>

    <div v-if="loading" class="loading">加载数据库...</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'

const users = ref([])
const wallets = ref([])
const catalog = ref([])
const transactions = ref([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const [usersRes, walletsRes, catalogRes, txnsRes] = await Promise.all([
      api.adminListUsers(100, 0),
      api.adminListWallets(100, 0),
      api.adminListCatalog(100, 0),
      api.adminListTransactions(100, 0),
    ])
    users.value = usersRes.items || []
    wallets.value = walletsRes.items || []
    catalog.value = catalogRes.items || []
    transactions.value = txnsRes.items || []
  } catch (e) {
    console.error('加载数据库失败:', e)
  } finally {
    loading.value = false
  }
})

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
</script>

<style scoped>
.db-viewer {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px;
}

.page-title {
  font-size: 24px;
  color: #ffffff;
  margin-bottom: 32px;
}

.db-section {
  margin-bottom: 48px;
}

.db-title {
  font-size: 18px;
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

.username {
  color: #ffffff;
  font-weight: 500;
}

.name {
  color: #ffffff;
  font-weight: 500;
}

.pkg {
  font-family: monospace;
  font-size: 12px;
  color: rgba(255,255,255,0.4);
}

.balance.pos, .amount.pos { color: #4ade80; font-weight: 600; }
.balance.neg, .amount.neg { color: #ff6b6b; font-weight: 600; }
.price.free { color: #4ade80; }
.price.paid { color: #ff6b6b; }
.time { font-size: 12px; color: rgba(255,255,255,0.4); }
.desc { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.badge-yes { background: rgba(96,165,250,0.15); color: #60a5fa; }
.badge-no { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.4); }
.badge-ok { background: rgba(74,222,128,0.15); color: #4ade80; }
.badge-pending { background: rgba(255,165,0,0.15); color: #ffa500; }

.db-empty {
  text-align: center;
  padding: 24px;
  color: rgba(255,255,255,0.3);
  font-size: 14px;
}

.loading {
  text-align: center;
  padding: 48px;
  color: rgba(255,255,255,0.4);
}

@media (max-width: 768px) {
  .db-table {
    display: block;
    overflow-x: auto;
  }
}
</style>
