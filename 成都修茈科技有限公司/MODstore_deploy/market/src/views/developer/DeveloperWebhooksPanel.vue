<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../../api'

interface Subscription {
  id: number
  name: string
  description: string
  target_url: string
  has_secret: boolean
  secret_storage: 'fernet' | 'plaintext' | 'none'
  enabled_events: string[]
  is_active: boolean
  success_count: number
  failure_count: number
  last_delivery_at: string | null
  last_delivery_status: string
  created_at: string | null
}

interface EventDef {
  name: string
  version: number
  aggregate: string
  description: string
}

interface Delivery {
  id: number
  event_id: string
  event_type: string
  status: 'success' | 'failed' | 'pending'
  status_code: number | null
  attempts: number
  duration_ms: number
  request_body: string
  response_body: string
  error_message: string
  started_at: string | null
}

const subs = ref<Subscription[]>([])
const eventCatalog = ref<EventDef[]>([])
const loading = ref(false)
const errMsg = ref('')

const dialog = reactive({
  open: false,
  busy: false,
  editingId: null as number | null,
  name: '',
  url: '',
  description: '',
  secret: '',
  selectedEvents: new Set<string>(['*']),
  isActive: true,
})

const deliveriesPanel = reactive({
  open: false,
  subId: 0,
  rows: [] as Delivery[],
  status: '',
  loading: false,
})

const previewDelivery = ref<Delivery | null>(null)

