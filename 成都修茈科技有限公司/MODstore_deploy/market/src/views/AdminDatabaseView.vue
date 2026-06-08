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

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const isAdmin = ref(false)
const loadingDb = ref(false)
const message = ref('')
const messageOk = ref(true)

interface RefundAdminRow {
  id: number | string
  user_id?: number | string
  order_no?: string
  amount?: number
  reason?: string
  created_at?: string
}
interface AssignableModRow {
  id: string
  name: string
}

interface AdminUserRow {
  id: number | string
  username?: string
  email?: string
  is_admin?: boolean
  is_enterprise?: boolean
  mod_ids?: string[]
  created_at?: string
}

type UserFilterMode = 'all' | 'enterprise' | 'non-enterprise'
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
interface WalletRow {
  id: number | string
  user_id?: number | string
  balance: number
  updated_at?: string
}
interface CatalogRow {
  id: number | string
  name?: string
  pkg_id?: string
  version?: string
  price: number
  downloads?: number
  created_at?: string
}
interface TransactionRow {
  id: number | string
  user_id?: number | string
  amount: number
  txn_type?: string
  status?: string
  description?: string
  created_at?: string
}

const dbUsers = ref<AdminUserRow[]>([])
const dbWallets = ref<WalletRow[]>([])
const dbCatalog = ref<CatalogRow[]>([])
const dbTransactions = ref<TransactionRow[]>([])
const pendingRefunds = ref<RefundAdminRow[]>([])
const assignableMods = ref<AssignableModRow[]>([])
const modEditorOpen = ref(false)
const modEditorUser = ref<AdminUserRow | null>(null)
const modEditorSelected = ref<string[]>([])
const modEditorLoading = ref(false)
const modEditorSaving = ref(false)

const assignableModNameById = computed(() => {
  const map: Record<string, string> = {}
  for (const m of assignableMods.value) {
    map[m.id] = m.name
  }
  return map
})

function modDisplayName(modId: string): string {
  return assignableModNameById.value[modId] || modId
}

function flash(msg: string, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 5000)
}

function formatTime(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

async function ensureAssignableModsLoaded() {
  if (assignableMods.value.length > 0) return
  const res = await api.adminEnterpriseAssignableMods()
  assignableMods.value = (res.mods || []) as AssignableModRow[]
}

async function openModEditor(row: AdminUserRow) {
  if (!row.is_enterprise) {
    flash('请先将该用户设为企业级', false)
    return
  }
  modEditorUser.value = row
  modEditorOpen.value = true
  modEditorLoading.value = true
  modEditorSelected.value = []
  try {
    await ensureAssignableModsLoaded()
    const detail = await api.adminListUserMods(Number(row.id))
    modEditorSelected.value = Array.isArray(detail.mod_ids) ? [...detail.mod_ids] : [...(row.mod_ids || [])]
  } catch (e) {
    flash(`加载 Mod 列表失败: ${errMsg(e)}`, false)
    modEditorOpen.value = false
  } finally {
    modEditorLoading.value = false
  }
}

function closeModEditor() {
  if (modEditorSaving.value) return
  modEditorOpen.value = false
  modEditorUser.value = null
  modEditorSelected.value = []
}

async function saveModEditor() {
  const row = modEditorUser.value
  if (!row) return
  const uid = Number(row.id)
  const prev = new Set((row.mod_ids || []).map(String))
  const next = new Set(modEditorSelected.value.map(String))
  const toBind = [...next].filter((id) => !prev.has(id))
  const toUnbind = [...prev].filter((id) => !next.has(id))
  if (!toBind.length && !toUnbind.length) {
    closeModEditor()
    return
  }
  modEditorSaving.value = true
  try {
    for (const mid of toBind) {
      await api.adminBindUserMod(uid, mid)
    }
    for (const mid of toUnbind) {
      await api.adminUnbindUserMod(uid, mid)
    }
    flash(`用户 #${uid} 企业 Mod 已更新`)
    closeModEditor()
    await loadDatabase()
  } catch (e) {
    flash(`保存失败: ${errMsg(e)}`, false)
  } finally {
    modEditorSaving.value = false
  }
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

async function loadDatabase() {
  loadingDb.value = true
  try {
    const settled = await Promise.allSettled([
      api.refundsAdminPending(),
      api.adminListUsers(200, 0),
      api.adminListWallets(),
      api.adminListCatalog(),
      api.adminListTransactions(),
    ])
    const labels = ['退款待审', '用户', '钱包', '商品目录', '交易流水']
    const errs: string[] = []

    const [refundsR, usersR, walletsR, catalogR, txnsR] = settled

    if (refundsR.status === 'fulfilled') {
      pendingRefunds.value = (refundsR.value.refunds || []) as RefundAdminRow[]
    } else {
      pendingRefunds.value = []
      errs.push(`${labels[0]}: ${errMsg(refundsR.reason)}`)
    }
    if (usersR.status === 'fulfilled') {
      dbUsers.value = (usersR.value.users || []) as AdminUserRow[]
    } else {
      dbUsers.value = []
      errs.push(`${labels[1]}: ${errMsg(usersR.reason)}`)
    }
    if (walletsR.status === 'fulfilled') {
      dbWallets.value = (walletsR.value.items || []) as WalletRow[]
    } else {
      dbWallets.value = []
      errs.push(`${labels[2]}: ${errMsg(walletsR.reason)}`)
    }
    if (catalogR.status === 'fulfilled') {
      dbCatalog.value = (catalogR.value.items || []) as CatalogRow[]
    } else {
      dbCatalog.value = []
      errs.push(`${labels[3]}: ${errMsg(catalogR.reason)}`)
    }
    if (txnsR.status === 'fulfilled') {
      dbTransactions.value = (txnsR.value.items || []) as TransactionRow[]
    } else {
      dbTransactions.value = []
      errs.push(`${labels[4]}: ${errMsg(txnsR.reason)}`)
    }

    if (errs.length) {
      flash('部分数据加载失败（其余已显示）: ' + errs.join('；'), false)
    }
  } finally {
    loadingDb.value = false
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

<style scoped>
.admin-db-view {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: var(--page-pad-y) var(--layout-pad-x);
  box-sizing: border-box;
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

.action-cell {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.btn-mini {
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 6px;
  padding: 0.35rem 0.55rem;
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
  cursor: pointer;
}

.btn-approve {
  border-color: rgba(74, 222, 128, 0.35);
  color: #86efac;
}

.btn-reject {
  border-color: rgba(248, 113, 113, 0.35);
  color: #fca5a5;
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

.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 12px;
}

.badge-admin {
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
}

.badge-enterprise {
  background: rgba(251, 191, 36, 0.15);
  color: #fcd34d;
}

.badge-user {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.55);
}

.user-filter-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}

.user-filter-label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
}

.filter-chip {
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  padding: 0.35rem 0.85rem;
  background: transparent;
  color: rgba(255, 255, 255, 0.75);
  cursor: pointer;
  font-size: 0.85rem;
}

.filter-chip--active {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.35);
  color: #fcd34d;
}

.btn-enterprise-set {
  border-color: rgba(251, 191, 36, 0.35);
  color: #fcd34d;
}

.btn-enterprise-unset {
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.65);
}

.btn-mod-manage {
  border-color: rgba(96, 165, 250, 0.35);
  color: #93c5fd;
  margin-left: 0.35rem;
}

.btn-mod-manage:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.mod-ids-cell {
  max-width: 220px;
}

.mod-chip {
  display: inline-block;
  margin: 0.15rem 0.25rem 0.15rem 0;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.75rem;
  background: rgba(96, 165, 250, 0.12);
  color: #93c5fd;
  border: 1px solid rgba(96, 165, 250, 0.25);
}

.mod-chip--empty {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.45);
  border-color: rgba(255, 255, 255, 0.1);
}

