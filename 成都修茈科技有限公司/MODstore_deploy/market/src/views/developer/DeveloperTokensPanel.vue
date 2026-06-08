<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../../api'
import { confirmDanger } from '../../composables/useDangerConfirm'
import { ApiError } from '../../infrastructure/http/client'

function errText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message
  if (e && typeof e === 'object') {
    const o = e as { message?: string; detail?: unknown }
    if (typeof o.message === 'string' && o.message.trim()) return o.message
    if (typeof o.detail === 'string' && o.detail.trim()) return o.detail
  }
  return fallback
}

interface DeveloperToken {
  id: number
  name: string
  prefix: string
  scopes: string[]
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  is_active: boolean
}

const tokens = ref<DeveloperToken[]>([])
const activeTokens = computed(() => tokens.value.filter((t) => t.is_active))
const loading = ref(false)
const errMsg = ref('')

const showDialog = ref(false)
const submitBusy = ref(false)
const draft = reactive({ name: '', scopesCsv: 'mod:sync,catalog:read', expiresDays: '90' })

const justCreated = ref<{ token: string; meta: DeveloperToken } | null>(null)
const copied = ref(false)

const SCOPE_HINTS = [
  'mod:sync',
  'llm:use',
  'workflow:read',
  'workflow:execute',
  'employee:execute',
  'catalog:read',
  'webhook:manage',
]

const desktopPubB64 = ref('')
const exportPassword = ref('')
const exportSelected = ref<number[]>([])
const exportBusy = ref(false)
const exportAuditOpen = ref(false)
const exportAudit = ref<any[]>([])
const exportAuditLoading = ref(false)

function onExportCheck(id: number, ev: Event) {
  const el = ev.target as HTMLInputElement
  if (el.checked) {
    if (!exportSelected.value.includes(id)) exportSelected.value = [...exportSelected.value, id]
  } else {
    exportSelected.value = exportSelected.value.filter((x) => x !== id)
  }
}

function selectAllActiveForExport() {
  exportSelected.value = activeTokens.value.map((t) => t.id)
}