async function refresh() {
  loading.value = true
  errMsg.value = ''
  try {
    const [list, catalog] = await Promise.all([
      api.developerListWebhooks(),
      api.developerWebhookEventCatalog(),
    ])
    subs.value = Array.isArray(list) ? (list as Subscription[]) : []
    eventCatalog.value = Array.isArray(catalog) ? (catalog as EventDef[]) : []
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

function openCreate() {
  dialog.editingId = null
  dialog.name = ''
  dialog.url = ''
  dialog.description = ''
  dialog.secret = ''
  dialog.selectedEvents = new Set<string>(['*'])
  dialog.isActive = true
  dialog.open = true
}

function openEdit(s: Subscription) {
  dialog.editingId = s.id
  dialog.name = s.name
  dialog.url = s.target_url
  dialog.description = s.description
  dialog.secret = ''
  dialog.selectedEvents = new Set<string>(s.enabled_events.length ? s.enabled_events : ['*'])
  dialog.isActive = s.is_active
  dialog.open = true
}

function closeDialog() {
  if (dialog.busy) return
  dialog.open = false
}

function toggleEvent(name: string) {
  if (name === '*') {
    if (dialog.selectedEvents.has('*')) {
      dialog.selectedEvents.delete('*')
    } else {
      dialog.selectedEvents = new Set(['*'])
    }
    return
  }
  if (dialog.selectedEvents.has(name)) {
    dialog.selectedEvents.delete(name)
  } else {
    dialog.selectedEvents.delete('*')
    dialog.selectedEvents.add(name)
  }
}

const selectedEventsList = computed(() => Array.from(dialog.selectedEvents))

async function submitDialog() {
  if (!dialog.name.trim()) {
    errMsg.value = '请填写名称'
    return
  }
  if (!dialog.url.trim()) {
    errMsg.value = '请填写目标 URL'
    return
  }
  dialog.busy = true
  errMsg.value = ''
  try {
    const payload: any = {
      name: dialog.name.trim(),
      target_url: dialog.url.trim(),
      description: dialog.description.trim(),
      enabled_events: selectedEventsList.value.length ? selectedEventsList.value : ['*'],
      is_active: dialog.isActive,
    }
    if (dialog.secret) payload.secret = dialog.secret
    if (dialog.editingId) {
      await api.developerUpdateWebhook(dialog.editingId, payload)
    } else {
      await api.developerCreateWebhook(payload)
    }
    dialog.open = false
    await refresh()
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '保存失败'
  } finally {
    dialog.busy = false
  }
}

async function toggleActive(s: Subscription) {
  try {
    await api.developerUpdateWebhook(s.id, { is_active: !s.is_active })
    await refresh()
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '切换失败'
  }
}

async function deleteSub(s: Subscription) {
  if (!confirm(`确认删除 "${s.name}"？已记录的投递日志会保留。`)) return
  try {
    await api.developerDeleteWebhook(s.id)
    await refresh()
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '删除失败'
  }
}

async function sendTest(s: Subscription) {
  try {
    await api.developerTestWebhook(s.id)
    await refresh()
    if (deliveriesPanel.open && deliveriesPanel.subId === s.id) {
      await openDeliveries(s)
    }
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '测试发送失败'
  }
}

async function openDeliveries(s: Subscription) {
  deliveriesPanel.open = true
  deliveriesPanel.subId = s.id
  await loadDeliveries()
}

async function loadDeliveries() {
  deliveriesPanel.loading = true
  try {
    const rows: any = await api.developerListWebhookDeliveries(deliveriesPanel.subId, {
      limit: 100,
      status: deliveriesPanel.status || undefined,
    })
    deliveriesPanel.rows = Array.isArray(rows) ? (rows as Delivery[]) : []
  } catch {
    deliveriesPanel.rows = []
  } finally {
    deliveriesPanel.loading = false
  }
}

async function retryDelivery(d: Delivery) {
  try {
    await api.developerRetryWebhookDelivery(d.id)
    await loadDeliveries()
    await refresh()
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '重试失败'
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

function statusChipClass(s: string): string {
  return `dw__chip dw__chip--${s || 'idle'}`
}
</script>

<template>
  <div class="dw dw--dark">
    <header class="dw__head">
      <div>
        <h2 class="dw__title">Webhook 订阅</h2>
        <p class="dw__hint">
          按事件名订阅业务回调，HMAC-SHA256 签名见
          <code>X-Modstore-Webhook-Signature</code> 头。
        </p>
      </div>
      <button class="dw__btn dw__btn--primary" type="button" @click="openCreate">新建订阅</button>
    </header>

    <p v-if="errMsg" class="dw__err">{{ errMsg }}</p>

    <div v-if="loading" class="dw__placeholder">加载中…</div>
    <div v-else-if="!subs.length" class="dw__placeholder">
      还没有订阅。新建一个，把 MODstore 的事件投递到你的 HTTP 端点。
    </div>

    <ul v-else class="dw__list">
      <li v-for="s in subs" :key="s.id" class="dw__item" :class="{ 'dw__item--off': !s.is_active }">
        <header class="dw__item-head">
          <h3 class="dw__item-name">{{ s.name || '(未命名)' }}</h3>
          <span :class="statusChipClass(s.last_delivery_status)">
            {{ s.is_active ? '启用' : '已停用' }}
            <span v-if="s.last_delivery_status">· 最近 {{ s.last_delivery_status }}</span>
          </span>
        </header>
        <p class="dw__item-url"><code>{{ s.target_url }}</code></p>
        <div class="dw__item-events">
          <span v-for="e in s.enabled_events" :key="e" class="dw__event-pill">{{ e }}</span>
        </div>
        <p v-if="s.description" class="dw__item-desc">{{ s.description }}</p>
        <footer class="dw__item-foot">
          <span class="dw__metric">成功 {{ s.success_count }}</span>
          <span class="dw__metric dw__metric--err">失败 {{ s.failure_count }}</span>
          <span class="dw__metric">最近：{{ formatTime(s.last_delivery_at) }}</span>
          <span
            class="dw__metric"
            :class="{ 'dw__metric--err': s.secret_storage === 'plaintext' }"
            :title="s.secret_storage === 'plaintext' ? '服务端 MODSTORE_FERNET_KEY 未配置，密钥以明文落库；建议尽快配置' : ''"
          >
            {{
              s.secret_storage === 'fernet'
                ? '已设密钥（Fernet 加密）'
                : s.secret_storage === 'plaintext'
                ? '⚠ 密钥明文存储'
                : '无 HMAC 密钥'
            }}
          </span>
          <span class="dw__spacer" />
          <button class="dw__btn" type="button" @click="sendTest(s)">发送测试</button>
          <button class="dw__btn" type="button" @click="openDeliveries(s)">投递日志</button>
          <button class="dw__btn" type="button" @click="toggleActive(s)">
            {{ s.is_active ? '停用' : '启用' }}
          </button>
          <button class="dw__btn" type="button" @click="openEdit(s)">编辑</button>
          <button class="dw__btn dw__btn--danger" type="button" @click="deleteSub(s)">删除</button>
        </footer>
      </li>
    </ul>

    <transition name="dw-fade">
      <div v-if="dialog.open" class="dw-modal" @click.self="closeDialog">
        <div class="dw-modal__card">
          <header class="dw-modal__head">
            <h3>{{ dialog.editingId ? '编辑订阅' : '新建订阅' }}</h3>
            <button class="dw__btn" type="button" :disabled="dialog.busy" @click="closeDialog">关闭</button>
          </header>
          <div class="dw-modal__body">
            <label class="dw-field">
              <span>名称</span>
              <input v-model="dialog.name" type="text" placeholder="例如：CRM 同步" />
            </label>
            <label class="dw-field">
              <span>目标 URL</span>
              <input v-model="dialog.url" type="url" placeholder="https://example.com/webhooks/modstore" />
            </label>
            <label class="dw-field">
              <span>HMAC 共享密钥（可选；填写后将以 Fernet 加密保存）</span>
              <input v-model="dialog.secret" type="text" :placeholder="dialog.editingId ? '留空保持原密钥' : '建议至少 32 字节'" />
            </label>
            <label class="dw-field">
              <span>说明（可选）</span>
              <textarea v-model="dialog.description" rows="2" />
            </label>

            <div class="dw-field">
              <span>订阅事件</span>
              <div class="dw-event-grid">
                <label class="dw-event-card" :class="{ 'dw-event-card--on': dialog.selectedEvents.has('*') }">
                  <input
                    type="checkbox"
                    :checked="dialog.selectedEvents.has('*')"
                    @change="toggleEvent('*')"
                  />
                  <span class="dw-event-card__name">* (全部事件)</span>
                  <span class="dw-event-card__desc">订阅当前与未来所有事件类型</span>
                </label>
                <label
                  v-for="e in eventCatalog"
                  :key="e.name"
                  class="dw-event-card"
                  :class="{ 'dw-event-card--on': dialog.selectedEvents.has(e.name) }"
                >
                  <input
                    type="checkbox"
                    :disabled="dialog.selectedEvents.has('*')"
                    :checked="dialog.selectedEvents.has(e.name)"
                    @change="toggleEvent(e.name)"
                  />
                  <span class="dw-event-card__name">{{ e.name }} <small>v{{ e.version }}</small></span>
                  <span class="dw-event-card__desc">{{ e.description }}</span>
                </label>
              </div>
            </div>

            <label class="dw-field dw-field--inline">
              <input type="checkbox" v-model="dialog.isActive" />
              <span>立即启用</span>
            </label>
          </div>
          <footer class="dw-modal__foot">
            <button class="dw__btn" type="button" :disabled="dialog.busy" @click="closeDialog">取消</button>
            <button class="dw__btn dw__btn--primary" type="button" :disabled="dialog.busy" @click="submitDialog">
              {{ dialog.busy ? '保存中…' : '保存' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>

    <transition name="dw-fade">
      <aside v-if="deliveriesPanel.open" class="dw-deliveries">
        <header class="dw-deliveries__head">
          <h3>投递日志</h3>
          <button class="dw__btn" type="button" @click="deliveriesPanel.open = false">关闭</button>
        </header>
        <div class="dw-deliveries__filter">
          <select v-model="deliveriesPanel.status" @change="loadDeliveries">
            <option value="">全部状态</option>
            <option value="success">success</option>
            <option value="failed">failed</option>
            <option value="pending">pending</option>
          </select>
          <button class="dw__btn" type="button" @click="loadDeliveries">刷新</button>
        </div>
        <div v-if="deliveriesPanel.loading" class="dw__placeholder">加载中…</div>
        <div v-else-if="!deliveriesPanel.rows.length" class="dw__placeholder">暂无投递</div>
        <ul v-else class="dw-deliveries__list">
          <li v-for="d in deliveriesPanel.rows" :key="d.id" class="dw-deliveries__item">
            <header class="dw-deliveries__item-head">
              <span :class="statusChipClass(d.status)">{{ d.status }}</span>
              <span class="dw-deliveries__time">{{ formatTime(d.started_at) }}</span>
            </header>
            <p class="dw-deliveries__type">
              <code>{{ d.event_type }}</code>
              · 尝试 {{ d.attempts }}
              · {{ d.duration_ms.toFixed(0) }}ms
              <span v-if="d.status_code"> · HTTP {{ d.status_code }}</span>
            </p>
            <p v-if="d.error_message" class="dw-deliveries__err">{{ d.error_message }}</p>
            <div class="dw-deliveries__actions">
              <button class="dw__btn" type="button" @click="previewDelivery = d">查看 Payload</button>
              <button v-if="d.status !== 'success'" class="dw__btn" type="button" @click="retryDelivery(d)">
                重试
              </button>
            </div>
          </li>
        </ul>
      </aside>
    </transition>

    <transition name="dw-fade">
      <div v-if="previewDelivery" class="dw-modal" @click.self="previewDelivery = null">
        <div class="dw-modal__card">
          <header class="dw-modal__head">
            <h3>投递 #{{ previewDelivery.id }} · {{ previewDelivery.event_type }}</h3>
            <button class="dw__btn" type="button" @click="previewDelivery = null">关闭</button>
          </header>
          <div class="dw-modal__body">
            <h4 class="dw-preview__h4">请求体</h4>
            <pre class="dw-preview__pre">{{ previewDelivery.request_body || '(空)' }}</pre>
            <h4 class="dw-preview__h4">响应体（截断 1KB）</h4>
            <pre class="dw-preview__pre">{{ previewDelivery.response_body || '(无响应)' }}</pre>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.dw__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.dw__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.dw__hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
}

.dw__hint code {
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 11px;
}

.dw__err {
  margin: 0 0 12px;
  padding: 8px 12px;
  background: #fee2e2;
  color: #991b1b;
  border-radius: 6px;
  font-size: 13px;
}

.dw__placeholder {
  padding: 24px;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  font-size: 13px;
}

.dw__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dw__item {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.dw__item--off {
  opacity: 0.7;
}

.dw__item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.dw__item-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.dw__item-url {
  margin: 0 0 6px;
  font-size: 12px;
  color: #475569;
  word-break: break-all;
}

.dw__item-url code {
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}

.dw__item-events {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.dw__event-pill {
  font-size: 11px;
  background: #eef2ff;
  color: #3730a3;
  padding: 1px 8px;
  border-radius: 999px;
}

.dw__item-desc {
  margin: 0 0 8px;
  font-size: 12px;
  color: #64748b;
  white-space: pre-wrap;
}

.dw__item-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  border-top: 1px dashed #e2e8f0;
  padding-top: 8px;
  font-size: 12px;
}

.dw__metric {
  font-size: 11px;
  color: #64748b;
}

.dw__metric--err {
  color: #b45309;
}

.dw__spacer {
  flex: 1;
}

.dw__chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  white-space: nowrap;
}

.dw__chip--success {
  background: #dcfce7;
  color: #166534;
}

.dw__chip--failed {
  background: #fee2e2;
  color: #991b1b;
}

.dw__chip--pending {
  background: #fef3c7;
  color: #92400e;
}

.dw__btn {
  font-size: 12px;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.dw__btn:hover:not(:disabled) {
  background: #f1f5f9;
}

.dw__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dw__btn--primary {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #fff;
}

.dw__btn--primary:hover:not(:disabled) {
  background: #4338ca;
}

.dw__btn--danger {
  border-color: #fecaca;
  color: #b91c1c;
}

.dw__btn--danger:hover:not(:disabled) {
  background: #fef2f2;
}

.dw-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 16px;
}

.dw-modal__card {
  width: min(660px, 100%);
  max-height: 90vh;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 24px 48px -16px rgba(15, 23, 42, 0.4);
  display: flex;
  flex-direction: column;
}

.dw-modal__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid #e2e8f0;
}

.dw-modal__head h3 {
  margin: 0;
  font-size: 15px;
}

.dw-modal__body {
  padding: 16px 18px;
  overflow-y: auto;
}

.dw-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid #e2e8f0;
}

.dw-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 14px;
}

.dw-field span {
  font-size: 12px;
  color: #334155;
  font-weight: 500;
}

.dw-field input,
.dw-field textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 13px;
  font-family: inherit;
}

.dw-field input:focus,
.dw-field textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.18);
}

