<script setup lang="ts">
/**
 * 管理员：AI 员工账号池（QQ / 微信 / 邮箱 …）
 *
 * 这个页面把"哪个 AI 员工 用 哪个外部平台账号 接入入站消息"的关系做成 CRUD：
 * - 列表 + 状态过滤
 * - 新建 / 改派员工 / 改状态 / 改备注 / 删除
 * - 轮换密钥（QQ：app_id + app_secret + bot_token）
 * - 显示该员工在 QQ 桥接中的"一等公民"webhook URL，方便复制粘贴到 QQ 后台
 *
 * 设计原则：
 * - 不在前端缓存任何明文密钥；所有 secret 字段在表单提交后立即清空。
 * - webhook URL 由后端 channel.paths 直接给，前端只负责拼接 host。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

type ChannelPath = { label: string; path: string }
type Channel = { platform: string; paths: ChannelPath[] }
type Account = {
  id: number
  platform: string
  external_id: string
  employee_id: string
  display_name: string
  status: string
  sandbox: boolean
  notes: string
  has_secret: boolean
  secrets_path: string
  created_at?: string
  updated_at?: string
  channel: Channel
}
type ListResp = { items: Account[]; total: number; limit: number; offset: number }
type FirstClassEmp = {
  employee_id: string
  app_id: string
  webhook_key: string
  webhook_path: string
  by_employee_path: string
  app_secret_env: string
  app_secret_present: boolean
  uses_executor: boolean
}
type QqStatus = {
  configured: boolean
  credential_source: string
  app_id: string | null
  butler_employee_id: string
  first_class_employees: FirstClassEmp[]
  sandbox: boolean
  api_base: string
}

const router = useRouter()
const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

const loading = ref(false)
const error = ref('')
const items = ref<Account[]>([])
const total = ref(0)
const filterPlatform = ref('')
const filterEmployee = ref('')
const filterStatus = ref('')

const qqStatus = ref<QqStatus | null>(null)

const createOpen = ref(false)
const createForm = reactive({
  platform: 'qq',
  external_id: '',
  employee_id: '',
  display_name: '',
  sandbox: false,
  notes: '',
  app_id: '',
  app_secret: '',
  bot_token: '',
})
const createBusy = ref(false)

const rotateOpenId = ref<number | null>(null)
const rotateForm = reactive({ app_id: '', app_secret: '', bot_token: '' })
const rotateBusy = ref(false)

const editOpenId = ref<number | null>(null)
const editForm = reactive({ employee_id: '', display_name: '', status: 'active', sandbox: false, notes: '' })
const editBusy = ref(false)

function host(): string {
  if (typeof window === 'undefined') return ''
  return `${window.location.protocol}//${window.location.host}`
}

const fullWebhookList = computed(() => {
  const base = host()
  return items.value.map((it) => ({
    id: it.id,
    employee_id: it.employee_id,
    paths: (it.channel?.paths || []).map((p) => ({ label: p.label, url: `${base}${p.path}` })),
  }))
})

async function loadAll() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string | number> = { limit: 200 }
    if (filterPlatform.value) params.platform = filterPlatform.value
    if (filterEmployee.value) params.employee_id = filterEmployee.value
    if (filterStatus.value) params.status = filterStatus.value
    const resp = (await api.adminListAiAccounts(params as never)) as ListResp
    items.value = resp.items || []
    total.value = resp.total || 0
    try {
      qqStatus.value = (await api.butlerQqStatus()) as QqStatus
    } catch {
      qqStatus.value = null
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.platform = 'qq'
  createForm.external_id = ''
  createForm.employee_id = ''
  createForm.display_name = ''
  createForm.sandbox = false
  createForm.notes = ''
  createForm.app_id = ''
  createForm.app_secret = ''
  createForm.bot_token = ''
  createOpen.value = true
}

function closeCreate() {
  createOpen.value = false
  createForm.app_secret = ''
  createForm.bot_token = ''
}

async function submitCreate() {
  if (createBusy.value) return
  if (!createForm.platform || !createForm.external_id || !createForm.employee_id) {
    error.value = 'platform / external_id / employee_id 都不能为空'
    return
  }
  if (createForm.platform === 'qq' && (!createForm.app_id || !createForm.app_secret || !createForm.bot_token)) {
    error.value = 'QQ 平台需要 app_id / app_secret / bot_token 三个字段'
    return
  }
  createBusy.value = true
  error.value = ''
  try {
    const secret =
      createForm.platform === 'qq'
        ? { app_id: createForm.app_id, app_secret: createForm.app_secret, bot_token: createForm.bot_token }
        : {}
    await api.adminCreateAiAccount({
      platform: createForm.platform,
      external_id: createForm.external_id,
      employee_id: createForm.employee_id,
      display_name: createForm.display_name || undefined,
      sandbox: createForm.sandbox,
      notes: createForm.notes || undefined,
      secret,
    })
    closeCreate()
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    createBusy.value = false
  }
}

function openEdit(a: Account) {
  editOpenId.value = a.id
  editForm.employee_id = a.employee_id
  editForm.display_name = a.display_name || ''
  editForm.status = a.status
  editForm.sandbox = !!a.sandbox
  editForm.notes = a.notes || ''
}
function closeEdit() {
  editOpenId.value = null
}
async function submitEdit() {
  if (editOpenId.value == null || editBusy.value) return
  editBusy.value = true
  error.value = ''
  try {
    await api.adminUpdateAiAccount(editOpenId.value, {
      employee_id: editForm.employee_id,
      display_name: editForm.display_name,
      status: editForm.status,
      sandbox: editForm.sandbox,
      notes: editForm.notes,
    })
    closeEdit()
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    editBusy.value = false
  }
}

function openRotate(a: Account) {
  rotateOpenId.value = a.id
  rotateForm.app_id = ''
  rotateForm.app_secret = ''
  rotateForm.bot_token = ''
}
function closeRotate() {
  rotateOpenId.value = null
  rotateForm.app_secret = ''
  rotateForm.bot_token = ''
}
async function submitRotate() {
  if (rotateOpenId.value == null || rotateBusy.value) return
  if (!rotateForm.app_id || !rotateForm.app_secret || !rotateForm.bot_token) {
    error.value = 'QQ 轮换需要 app_id / app_secret / bot_token 三个字段（粘贴 QQ 后台最新值）'
    return
  }
  rotateBusy.value = true
  error.value = ''
  try {
    await api.adminRotateAiAccountSecret(rotateOpenId.value, {
      app_id: rotateForm.app_id,
      app_secret: rotateForm.app_secret,
      bot_token: rotateForm.bot_token,
    })
    closeRotate()
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    rotateBusy.value = false
  }
}

async function removeAccount(a: Account) {
  if (!window.confirm(`确认删除账号 #${a.id}（${a.platform}/${a.external_id}）？密钥文件也会一并销毁。`)) return
  error.value = ''
  try {
    await api.adminDeleteAiAccount(a.id)
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function copyText(text: string) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const el = document.createElement('textarea')
      el.value = text
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
  } catch {
    /* clipboard 权限问题就静默失败，让用户手动选 */
  }
}

