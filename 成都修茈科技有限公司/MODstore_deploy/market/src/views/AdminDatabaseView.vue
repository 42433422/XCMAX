<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：数据加载 / Mod 分配 composables 与共享类型、样式在 ./admin-database/。
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useAdminDbData } from './admin-database/useAdminDbData'
import { useModEditor } from './admin-database/useModEditor'
import type { AdminUserRow, RefundAdminRow, UserFilterMode } from './admin-database/adminDatabaseHelpers'
import { errMsg, formatTime } from './admin-database/adminDatabaseHelpers'

const router = useRouter()
const isAdmin = ref(false)

const {
  loadingDb, message, messageOk,
  dbUsers, dbWallets, dbCatalog, dbTransactions, pendingRefunds,
  flash, loadDatabase,
} = useAdminDbData()

const {
  assignableMods, modEditorOpen, modEditorUser, modEditorSelected, modEditorLoading, modEditorSaving,
  modDisplayName, ensureAssignableModsLoaded, openModEditor, closeModEditor, saveModEditor,
} = useModEditor({ flash, loadDatabase })

const userFilter = ref<UserFilterMode>('all')

const enterpriseUserCount = computed(() => dbUsers.value.filter((u) => u.is_enterprise).length)

const filteredUsers = computed(() => {
  if (userFilter.value === 'enterprise') {
    return dbUsers.value.filter((u) => u.is_enterprise)
  }
  if (userFilter.value === 'non-enterprise') {
    return dbUsers.value.filter((u) => !u.is_enterprise)
  }
  return dbUsers.value
})

function setUserFilter(mode: UserFilterMode) {
  userFilter.value = mode
}

async function toggleEnterprise(row: AdminUserRow, enable: boolean) {
  const verb = enable ? '设为企业级' : '取消企业级'
  if (!window.confirm(`确认将用户「${row.username || row.id}」${verb}？`)) return
  try {
    await api.adminSetUserEnterprise(Number(row.id), enable)
    flash(`用户 #${row.id} 已${verb}`)
    await loadDatabase()
  } catch (e) {
    flash(`${verb}失败: ${errMsg(e)}`, false)
  }
}

async function reviewRefund(row: RefundAdminRow, action: 'approve' | 'reject') {
  const verb = action === 'approve' ? '通过' : '拒绝'
  const note = window.prompt(`确认${verb}退款申请 #${row.id}？可填写管理员备注：`, '') ?? null
  if (note === null) return
  try {
    await api.refundsAdminReview(Number(row.id), action, note)
    flash(`退款申请 #${row.id} 已${verb}`)
    await loadDatabase()
  } catch (e) {
    flash(`审核失败: ${errMsg(e)}`, false)
  }
}