.dw-field--inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.dw-event-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.dw-event-card {
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  column-gap: 8px;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  background: #fafafa;
}

.dw-event-card input {
  grid-row: span 2;
  align-self: center;
}

.dw-event-card--on {
  border-color: #4f46e5;
  background: #eef2ff;
}

.dw-event-card__name {
  font-size: 12px;
  color: #0f172a;
  font-weight: 600;
}

.dw-event-card__desc {
  font-size: 11px;
  color: #64748b;
}

.dw-deliveries {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: min(440px, 100%);
  background: #fff;
  border-left: 1px solid #e2e8f0;
  box-shadow: -16px 0 32px -16px rgba(15, 23, 42, 0.3);
  z-index: 90;
  display: flex;
  flex-direction: column;
}

.dw-deliveries__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.dw-deliveries__head h3 {
  margin: 0;
  font-size: 15px;
}

.dw-deliveries__filter {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.dw-deliveries__filter select {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
}

.dw-deliveries__list {
  list-style: none;
  margin: 0;
  padding: 4px 0;
  overflow-y: auto;
  flex: 1;
}

.dw-deliveries__item {
  padding: 10px 16px;
  border-bottom: 1px dashed #e2e8f0;
}

.dw-deliveries__item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dw-deliveries__time {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}

.dw-deliveries__type {
  margin: 4px 0;
  font-size: 12px;
  color: #475569;
}

.dw-deliveries__type code {
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
}

.dw-deliveries__err {
  margin: 0 0 6px;
  padding: 4px 8px;
  background: #fef2f2;
  color: #991b1b;
  font-size: 11px;
  border-radius: 4px;
  white-space: pre-wrap;
}

.dw-deliveries__actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

.dw-preview__h4 {
  margin: 12px 0 4px;
  font-size: 12px;
  color: #475569;
}

.dw-preview__pre {
  margin: 0;
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px 12px;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 220px;
  overflow-y: auto;
}

/* 开发者门户全深色 */
.dw.dw--dark {
  color: rgba(248, 250, 252, 0.92);
}
.dw.dw--dark .dw__title {
  color: #ffffff;
}
.dw.dw--dark .dw__hint {
  color: rgba(255, 255, 255, 0.55);
}
.dw.dw--dark .dw__hint code {
  background: rgba(15, 23, 42, 0.65);
  color: #e2e8f0;
}
.dw.dw--dark .dw__err {
  background: rgba(255, 80, 80, 0.12);
  color: #ff6b6b;
}
.dw.dw--dark .dw__placeholder {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.45);
}
.dw.dw--dark .dw__item {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: none;
}
.dw.dw--dark .dw__item-name {
  color: #ffffff;
}
.dw.dw--dark .dw__item-url {
  color: rgba(255, 255, 255, 0.55);
}
.dw.dw--dark .dw__item-url code {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}
.dw.dw--dark .dw__event-pill {
  background: rgba(129, 140, 248, 0.18);
  color: #c7d2fe;
}
.dw.dw--dark .dw__item-desc {
  color: rgba(255, 255, 255, 0.5);
}
.dw.dw--dark .dw__item-foot {
  border-top-color: rgba(255, 255, 255, 0.08);
}
.dw.dw--dark .dw__metric {
  color: rgba(255, 255, 255, 0.45);
}
.dw.dw--dark .dw__metric--err {
  color: #fbbf24;
}
.dw.dw--dark .dw__chip {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(226, 232, 240, 0.9);
}
.dw.dw--dark .dw__chip--success {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
}
.dw.dw--dark .dw__chip--failed {
  background: rgba(255, 80, 80, 0.15);
  color: #ff6b6b;
}
.dw.dw--dark .dw__chip--pending {
  background: rgba(234, 179, 8, 0.15);
  color: #fbbf24;
}
.dw.dw--dark .dw__btn {
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: #111111;
  color: #ffffff;
}
.dw.dw--dark .dw__btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}
.dw.dw--dark .dw__btn--primary {
  background: #ffffff;
  border-color: transparent;
  color: #0a0a0a;
}
.dw.dw--dark .dw__btn--primary:hover:not(:disabled) {
  opacity: 0.9;
}
.dw.dw--dark .dw__btn--danger {
  border-color: rgba(255, 80, 80, 0.35);
  color: #ff6b6b;
  background: rgba(255, 80, 80, 0.08);
}
.dw.dw--dark .dw__btn--danger:hover:not(:disabled) {
  background: rgba(255, 80, 80, 0.15);
}
.dw.dw--dark .dw-modal__card {
  background: #141416;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.65);
}
.dw.dw--dark .dw-modal__head {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}
.dw.dw--dark .dw-modal__head h3 {
  color: #ffffff;
}
.dw.dw--dark .dw-modal__body {
  color: rgba(248, 250, 252, 0.88);
}
.dw.dw--dark .dw-modal__foot {
  border-top-color: rgba(255, 255, 255, 0.1);
}
.dw.dw--dark .dw-field span {
  color: rgba(255, 255, 255, 0.65);
}
.dw.dw--dark .dw-field input,
.dw.dw--dark .dw-field textarea {
  background: rgba(255, 255, 255, 0.03);
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  color: #ffffff;
}
.dw.dw--dark .dw-field input:focus,
.dw.dw--dark .dw-field textarea:focus {
  outline: none;
  border-color: rgba(165, 180, 252, 0.55);
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.2);
}
.dw.dw--dark .dw-event-card {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.2);
}
.dw.dw--dark .dw-event-card--on {
  border-color: rgba(129, 140, 248, 0.55);
  background: rgba(129, 140, 248, 0.12);
}
.dw.dw--dark .dw-event-card__name {
  color: #f8fafc;
}
.dw.dw--dark .dw-event-card__desc {
  color: rgba(255, 255, 255, 0.5);
}
.dw.dw--dark .dw-deliveries {
  background: #141416;
  border-left-color: rgba(255, 255, 255, 0.1);
  box-shadow: -16px 0 32px -12px rgba(0, 0, 0, 0.65);
}
.dw.dw--dark .dw-deliveries__head {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}
.dw.dw--dark .dw-deliveries__head h3 {
  color: #ffffff;
}
.dw.dw--dark .dw-deliveries__filter {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}
.dw.dw--dark .dw-deliveries__filter select {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.15);
  color: #f8fafc;
}
.dw.dw--dark .dw-deliveries__item {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}
.dw.dw--dark .dw-deliveries__time {
  color: rgba(255, 255, 255, 0.4);
}
.dw.dw--dark .dw-deliveries__type {
  color: rgba(255, 255, 255, 0.65);
}
.dw.dw--dark .dw-deliveries__type code {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}
.dw.dw--dark .dw-deliveries__err {
  background: rgba(255, 80, 80, 0.12);
  color: #ff6b6b;
}
.dw.dw--dark .dw-preview__h4 {
  color: rgba(255, 255, 255, 0.55);
}

.dw-fade-enter-active,
.dw-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.dw-fade-enter-from,
.dw-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