onMounted(() => void loadAll())
</script>

<template>
  <div v-if="!isAdmin" class="aa-denied">
    <p>需要管理员权限</p>
    <button type="button" class="btn" @click="router.push('/')">返回首页</button>
  </div>
  <div v-else class="aa-page">
    <header class="aa-head">
      <div>
        <h1>AI 员工账号池</h1>
        <p class="aa-lead">管理 AI 员工的外部平台账号与密钥。</p>
      </div>
      <div class="aa-actions">
        <button type="button" class="btn ghost" :disabled="loading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <button type="button" class="btn primary" @click="openCreate">+ 新建账号</button>
      </div>
    </header>

    <p v-if="error" class="aa-err">{{ error }}</p>

    <!-- ─── QQ 桥接状态 ───────────────────────────────── -->
    <section v-if="qqStatus" class="aa-card">
      <h2>QQ 桥接</h2>
      <p>
        <span :class="qqStatus.configured ? 'ok' : 'bad'">{{ qqStatus.configured ? '已连接' : '未配置' }}</span>
        <span class="muted"> · {{ qqStatus.credential_source || '-' }} · {{ qqStatus.sandbox ? '沙箱' : '正式' }}</span>
      </p>
      <ul v-if="qqStatus.first_class_employees?.length" class="aa-fc-list">
        <li v-for="emp in qqStatus.first_class_employees" :key="emp.employee_id" class="aa-fc-item">
          <p>
            <strong>{{ emp.employee_id }}</strong>
            <span class="muted">AppID {{ emp.app_id }}</span>
            <span :class="emp.app_secret_present ? 'ok' : 'bad'">{{ emp.app_secret_present ? '✓' : '✕ 密钥缺失' }}</span>
          </p>
          <ul class="aa-url-list">
            <li>
              <code class="aa-code">{{ host() }}{{ emp.by_employee_path }}</code>
              <button type="button" class="btn link" @click="copyText(host() + emp.by_employee_path)">复制</button>
            </li>
          </ul>
        </li>
      </ul>
    </section>

    <!-- ─── 过滤 + 列表 ───────────────────────────────── -->
    <section class="aa-card">
      <div class="aa-filters">
        <label class="aa-field">
          <span>平台</span>
          <select v-model="filterPlatform" class="aa-input" @change="loadAll">
            <option value="">全部</option>
            <option value="qq">qq</option>
            <option value="wechat">wechat</option>
            <option value="email">email</option>
            <option value="slack">slack</option>
            <option value="feishu">feishu</option>
            <option value="discord">discord</option>
          </select>
        </label>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="filterEmployee" class="aa-input" placeholder="如 task-router-officer" @change="loadAll" />
        </label>
        <label class="aa-field">
          <span>状态</span>
          <select v-model="filterStatus" class="aa-input" @change="loadAll">
            <option value="">全部</option>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
        <p class="muted aa-total">共 {{ total }} 条</p>
      </div>

      <div v-if="loading && !items.length" class="muted">加载中…</div>
      <div v-else-if="!items.length" class="muted">暂无账号</div>
      <table v-else class="aa-table">
        <thead>
          <tr>
            <th>#</th>
            <th>平台</th>
            <th>外部 ID</th>
            <th>员工</th>
            <th>状态</th>
            <th>沙箱</th>
            <th>密钥</th>
            <th>入站 URL</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in items" :key="a.id">
            <td>{{ a.id }}</td>
            <td>{{ a.platform }}</td>
            <td><code class="aa-code">{{ a.external_id }}</code></td>
            <td>
              <code class="aa-code">{{ a.employee_id }}</code>
              <p v-if="a.display_name" class="muted">{{ a.display_name }}</p>
            </td>
            <td :class="a.status === 'active' ? 'ok' : 'bad'">{{ a.status }}</td>
            <td>{{ a.sandbox ? '是' : '否' }}</td>
            <td :class="a.has_secret ? 'ok' : 'bad'">{{ a.has_secret ? '已落地' : '缺失' }}</td>
            <td>
              <ul v-if="(a.channel?.paths?.length || 0) > 0" class="aa-url-list">
                <li v-for="p in a.channel.paths" :key="p.path">
                  <span class="muted">{{ p.label }}：</span>
                  <code class="aa-code">{{ host() }}{{ p.path }}</code>
                  <button type="button" class="btn link" @click="copyText(host() + p.path)">复制</button>
                </li>
              </ul>
              <span v-else class="muted">该平台暂未导出 URL</span>
            </td>
            <td class="aa-row-actions">
              <button type="button" class="btn link" @click="openEdit(a)">编辑</button>
              <button type="button" class="btn link" @click="openRotate(a)">轮换密钥</button>
              <button type="button" class="btn link bad" @click="removeAccount(a)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ─── 新建对话框 ───────────────────────────────── -->
    <div v-if="createOpen" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>新建 AI 员工账号</h2>
        <label class="aa-field">
          <span>平台</span>
          <select v-model="createForm.platform" class="aa-input">
            <option value="qq">qq</option>
            <option value="wechat" disabled>wechat（暂未实现）</option>
            <option value="email" disabled>email（暂未实现）</option>
          </select>
        </label>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="createForm.employee_id" class="aa-input" placeholder="如 task-router-officer" />
        </label>
        <label class="aa-field">
          <span>external_id（QQ 号 / AppID）</span>
          <input v-model="createForm.external_id" class="aa-input" placeholder="如 1903978019" />
        </label>
        <label class="aa-field">
          <span>显示名称（可选）</span>
          <input v-model="createForm.display_name" class="aa-input" placeholder="如 任务路由员主号" />
        </label>
        <label class="aa-field">
          <span>备注（可选）</span>
          <textarea v-model="createForm.notes" class="aa-input" rows="2" />
        </label>
        <label class="aa-check">
          <input v-model="createForm.sandbox" type="checkbox" />
          <span>使用 QQ 沙箱环境</span>
        </label>
        <template v-if="createForm.platform === 'qq'">
          <h3>QQ 凭证</h3>
          <label class="aa-field">
            <span>app_id</span>
            <input v-model="createForm.app_id" class="aa-input" />
          </label>
          <label class="aa-field">
            <span>app_secret</span>
            <input v-model="createForm.app_secret" class="aa-input" type="password" autocomplete="off" />
          </label>
          <label class="aa-field">
            <span>bot_token</span>
            <input v-model="createForm.bot_token" class="aa-input" type="password" autocomplete="off" />
          </label>
        </template>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="createBusy" @click="closeCreate">取消</button>
          <button type="button" class="btn primary" :disabled="createBusy" @click="submitCreate">
            {{ createBusy ? '提交中…' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ─── 编辑对话框 ───────────────────────────────── -->
    <div v-if="editOpenId != null" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>编辑账号 #{{ editOpenId }}</h2>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="editForm.employee_id" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>显示名称</span>
          <input v-model="editForm.display_name" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>状态</span>
          <select v-model="editForm.status" class="aa-input">
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
        <label class="aa-check">
          <input v-model="editForm.sandbox" type="checkbox" />
          <span>使用 QQ 沙箱</span>
        </label>
        <label class="aa-field">
          <span>备注</span>
          <textarea v-model="editForm.notes" class="aa-input" rows="2" />
        </label>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="editBusy" @click="closeEdit">取消</button>
          <button type="button" class="btn primary" :disabled="editBusy" @click="submitEdit">
            {{ editBusy ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ─── 轮换密钥对话框 ────────────────────────────── -->
    <div v-if="rotateOpenId != null" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>轮换密钥（账号 #{{ rotateOpenId }}）</h2>
        <p class="muted">提交后会**覆盖**密钥文件，旧密钥立刻作废。</p>
        <label class="aa-field">
          <span>app_id</span>
          <input v-model="rotateForm.app_id" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>app_secret</span>
          <input v-model="rotateForm.app_secret" class="aa-input" type="password" autocomplete="off" />
        </label>
        <label class="aa-field">
          <span>bot_token</span>
          <input v-model="rotateForm.bot_token" class="aa-input" type="password" autocomplete="off" />
        </label>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="rotateBusy" @click="closeRotate">取消</button>
          <button type="button" class="btn primary" :disabled="rotateBusy" @click="submitRotate">
            {{ rotateBusy ? '提交中…' : '提交轮换' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aa-page {
  padding: 1rem 1.25rem;
  max-width: 1280px;
  margin: 0 auto;
}
.aa-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.aa-lead {
  color: var(--color-text-muted, #666);
  margin: 0.25rem 0 0;
  max-width: 720px;
}
.aa-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.aa-err {
  color: #c44;
  margin-bottom: 0.75rem;
  white-space: pre-wrap;
}
.aa-card {
  background: var(--color-surface-raised, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--color-border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}
.aa-card h2,
.aa-card h3 {
  margin-top: 0;
}
.aa-fc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.75rem;
}
.aa-fc-item {
  border: 1px dashed var(--color-border, rgba(255, 255, 255, 0.12));
  padding: 0.75rem;
  border-radius: 6px;
}
.aa-url-list {
  list-style: none;
  margin: 0.25rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.aa-url-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}
.aa-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.aa-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 180px;
  flex: 1 0 180px;
}
.aa-field span {
  font-size: 0.85rem;
  opacity: 0.85;
}
.aa-input {
  padding: 0.4rem 0.55rem;
  border-radius: 6px;
  border: 1px solid var(--color-border, #444);
  background: var(--color-bg, #111);
  color: inherit;
  font: inherit;
}
.aa-check {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
}
.aa-total {
  margin-left: auto;
}
.aa-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.aa-table th,
.aa-table td {
  border-bottom: 1px solid var(--color-border, rgba(255, 255, 255, 0.08));
  padding: 0.5rem;
  text-align: left;
  vertical-align: top;
}
.aa-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.aa-code {
  font-size: 0.8em;
  word-break: break-all;
}
.muted {
  opacity: 0.75;
}
.ok {
  color: #6a6;
  margin-left: 0.4rem;
}
.bad {
  color: #c66;
  margin-left: 0.4rem;
}
.aa-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 4vh 1rem;
  z-index: 1000;
}
.aa-modal-body {
  background: var(--color-bg, #1a1a1a);
  border: 1px solid var(--color-border, #444);
  border-radius: 8px;
  padding: 1.25rem 1.5rem;
  width: min(560px, 100%);
  max-height: 92vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.aa-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.aa-denied {
  padding: 2rem;
  text-align: center;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  border: 1px solid var(--color-border, #555);
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.btn.primary {
  background: var(--color-accent, #3b82f6);
  border-color: transparent;
  color: #fff;
}
.btn.ghost {
  background: transparent;
}
.btn.link {
  border: none;
  color: var(--color-accent, #3b82f6);
  background: transparent;
  padding: 0.15rem 0.35rem;
}
.btn.link.bad {
  color: #c66;
}
.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
html[data-workbench-theme='light'] .aa-card{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .aa-fc-item{border-color:rgba(0,0,0,0.12)}
html[data-workbench-theme='light'] .aa-input{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .aa-table th,html[data-workbench-theme='light'] .aa-table td{border-color:#e2e8f0}
html[data-workbench-theme='light'] .ok{color:#059669}
html[data-workbench-theme='light'] .bad{color:#dc2626}
html[data-workbench-theme='light'] .aa-modal{background:rgba(0,0,0,0.25)}
html[data-workbench-theme='light'] .aa-modal-body{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .btn{border-color:#d1d5db}
html[data-workbench-theme='light'] .btn.primary{background:#3b82f6;color:#fff}
html[data-workbench-theme='light'] .btn.link{color:#2563eb}
html[data-workbench-theme='light'] .btn.link.bad{color:#dc2626}
</style>