onMounted(async () => {
  try {
    const me = await api.me()
    isAdmin.value = me.is_admin === true
    if (!isAdmin.value) return
    void ensureAssignableModsLoaded().catch(() => {})
    await loadDatabase()
  } catch {
    router.push('/login')
  }
})
</script>

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
        <!-- Refunds -->
        <div class="db-section">
          <h3 class="db-title">退款审核</h3>
          <p class="db-count">待审核 {{ pendingRefunds.length }} 条</p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>用户ID</th><th>订单号</th><th>金额</th><th>原因</th><th>时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in pendingRefunds" :key="r.id">
                <td>{{ r.id }}</td>
                <td>{{ r.user_id }}</td>
                <td class="pkg">{{ r.order_no }}</td>
                <td class="amount pos">¥{{ Number(r.amount || 0).toFixed(2) }}</td>
                <td class="desc">{{ r.reason || '—' }}</td>
                <td class="time">{{ formatTime(r.created_at) }}</td>
                <td class="action-cell">
                  <button class="btn-mini btn-approve" @click="reviewRefund(r, 'approve')">通过</button>
                  <button class="btn-mini btn-reject" @click="reviewRefund(r, 'reject')">拒绝</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="pendingRefunds.length === 0" class="db-empty">暂无待审核退款</p>
        </div>

        <!-- Users -->
        <div class="db-section">
          <h3 class="db-title">📋 用户表</h3>
          <div class="user-filter-bar">
            <span class="user-filter-label">筛选</span>
            <button
              type="button"
              :class="['filter-chip', userFilter === 'all' ? 'filter-chip--active' : '']"
              @click="setUserFilter('all')"
            >全部</button>
            <button
              type="button"
              :class="['filter-chip', userFilter === 'enterprise' ? 'filter-chip--active' : '']"
              @click="setUserFilter('enterprise')"
            >企业级</button>
            <button
              type="button"
              :class="['filter-chip', userFilter === 'non-enterprise' ? 'filter-chip--active' : '']"
              @click="setUserFilter('non-enterprise')"
            >非企业级</button>
          </div>
          <p class="db-count">
            共 {{ dbUsers.length }} 个用户（企业级 {{ enterpriseUserCount }} 个）
            <template v-if="userFilter !== 'all'"> · 当前筛选 {{ filteredUsers.length }} 个</template>
          </p>
          <table class="db-table">
            <thead>
              <tr><th>ID</th><th>用户名</th><th>邮箱</th><th>管理员</th><th>企业级</th><th>企业 Mod</th><th>注册时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="u in filteredUsers" :key="u.id">
                <td>{{ u.id }}</td>
                <td class="username">{{ u.username }}</td>
                <td>{{ u.email || '—' }}</td>
                <td><span :class="['badge', u.is_admin ? 'badge-admin' : 'badge-user']">{{ u.is_admin ? '是' : '否' }}</span></td>
                <td><span :class="['badge', u.is_enterprise ? 'badge-enterprise' : 'badge-user']">{{ u.is_enterprise ? '是' : '否' }}</span></td>
                <td class="mod-ids-cell">
                  <template v-if="u.is_enterprise">
                    <span v-for="mid in (u.mod_ids || [])" :key="mid" class="mod-chip">{{ modDisplayName(mid) }}</span>
                    <span v-if="!(u.mod_ids || []).length" class="mod-chip mod-chip--empty">未分配</span>
                  </template>
                  <span v-else class="mod-chip mod-chip--muted">—</span>
                </td>
                <td class="time">{{ formatTime(u.created_at) }}</td>
                <td class="action-cell">
                  <button
                    v-if="!u.is_enterprise"
                    type="button"
                    class="btn-mini btn-enterprise-set"
                    @click="toggleEnterprise(u, true)"
                  >设为企业级</button>
                  <button
                    v-else
                    type="button"
                    class="btn-mini btn-enterprise-unset"
                    @click="toggleEnterprise(u, false)"
                  >取消企业级</button>
                  <button
                    type="button"
                    class="btn-mini btn-mod-manage"
                    :disabled="!u.is_enterprise"
                    :title="u.is_enterprise ? '分配客户 Mod' : '请先设为企业级用户'"
                    @click="openModEditor(u)"
                  >管理 Mod</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="filteredUsers.length === 0" class="db-empty">暂无用户</p>
        </div>

        <!-- 企业 Mod 分配弹窗 -->
        <div v-if="modEditorOpen" class="mod-editor-overlay" @click.self="closeModEditor">
          <div class="mod-editor-panel" role="dialog" aria-labelledby="mod-editor-title">
            <h3 id="mod-editor-title" class="mod-editor-title">
              管理企业 Mod — {{ modEditorUser?.username || modEditorUser?.id }}
            </h3>
            <p class="mod-editor-hint">仅企业级用户可在桌面版加载下列客户 Mod；宿主 Mod 由安装包自带，无需分配。</p>
            <div v-if="modEditorLoading" class="mod-editor-loading">加载中…</div>
            <div v-else class="mod-editor-options">
              <label
                v-for="m in assignableMods"
                :key="m.id"
                class="mod-editor-option"
              >
                <input
                  v-model="modEditorSelected"
                  type="checkbox"
                  :value="m.id"
                />
                <span class="mod-editor-option-label">{{ m.name }}</span>
                <span class="mod-editor-option-id">{{ m.id }}</span>
              </label>
              <p v-if="assignableMods.length === 0" class="db-empty">暂无可分配 Mod</p>
            </div>
            <div class="mod-editor-actions">
              <button type="button" class="btn btn-back" :disabled="modEditorSaving" @click="closeModEditor">取消</button>
              <button type="button" class="btn btn-refresh" :disabled="modEditorSaving" @click="saveModEditor">
                {{ modEditorSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>
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

<style scoped src="./admin-database/adminDatabase.css"></style>