.mod-chip--muted {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.35);
}

.mod-editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 12000;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.mod-editor-panel {
  width: min(480px, 100%);
  background: #1a1d24;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.45);
}

.mod-editor-title {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
  color: #f3f4f6;
}

.mod-editor-hint {
  margin: 0 0 1rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.45;
}

.mod-editor-loading {
  padding: 1rem 0;
  color: rgba(255, 255, 255, 0.6);
}

.mod-editor-options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.mod-editor-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.65rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
}

.mod-editor-option:hover {
  background: rgba(255, 255, 255, 0.04);
}

.mod-editor-option-label {
  flex: 1;
  color: #e5e7eb;
  font-size: 0.95rem;
}

.mod-editor-option-id {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  font-family: ui-monospace, monospace;
}

.mod-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

@media (max-width: 768px) {
  .db-table {
    display: block;
    overflow-x: auto;
  }
}
html[data-workbench-theme='light'] .page-title{color:#1a1a1a}
html[data-workbench-theme='light'] .access-denied{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .btn-back{color:#64748b;border-color:#d1d5db}
html[data-workbench-theme='light'] .btn-back:hover{background:rgba(0,0,0,0.04);color:#1a1a1a}
html[data-workbench-theme='light'] .btn-refresh{background:#1a1a1a;color:#fff}
html[data-workbench-theme='light'] .btn-mini{background:rgba(0,0,0,0.04);color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .btn-approve{color:#059669;border-color:rgba(5,150,105,0.3)}
html[data-workbench-theme='light'] .btn-reject{color:#dc2626;border-color:rgba(220,38,38,0.3)}
html[data-workbench-theme='light'] .message-ok{background:rgba(5,150,105,0.08);color:#059669}
html[data-workbench-theme='light'] .message-err{background:rgba(220,38,38,0.08);color:#dc2626}
html[data-workbench-theme='light'] .db-title{color:#1a1a1a}
html[data-workbench-theme='light'] .db-count{color:#94a3b8}
html[data-workbench-theme='light'] .db-table{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .db-table th{background:#f8f9fa;color:#64748b;border-color:#e2e8f0}
html[data-workbench-theme='light'] .db-table td{color:#334155;border-color:rgba(0,0,0,0.06)}
html[data-workbench-theme='light'] .username,html[data-workbench-theme='light'] .name{color:#1a1a1a}
html[data-workbench-theme='light'] .pkg{color:#94a3b8}
html[data-workbench-theme='light'] .amount.pos{color:#059669}
html[data-workbench-theme='light'] .amount.neg{color:#dc2626}
html[data-workbench-theme='light'] .time{color:#94a3b8}
html[data-workbench-theme='light'] .db-empty{color:#94a3b8}
html[data-workbench-theme='light'] .loading{color:#94a3b8}
</style>
