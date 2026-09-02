<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../../api'
import { errorMessage } from '../../utils/typeNarrowing'

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
    const [list, catalog] = await Promise.all([api.developerListWebhooks(), api.developerWebhookEventCatalog()])
    subs.value = Array.isArray(list) ? (list as Subscription[]) : []
    eventCatalog.value = Array.isArray(catalog) ? (catalog as EventDef[]) : []
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '加载失败')
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
    const payload: {
      name: string
      target_url: string
      description: string
      enabled_events: string[]
      is_active: boolean
      secret?: string
    } = {
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
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '保存失败')
  } finally {
    dialog.busy = false
  }
}

async function toggleActive(s: Subscription) {
  try {
    await api.developerUpdateWebhook(s.id, { is_active: !s.is_active })
    await refresh()
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '切换失败')
  }
}

async function deleteSub(s: Subscription) {
  if (!confirm(`确认删除 "${s.name}"？已记录的投递日志会保留。`)) return
  try {
    await api.developerDeleteWebhook(s.id)
    await refresh()
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '删除失败')
  }
}

async function sendTest(s: Subscription) {
  try {
    await api.developerTestWebhook(s.id)
    await refresh()
    if (deliveriesPanel.open && deliveriesPanel.subId === s.id) {
      await openDeliveries(s)
    }
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '测试发送失败')
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
    const rows = await api.developerListWebhookDeliveries(deliveriesPanel.subId, {
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
  } catch (e: unknown) {
    errMsg.value = errorMessage(e, '重试失败')
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
    <div v-else-if="!subs.length" class="dw__placeholder">还没有订阅。新建一个，把 MODstore 的事件投递到你的 HTTP 端点。</div>

    <ul v-else class="dw__list">
      <li v-for="s in subs" :key="s.id" class="dw__item" :class="{ 'dw__item--off': !s.is_active }">
        <header class="dw__item-head">
          <h3 class="dw__item-name">{{ s.name || '(未命名)' }}</h3>
          <span :class="statusChipClass(s.last_delivery_status)">
            {{ s.is_active ? '启用' : '已停用' }}
            <span v-if="s.last_delivery_status">· 最近 {{ s.last_delivery_status }}</span>
          </span>
        </header>
        <p class="dw__item-url">
          <code>{{ s.target_url }}</code>
        </p>
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
                  <input type="checkbox" :checked="dialog.selectedEvents.has('*')" @change="toggleEvent('*')" />
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
                  <span class="dw-event-card__name"
                    >{{ e.name }} <small>v{{ e.version }}</small></span
                  >
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
              · 尝试 {{ d.attempts }} · {{ d.duration_ms.toFixed(0) }}ms
              <span v-if="d.status_code"> · HTTP {{ d.status_code }}</span>
            </p>
            <p v-if="d.error_message" class="dw-deliveries__err">{{ d.error_message }}</p>
            <div class="dw-deliveries__actions">
              <button class="dw__btn" type="button" @click="previewDelivery = d">查看 Payload</button>
              <button v-if="d.status !== 'success'" class="dw__btn" type="button" @click="retryDelivery(d)">重试</button>
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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./developer-webhooks/developerWebhooks.css，逻辑与模板保持原样。 -->
<style scoped src="./developer-webhooks/developerWebhooks.css"></style>