async function runExportBundle() {
  errMsg.value = ''
  if (!desktopPubB64.value.trim()) {
    errMsg.value = '请粘贴桌面端公钥（SPKI DER 的 base64）'
    return
  }
  if (!exportPassword.value) {
    errMsg.value = '请输入当前登录密码以确认导出'
    return
  }
  if (!exportSelected.value.length) {
    errMsg.value = '请至少勾选一个要下发的 Token'
    return
  }
  if (
    !confirm(
      '将使用所选 Token 的同名同权限**轮换签发**新明文，并仅写入加密包；网页上旧前缀将立即失效。确定继续？',
    )
  )
    return
  exportBusy.value = true
  try {
    const resp: any = await api.developerExportKeyBundle({
      recipient_public_key_spki_b64: desktopPubB64.value.trim(),
      current_password: exportPassword.value,
      token_ids: exportSelected.value,
      rotate_source_tokens: true,
    })
    const b64 = resp?.cipher_b64 as string
    if (!b64) throw new Error('响应缺少 cipher_b64')
    const bin = atob(b64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    const blob = new Blob([bytes], { type: 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `modstore-keybundle-${Date.now()}.msk1`
    a.click()
    URL.revokeObjectURL(url)
    exportPassword.value = ''
    await refresh()
  } catch (e: unknown) {
    errMsg.value = errText(e, '导出失败')
  } finally {
    exportBusy.value = false
  }
}

async function loadExportAudit() {
  exportAuditLoading.value = true
  try {
    const r: any = await api.developerListKeyExportAudit(30)
    exportAudit.value = Array.isArray(r?.events) ? r.events : []
  } catch {
    exportAudit.value = []
  } finally {
    exportAuditLoading.value = false
  }
}

async function toggleAudit() {
  exportAuditOpen.value = !exportAuditOpen.value
  if (exportAuditOpen.value && !exportAudit.value.length) await loadExportAudit()
}

async function refresh() {
  loading.value = true
  errMsg.value = ''
  try {
    const list: any = await api.developerListTokens()
    tokens.value = Array.isArray(list) ? list : []
  } catch (e: unknown) {
    errMsg.value = errText(e, '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

function openCreate() {
  draft.name = ''
  draft.scopesCsv = 'mod:sync,catalog:read'
  draft.expiresDays = '90'
  showDialog.value = true
}

function addScope(scope: string) {
  const scopes = draft.scopesCsv
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (!scopes.includes(scope)) scopes.push(scope)
  draft.scopesCsv = scopes.join(',')
}

function closeCreate() {
  if (submitBusy.value) return
  showDialog.value = false
}

async function submitCreate() {
  if (!draft.name.trim()) {
    errMsg.value = '请填写 Token 名称'
    return
  }
  const ok = await confirmDanger({
    title: '创建开发者 Token',
    message: `将创建名为「${draft.name.trim()}」的 API Token。创建后请立即复制保存，明文仅显示一次。`,
    confirmLabel: '创建',
  })
  if (!ok) return
  submitBusy.value = true
  errMsg.value = ''
  try {
    const scopes = draft.scopesCsv
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const days = draft.expiresDays.trim() ? Number(draft.expiresDays) : null
    const resp: any = await api.developerCreateToken(
      draft.name.trim(),
      scopes,
      Number.isFinite(days as number) && (days as number) > 0 ? (days as number) : null,
    )
    showDialog.value = false
    if (resp?.token) {
      const { token, ...meta } = resp
      justCreated.value = { token, meta: meta as DeveloperToken }
      copied.value = false
    }
    await refresh()
  } catch (e: unknown) {
    errMsg.value = errText(e, '创建失败')
  } finally {
    submitBusy.value = false
  }
}

async function copyJustCreated() {
  if (!justCreated.value) return
  try {
    await navigator.clipboard.writeText(justCreated.value.token)
    copied.value = true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = justCreated.value.token
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      copied.value = true
    } finally {
      document.body.removeChild(ta)
    }
  }
}

function dismissJustCreated() {
  if (!copied.value && !confirm('确定关闭？关闭后将无法再次查看明文，请确认已经复制并妥善保管。')) return
  justCreated.value = null
}

async function revoke(row: DeveloperToken) {
  const ok = await confirmDanger({
    title: '吊销 Token',
    message: `确认吊销「${row.name}」？已分发的客户端将立即失效。`,
    confirmLabel: '吊销',
    destructive: true,
  })
  if (!ok) return
  try {
    await api.developerRevokeToken(row.id)
    await refresh()
  } catch (e: any) {
    errMsg.value = errText(e, '吊销失败')
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function statusOf(row: DeveloperToken): { text: string; cls: string } {
  if (row.revoked_at) return { text: '已吊销', cls: 'st-revoked' }
  if (row.expires_at && new Date(row.expires_at).getTime() < Date.now())
    return { text: '已过期', cls: 'st-expired' }
  return { text: '可用', cls: 'st-active' }
}

function justCreatedHasScope(scope: string): boolean {
  return !!justCreated.value?.meta?.scopes?.includes(scope)
}
</script>

<template>
  <div class="dt dt--dark">
    <header class="dt__head">
      <div>
        <h2 class="dt__title">Personal Access Token</h2>
        <p class="dt__hint">Bearer Token 调用 API；创建后明文仅显示一次。<a href="/dev-docs/" target="_blank" rel="noreferrer">文档</a></p>
      </div>
      <button class="dt__btn dt__btn--primary" type="button" @click="openCreate">
        创建新 Token
      </button>
    </header>

    <p v-if="errMsg" class="dt__err">{{ errMsg }}</p>

    <div v-if="loading" class="dt__placeholder">加载中…</div>
    <div v-else-if="!tokens.length" class="dt__placeholder">
      还没有 Token，点击「创建新 Token」开始接入第三方应用。
    </div>
    <table v-else class="dt__table">
      <thead>
        <tr>
          <th>名称</th>
          <th>前缀</th>
          <th>权限范围</th>
          <th>创建时间</th>
          <th>最近使用</th>
          <th>过期</th>
          <th>状态</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in tokens" :key="t.id" :class="{ 'dt__row--inactive': !t.is_active }">
          <td>{{ t.name || '—' }}</td>
          <td><code>{{ t.prefix }}…</code></td>
          <td>
            <span v-if="!t.scopes.length" class="dt__scope-empty">未配置</span>
            <span v-for="s in t.scopes" :key="s" class="dt__scope">{{ s }}</span>
          </td>
          <td>{{ formatTime(t.created_at) }}</td>
          <td>{{ formatTime(t.last_used_at) }}</td>
          <td>{{ t.expires_at ? formatTime(t.expires_at) : '永不' }}</td>
          <td>
            <span class="dt__status" :class="statusOf(t).cls">{{ statusOf(t).text }}</span>
          </td>
          <td>
            <button
              v-if="t.is_active"
              class="dt__btn dt__btn--danger"
              type="button"
              @click="revoke(t)"
            >
              吊销
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <section class="dt-desk">
      <h3 class="dt-desk__title">传到桌面（加密包）</h3>
      <p class="dt-desk__hint">粘贴桌面公钥并确认密码后下发加密包。<a href="/dev-docs/developer/08-key-export-desktop.md" target="_blank" rel="noreferrer">说明</a></p>
      <label class="dt-field">
        <span>桌面端公钥（base64 DER SPKI）</span>
        <textarea v-model="desktopPubB64" class="dt-desk__ta" rows="3" placeholder="MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE..." />
      </label>
      <label class="dt-field">
        <span>当前登录密码（二次确认）</span>
        <input v-model="exportPassword" type="password" autocomplete="current-password" />
      </label>
      <div v-if="activeTokens.length" class="dt-desk__pick">
        <div class="dt-desk__pick-head">
          <span>要下发的 Token（多选）</span>
          <button type="button" class="dt__btn" @click="selectAllActiveForExport">全选可用</button>
        </div>
        <label v-for="t in activeTokens" :key="'ex-' + t.id" class="dt-desk__cb">
          <input type="checkbox" :checked="exportSelected.includes(t.id)" @change="onExportCheck(t.id, $event)" />
          <span>{{ t.name }} <code>{{ t.prefix }}…</code></span>
        </label>
      </div>
      <p v-else class="dt__placeholder">没有可用 Token，请先创建。</p>
      <div class="dt-desk__actions">
        <button
          class="dt__btn dt__btn--primary"
          type="button"
          :disabled="exportBusy || !activeTokens.length"
          @click="runExportBundle"
        >
          {{ exportBusy ? '生成中…' : '生成并下载 .msk1 加密包' }}
        </button>
        <button type="button" class="dt__btn" @click="toggleAudit">
          {{ exportAuditOpen ? '收起' : '查看' }}导出审计
        </button>
      </div>
      <div v-if="exportAuditOpen" class="dt-desk__audit">
        <p v-if="exportAuditLoading">加载审计…</p>
        <table v-else-if="exportAudit.length" class="dt__table dt__table--compact">
          <thead>
            <tr>
              <th>时间</th>
              <th>动作</th>
              <th>成功</th>
              <th>详情</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ev in exportAudit" :key="ev.id">
              <td>{{ formatTime(ev.created_at) }}</td>
              <td>{{ ev.action }}</td>
              <td>{{ ev.success ? '是' : '否' }}</td>
              <td>{{ ev.detail }}</td>
              <td>{{ ev.client_ip || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="dt__placeholder">暂无记录</p>
      </div>
    </section>

    <transition name="dt-fade">
      <div v-if="showDialog" class="dt-modal" @click.self="closeCreate">
        <div class="dt-modal__card">
          <header class="dt-modal__head">
            <h3>创建新 Token</h3>
            <button class="dt__btn" type="button" :disabled="submitBusy" @click="closeCreate">关闭</button>
          </header>
          <div class="dt-modal__body">
            <label class="dt-field">
              <span>名称</span>
              <input v-model="draft.name" type="text" placeholder="例如：本地脚本 / CI Pipeline" />
            </label>
            <label class="dt-field">
              <span>权限范围（逗号分隔）</span>
              <input v-model="draft.scopesCsv" type="text" placeholder="mod:sync,catalog:read" />
              <small class="dt-field__hint">
                本地 Mod 同步请至少包含 <code>mod:sync</code>；读取 Catalog 建议同时包含 <code>catalog:read</code>。
                <br />
                可选：
                <button
                  v-for="s in SCOPE_HINTS"
                  :key="s"
                  type="button"
                  class="dt-field__chip"
                  @click="addScope(s)"
                >
                  {{ s }}
                </button>
              </small>
            </label>
            <label class="dt-field">
              <span>有效期（天，留空 = 永不过期）</span>
              <input v-model="draft.expiresDays" type="number" min="1" max="365" placeholder="90" />
            </label>
          </div>
          <footer class="dt-modal__foot">
            <button class="dt__btn" type="button" :disabled="submitBusy" @click="closeCreate">取消</button>
            <button class="dt__btn dt__btn--primary" type="button" :disabled="submitBusy" @click="submitCreate">
              {{ submitBusy ? '提交中…' : '生成 Token' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>

    <transition name="dt-fade">
      <div v-if="justCreated" class="dt-modal">
        <div class="dt-modal__card dt-modal__card--ok">
          <header class="dt-modal__head">
            <h3>Token 已生成 — 仅显示一次</h3>
          </header>
          <div class="dt-modal__body">
            <p class="dt-just__warn">
              这是 <strong>{{ justCreated.meta.name }}</strong> 的明文 Token。请立即复制并妥善保管，关闭后将无法再次查看。
            </p>
            <pre class="dt-just__token">{{ justCreated.token }}</pre>
            <p class="dt-just__sample">使用示例：</p>
            <pre
              v-if="justCreatedHasScope('mod:sync')"
              class="dt-just__sample-code"
><code>curl -X POST https://xiu-ci.com/v1/mod-sync/push \
  -H "Authorization: Bearer {{ justCreated.token }}" \
  -H "Content-Type: application/json" \
  -d '{"mod_ids":["example-mod"]}'</code></pre>
            <pre
              v-else
              class="dt-just__sample-code"
><code>curl https://&lt;your-domain&gt;/api/employees/ \
  -H "Authorization: Bearer {{ justCreated.token }}"</code></pre>
          </div>
          <footer class="dt-modal__foot">
            <button class="dt__btn" type="button" @click="copyJustCreated">
              {{ copied ? '已复制 ✓' : '复制到剪贴板' }}
            </button>
            <button class="dt__btn dt__btn--primary" type="button" @click="dismissJustCreated">
              我已保存
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.dt__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 14px;
}

.dt__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.dt__hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
}

.dt__hint code {
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 11px;
}

.dt__err {
  margin: 0 0 12px;
  padding: 8px 12px;
  background: #fee2e2;
  color: #991b1b;
  border-radius: 6px;
  font-size: 13px;
}

.dt__placeholder {
  padding: 28px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.dt__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.dt__table th,
.dt__table td {
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.dt__table th {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: #f8fafc;
}

.dt__row--inactive {
  color: #94a3b8;
}

.dt__row--inactive code {
  color: #94a3b8;
}

.dt__scope {
  display: inline-block;
  font-size: 11px;
  background: #eef2ff;
  color: #3730a3;
  padding: 1px 6px;
  border-radius: 999px;
  margin-right: 4px;
  margin-bottom: 2px;
}

.dt__scope-empty {
  font-size: 11px;
  color: #94a3b8;
}

.dt__status {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
}

.st-active {
  background: #dcfce7;
  color: #166534;
}

.st-revoked {
  background: #fee2e2;
  color: #991b1b;
}

.st-expired {
  background: #fef3c7;
  color: #92400e;
}

.dt__btn {
  font-size: 13px;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.dt__btn:hover:not(:disabled) {
  background: #f1f5f9;
}

.dt__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dt__btn--primary {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #fff;
}

.dt__btn--primary:hover:not(:disabled) {
  background: #4338ca;
}

.dt__btn--danger {
  border-color: #fecaca;
  color: #b91c1c;
  background: #fff;
}

.dt__btn--danger:hover {
  background: #fef2f2;
}

.dt-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 16px;
}

.dt-modal__card {
  width: min(560px, 100%);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 24px 48px -16px rgba(15, 23, 42, 0.4);
  display: flex;
  flex-direction: column;
}

.dt-modal__card--ok {
  border-top: 4px solid #22c55e;
}

.dt-modal__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid #e2e8f0;
}

.dt-modal__head h3 {
  margin: 0;
  font-size: 15px;
}

.dt-modal__body {
  padding: 16px 18px;
}

.dt-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid #e2e8f0;
}

.dt-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 14px;
}

.dt-field span {
  font-size: 12px;
  color: #334155;
  font-weight: 500;
}

.dt-field input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 13px;
}

.dt-field input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.18);
}

.dt-field__hint {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.dt-field__chip {
  background: #eef2ff;
  color: #3730a3;
  border: 0;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  margin-left: 4px;
  cursor: pointer;
}

.dt-field__chip:hover {
  background: #c7d2fe;
}

.dt-just__warn {
  margin: 0 0 10px;
  font-size: 13px;
  color: #b45309;
  background: #fef3c7;
  padding: 8px 12px;
  border-radius: 6px;
}

.dt-just__token {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  background: #0f172a;
  color: #e2e8f0;
  padding: 12px;
  border-radius: 6px;
  word-break: break-all;
  white-space: pre-wrap;
  margin: 0 0 14px;
}

.dt-just__sample {
  margin: 0 0 4px;
  font-size: 12px;
  color: #475569;
}

.dt-just__sample-code {
  margin: 0;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #0f172a;
}

.dt-desk {
  margin-top: 28px;
  padding: 18px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}

.dt-desk__title {
  margin: 0 0 8px;
  font-size: 16px;
}

.dt-desk__hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
}

.dt-desk__ta {
  width: 100%;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
}

.dt-desk__pick {
  margin: 12px 0;
}

.dt-desk__pick-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
}

.dt-desk__cb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  margin: 4px 0;
}

.dt-desk__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.dt-desk__audit {
  margin-top: 14px;
}

.dt__table--compact {
  font-size: 12px;
}

.dt-fade-enter-active,
.dt-fade-leave-active {
  transition: opacity 0.18s ease;
}

.dt-fade-enter-from,
.dt-fade-leave-to {
  opacity: 0;
}

/* 深色主题（账户中心 / 开发者门户统一） */
.dt.dt--dark {
  color: rgba(248, 250, 252, 0.92);
}

.dt.dt--dark .dt__title {
  color: #ffffff;
}

.dt.dt--dark .dt__hint {
  color: rgba(255, 255, 255, 0.55);
}

.dt.dt--dark .dt__hint code {
  background: rgba(15, 23, 42, 0.65);
  color: #e2e8f0;
}

.dt.dt--dark .dt__err {
  background: rgba(255, 80, 80, 0.12);
  color: #ff6b6b;
}

.dt.dt--dark .dt__placeholder {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.45);
}

.dt.dt--dark .dt__table th,
.dt.dt--dark .dt__table td {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}

.dt.dt--dark .dt__table th {
  color: rgba(255, 255, 255, 0.45);
  background: rgba(0, 0, 0, 0.35);
}

.dt.dt--dark .dt__table td {
  color: rgba(248, 250, 252, 0.9);
}

.dt.dt--dark .dt__table code {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}

.dt.dt--dark .dt__row--inactive,
.dt.dt--dark .dt__row--inactive code {
  color: rgba(255, 255, 255, 0.38);
}

.dt.dt--dark .dt__scope {
  background: rgba(129, 140, 248, 0.18);
  color: #c7d2fe;
}

.dt.dt--dark .dt__scope-empty {
  color: rgba(255, 255, 255, 0.35);
}

.dt.dt--dark .st-active {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
}

.dt.dt--dark .st-revoked {
  background: rgba(255, 80, 80, 0.15);
  color: #ff6b6b;
}

.dt.dt--dark .st-expired {
  background: rgba(234, 179, 8, 0.15);
  color: #fbbf24;
}

.dt.dt--dark .dt__btn {
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: #111111;
  color: #ffffff;
}

.dt.dt--dark .dt__btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.dt.dt--dark .dt__btn--primary {
  background: #ffffff;
  border-color: transparent;
  color: #0a0a0a;
}

.dt.dt--dark .dt__btn--primary:hover:not(:disabled) {
  background: #ffffff;
  opacity: 0.9;
}

.dt.dt--dark .dt__btn--danger {
  border-color: rgba(255, 80, 80, 0.35);
  color: #ff6b6b;
  background: rgba(255, 80, 80, 0.08);
}

.dt.dt--dark .dt__btn--danger:hover {
  background: rgba(255, 80, 80, 0.15);
}

.dt.dt--dark .dt-modal__card {
  background: #141416;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.65);
}

.dt.dt--dark .dt-modal__head {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

.dt.dt--dark .dt-modal__head h3 {
  color: #ffffff;
}

.dt.dt--dark .dt-modal__foot {
  border-top-color: rgba(255, 255, 255, 0.1);
}

.dt.dt--dark .dt-field span {
  color: rgba(255, 255, 255, 0.65);
}

.dt.dt--dark .dt-field input,
.dt.dt--dark .dt-desk__ta {
  background: rgba(255, 255, 255, 0.03);
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
  border-radius: 8px;
}

.dt.dt--dark .dt-desk__ta {
  padding: 8px 10px;
  resize: vertical;
  line-height: 1.45;
}

.dt.dt--dark .dt-field input::placeholder,
.dt.dt--dark .dt-desk__ta::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.dt.dt--dark .dt-field input:focus,
.dt.dt--dark .dt-desk__ta:focus {
  outline: none;
  border-color: rgba(165, 180, 252, 0.55);
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.2);
}

.dt.dt--dark .dt-field__hint {
  color: rgba(255, 255, 255, 0.4);
}

.dt.dt--dark .dt-field__chip {
  background: rgba(129, 140, 248, 0.2);
  color: #c7d2fe;
}

.dt.dt--dark .dt-field__chip:hover {
  background: rgba(129, 140, 248, 0.3);
}

.dt.dt--dark .dt-just__warn {
  color: #fbbf24;
  background: rgba(234, 179, 8, 0.12);
}

.dt.dt--dark .dt-just__sample {
  color: rgba(255, 255, 255, 0.55);
}

.dt.dt--dark .dt-just__sample-code {
  background: rgba(0, 0, 0, 0.45);
  border-color: rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
}

.dt.dt--dark .dt-desk {
  background: rgba(0, 0, 0, 0.22);
  border-color: rgba(255, 255, 255, 0.08);
}

.dt.dt--dark .dt-desk__title {
  color: #ffffff;
}

.dt.dt--dark .dt-desk__hint {
  color: rgba(255, 255, 255, 0.55);
}

.dt.dt--dark .dt-desk__hint a {
  color: #a5b4fc;
}

.dt.dt--dark .dt-desk__hint a:hover {
  text-decoration: underline;
}

.dt.dt--dark .dt-desk__pick-head {
  color: rgba(255, 255, 255, 0.88);
}

.dt.dt--dark .dt-desk__cb {
  color: rgba(248, 250, 252, 0.88);
}

.dt.dt--dark .dt-desk__cb code {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}
</style>
