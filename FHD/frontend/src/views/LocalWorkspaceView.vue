<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { localWorkspaceApi, type LocalArchive, type LocalRecord, type LocalRecordKind } from '@/api/localWorkspace'

const kindLabels: Record<LocalRecordKind, string> = { customer: '客户', product: '商品', order: '订单草稿' }
const kind = ref<LocalRecordKind>('customer')
const status = ref<Awaited<ReturnType<typeof localWorkspaceApi.status>> | null>(null)
const archivePageSize = 100
const archives = ref<LocalArchive[]>([])
const archiveTotal = ref(0)
const archiveOffset = ref(0)
const records = ref<LocalRecord[]>([])
const workspaceId = ref('')
const busy = ref(false)
const current = ref(false)
const message = ref('')
const error = ref('')
const qrUrl = ref('')
let invitationTimer: ReturnType<typeof setTimeout> | undefined
let statusTimer: ReturnType<typeof setInterval> | undefined
const editor = ref(false)
const target = ref<LocalRecord | null>(null)
const conflict = ref<LocalRecord | null>(null)
const editKind = ref<LocalRecordKind>('customer')
const form = ref({ name: '', contact: '', phone: '', sku: '', unitPrice: '', customerId: '', notes: '' })

type DraftItem = { productId: string; quantity: string; unitPrice: string; original: Record<string, unknown> }
const items = ref<DraftItem[]>([])
let lastWrite: { signature: string; opId: string; recordId: string } | undefined
const visible = computed(() => records.value.filter(record => !record.deleted && record.kind === kind.value))
const customers = computed(() => records.value.filter(record => !record.deleted && record.kind === 'customer'))
const products = computed(() => records.value.filter(record => !record.deleted && record.kind === 'product'))

function text(value: unknown) {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}
function rowName(record: LocalRecord) {
  return text(record.kind === 'order' ? record.data.title : record.data.name) || '未命名'
}
function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
function archiveDate(value: LocalArchive['created_at']) {
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value)
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString()
}
function recordSummary(record: LocalRecord) {
  if (record.kind === 'customer') return [record.data.contact, record.data.phone].map(text).filter(Boolean).join(' · ')
  if (record.kind === 'product') return [text(record.data.sku), record.data.unit_price == null ? '' : '¥' + text(record.data.unit_price)].filter(Boolean).join(' · ')
  const count = Array.isArray(record.data.items) ? record.data.items.length : 0
  return [text(record.data.customer), `${count} 项商品`].filter(Boolean).join(' · ')
}

async function load() {
  current.value = false
  const [details, local] = await Promise.all([localWorkspaceApi.records(), localWorkspaceApi.status()])
  if (details.workspace_id !== local.workspace_id) throw new Error('工作区已切换，请刷新重试。')
  if (workspaceId.value && workspaceId.value !== details.workspace_id) {
    editor.value = false
    qrUrl.value = ''
    archiveOffset.value = 0
  }
  if (archiveOffset.value >= local.archives_total) archiveOffset.value = 0
  const archivePage = archiveOffset.value === 0
    ? { archives: local.archives, total: local.archives_total }
    : await localWorkspaceApi.archives(archiveOffset.value, archivePageSize)
  archives.value = archivePage.archives
  archiveTotal.value = archivePage.total
  status.value = local
  workspaceId.value = details.workspace_id
  records.value = details.records
  current.value = true
  if (local.paired) clearInvitation()
}
async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await action()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '本地操作失败，请重试。'
  } finally {
    busy.value = false
  }
}
function refresh() { return run(load) }
function loadArchivePage(offset: number) {
  if (offset < 0 || offset >= archiveTotal.value) return
  return run(async () => {
    const page = await localWorkspaceApi.archives(offset, archivePageSize)
    archives.value = page.archives
    archiveTotal.value = page.total
    archiveOffset.value = offset
  })
}
function clearInvitation() {
  qrUrl.value = ''
  if (invitationTimer !== undefined) clearTimeout(invitationTimer)
}
onMounted(() => {
  void refresh()
  statusTimer = setInterval(() => {
    if (!document.hidden && !busy.value && !editor.value && (qrUrl.value || status.value?.paired)) void refresh()
  }, 3000)
})
onBeforeUnmount(() => {
  clearInvitation()
  if (statusTimer !== undefined) clearInterval(statusTimer)
})

function openEditor(record: LocalRecord | null = null) {
  if (!current.value || busy.value) return
  const data = record?.data ?? {}
  target.value = record
  conflict.value = null
  editKind.value = record?.kind ?? kind.value
  form.value = {
    name: text(data.name) || text(data.title), contact: text(data.contact), phone: text(data.phone),
    sku: text(data.sku), unitPrice: text(data.unit_price), customerId: text(data.customer_id), notes: text(data.notes),
  }
  items.value = Array.isArray(data.items) ? data.items.map((raw: unknown) => {
    const item = asObject(raw)
    return { productId: text(item.product_id), quantity: text(item.quantity), unitPrice: text(item.unit_price), original: item }
  }) : []
  editor.value = true
}
function addItem() {
  items.value.push({ productId: '', quantity: '1', unitPrice: '', original: {} })
}
function setProductPrice(item: DraftItem) {
  const product = products.value.find(record => record.id === item.productId)
  item.unitPrice = text(product?.data.unit_price)
}
function editData(): Record<string, unknown> {
  const value = form.value
  const data = { ...target.value?.data, notes: value.notes.trim() }
  const name = value.name.trim()
  if (!name) throw new Error('请填写名称。')
  if (editKind.value === 'customer') return { ...data, name, contact: value.contact.trim(), phone: value.phone.trim() }
  if (editKind.value === 'product') return { ...data, name, sku: value.sku.trim(), unit_price: Number(value.unitPrice || 0) }

  const customer = customers.value.find(record => record.id === value.customerId)
  return {
    ...data,
    title: name,
    status: 'draft',
    customer_id: value.customerId,
    customer: customer ? rowName(customer) : value.customerId ? text(target.value?.data.customer) : '',
    items: items.value.map(item => {
      const product = products.value.find(record => record.id === item.productId)
      return {
        ...item.original,
        product_id: item.productId,
        product_name: product ? rowName(product) : text(item.original.product_name),
        quantity: Number(item.quantity),
        unit_price: Number(item.unitPrice || 0),
      }
    }),
  }
}
async function write(recordKind: LocalRecordKind, data: Record<string, unknown>, record: LocalRecord | null, deleted = false) {
  const baseVersion = record?.version ?? null
  const signature = JSON.stringify([workspaceId.value, recordKind, record?.id, baseVersion, data, deleted])
  const attempt = lastWrite?.signature === signature
    ? lastWrite
    : { signature, opId: crypto.randomUUID(), recordId: record?.id ?? crypto.randomUUID() }
  lastWrite = attempt
  const result = await localWorkspaceApi.write(workspaceId.value, {
    op_id: attempt.opId, id: attempt.recordId, kind: recordKind, data, deleted, base_version: baseVersion,
  })
  lastWrite = undefined
  if (!result.accepted.includes(attempt.opId)) {
    conflict.value = result.conflicts.find(item => item.op_id === attempt.opId)?.current ?? null
    await load()
    throw new Error('这条记录已有更新。请核对当前版本后再操作。')
  }
  editor.value = false
  await load()
  message.value = deleted ? '已删除记录。' : '已保存到本机。'
}
function save() {
  if (!current.value) return
  return run(() => write(editKind.value, editData(), target.value))
}
function remove(record: LocalRecord) {
  if (!current.value || busy.value || !window.confirm(`删除「${rowName(record)}」？`)) return
  return run(() => write(record.kind, record.data, record, true))
}
function issuePairing() {
  if (!current.value || status.value?.paired) return
  return run(async () => {
    const { qr } = await localWorkspaceApi.createPairing()
    clearInvitation()
    qrUrl.value = await QRCode.toDataURL(JSON.stringify(qr), { width: 240, margin: 2, errorCorrectionLevel: 'M' })
    invitationTimer = setTimeout(clearInvitation, 300_000)
    await load()
  })
}
function unlink() {
  if (busy.value || (!status.value?.paired && !qrUrl.value)) return
  if (status.value?.paired && !window.confirm('停止与手机同步？两端已保存的数据会保留。')) return
  return run(async () => {
    await localWorkspaceApi.removePairing()
    clearInvitation()
    await load()
    message.value = '已关闭本地绑定。'
  })
}
function restore(archive: LocalArchive) {
  if (!current.value || busy.value || status.value?.paired || !window.confirm('切换到这份本地归档？当前工作区会归档。')) return
  return run(async () => {
    await localWorkspaceApi.restore(archive.archive_id, workspaceId.value)
    await load()
    message.value = '已切换到此归档。'
  })
}
</script>

<template>
  <main class="local-workspace">
    <header class="workspace-header">
      <div>
        <h1>本地工作区</h1>
        <p>业务数据保存在本机。同一局域网内可与已绑定手机同步。</p>
      </div>
      <div class="workspace-actions">
        <button type="button" class="btn btn-secondary" :disabled="busy" @click="refresh">刷新记录</button>
        <router-link :to="{ name: 'chat' }" class="btn btn-secondary">返回在线工作台</router-link>
      </div>
    </header>
    <p v-if="error" class="workspace-error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>

    <div class="workspace-layout">
      <section class="workspace-card" aria-label="本地业务记录" :aria-busy="busy">
        <div class="workspace-actions workspace-toolbar">
          <nav class="workspace-actions" aria-label="业务类别">
            <button v-for="(label, value) in kindLabels" :key="value" type="button"
              :aria-pressed="kind === value" :class="kind === value ? 'btn btn-primary' : 'btn btn-secondary'"
              :disabled="busy || editor" @click="kind = value">
              {{ label }}
            </button>
          </nav>
          <button type="button" class="btn btn-primary" :disabled="busy || !current || editor" @click="openEditor()">
            新建{{ kindLabels[kind] }}
          </button>
        </div>
        <p v-if="!current && busy" role="status">正在读取本地记录…</p>
        <p v-else-if="current && !visible.length">暂无{{ kindLabels[kind] }}</p>
        <ul v-if="visible.length" class="workspace-records">
          <li v-for="record in visible" :key="record.id">
            <div><strong>{{ rowName(record) }}</strong><small>{{ recordSummary(record) }}</small></div>
            <div class="workspace-actions">
              <button type="button" class="btn btn-secondary" :disabled="busy || !current || editor" :aria-label="'编辑 ' + rowName(record)" @click="openEditor(record)">编辑</button>
              <button type="button" class="btn btn-secondary" :disabled="busy || !current || editor" :aria-label="'删除 ' + rowName(record)" @click="remove(record)">删除</button>
            </div>
          </li>
        </ul>
        <form v-if="editor" class="workspace-editor" @submit.prevent="save">
          <h2>{{ target ? '编辑' : '新建' }}{{ kindLabels[editKind] }}</h2>
          <fieldset class="workspace-fields" :disabled="busy || !current">
            <label>名称<input v-model="form.name" type="text" required maxlength="200" /></label>
            <template v-if="editKind === 'customer'">
              <label>联系人<input v-model="form.contact" type="text" maxlength="200" /></label>
              <label>电话<input v-model="form.phone" type="tel" maxlength="100" /></label>
            </template>
            <template v-else-if="editKind === 'product'">
              <label>型号<input v-model="form.sku" type="text" maxlength="100" /></label>
              <label>单价<input v-model="form.unitPrice" type="number" min="0" step="0.01" /></label>
            </template>
            <template v-else>
              <label>客户
                <select v-model="form.customerId">
                  <option value="">选择客户</option>
                  <option v-if="form.customerId && !customers.some(record => record.id === form.customerId)" :value="form.customerId">{{ text(target?.data.customer) || '原客户' }}</option>
                  <option v-for="record in customers" :key="record.id" :value="record.id">{{ rowName(record) }}</option>
                </select>
              </label>
              <div v-for="(item, index) in items" :key="index" class="workspace-line">
                <label>商品 {{ index + 1 }}
                  <select v-model="item.productId" required @change="setProductPrice(item)">
                    <option value="">选择商品</option>
                    <option v-if="item.productId && !products.some(record => record.id === item.productId)" :value="item.productId">{{ text(item.original.product_name) || '原商品' }}</option>
                    <option v-for="record in products" :key="record.id" :value="record.id">{{ rowName(record) }}</option>
                  </select>
                </label>
                <label>数量<input v-model="item.quantity" type="number" min="0.01" step="0.01" required /></label>
                <label>单价<input v-model="item.unitPrice" type="number" min="0" step="0.01" /></label>
                <button type="button" class="btn btn-secondary" @click="items.splice(index, 1)">移除此行</button>
              </div>
              <button type="button" class="btn btn-secondary" @click="addItem">添加商品行</button>
            </template>
            <label>备注<textarea v-model="form.notes" rows="3" maxlength="2000"></textarea></label>
          </fieldset>
          <div class="workspace-actions">
            <button type="submit" class="btn btn-primary" :disabled="busy || !current">保存到本机</button>
            <button type="button" class="btn btn-secondary" :disabled="busy" @click="editor = false">取消</button>
            <button v-if="conflict && !conflict.deleted" type="button" class="btn btn-secondary" :disabled="busy" @click="openEditor(conflict)">读取当前版本</button>
          </div>
        </form>
      </section>

      <aside class="workspace-card" aria-label="设备和本地归档">
        <h2>绑定手机</h2>
        <p v-if="status">{{ status.paired ? '已启用局域网绑定' : '尚未绑定设备' }}</p>
        <img v-if="qrUrl" :src="qrUrl" alt="手机本地工作区绑定二维码" width="240" height="240" />
        <p v-if="qrUrl">请用手机本地工作区扫码并选择起始数据，二维码 5 分钟内有效。</p>
        <button v-if="status && !status.paired" type="button" class="btn btn-primary" :disabled="busy || !current" @click="issuePairing">{{ qrUrl ? '更新绑定二维码' : '生成绑定二维码' }}</button>
        <button v-if="status?.paired || qrUrl" type="button" class="btn btn-secondary" :disabled="busy" @click="unlink">{{ status?.paired ? '解除绑定' : '取消二维码' }}</button>
        <template v-if="status && archiveTotal">
          <h2>本地归档</h2>
          <p v-if="status.paired">解除设备绑定后可恢复归档。</p>
          <ul class="workspace-records">
            <li v-for="archive in archives" :key="archive.archive_id">
              <div><strong>{{ archive.record_count }} 条记录</strong><small>{{ archiveDate(archive.created_at) }}</small></div>
              <button type="button" class="btn btn-secondary" :disabled="busy || !current || status.paired || editor" @click="restore(archive)">恢复</button>
            </li>
          </ul>
          <nav class="workspace-actions" aria-label="归档分页">
            <button type="button" class="btn btn-secondary" :disabled="busy || archiveOffset === 0" @click="loadArchivePage(archiveOffset - archivePageSize)">较新归档</button>
            <span>第 {{ archiveOffset + 1 }}–{{ archiveOffset + archives.length }} 条，共 {{ archiveTotal }} 条</span>
            <button type="button" class="btn btn-secondary" :disabled="busy || archiveOffset + archives.length >= archiveTotal" @click="loadArchivePage(archiveOffset + archivePageSize)">更早归档</button>
          </nav>
        </template>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.local-workspace { background: var(--xc-color-page-bg); color: var(--xc-color-text); box-sizing: border-box; padding: clamp(16px, 4vw, 54px); overflow: auto; }
.workspace-header, .workspace-toolbar, .workspace-records li { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.workspace-header h1 { margin: 0; }
.workspace-header p { margin: 8px 0; color: var(--xc-color-text-secondary); }
.workspace-layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(220px, 1fr); gap: 16px; margin-top: 18px; }
.workspace-card { border: 1px solid var(--xc-color-border); border-radius: 12px; background: var(--xc-color-surface); padding: 16px; }
.workspace-card h2 { font-size: var(--xc-font-xl); margin: 0 0 12px; }
.workspace-card button, .workspace-card input, .workspace-card select { min-height: 36px; }
.workspace-card img { max-width: 100%; height: auto; border-radius: 8px; }
.workspace-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.workspace-actions .btn { text-decoration: none; }
.workspace-records { list-style: none; margin: 12px 0; padding: 0; }
.workspace-records li { border-block-start: 1px solid var(--xc-color-border); padding: 10px 0; overflow-wrap: anywhere; }
.workspace-records small { display: block; color: var(--xc-color-text-secondary); }
.workspace-editor { border-block-start: 1px solid var(--xc-color-border); margin-top: 16px; padding-top: 16px; }
.workspace-fields { display: grid; gap: 10px; min-width: 0; border: 0; padding: 0; margin: 0 0 12px; }
.workspace-fields label { display: grid; gap: 4px; min-width: 0; }
.workspace-fields input, .workspace-fields select, .workspace-fields textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--xc-color-border-strong); border-radius: 6px; padding: 7px; background: var(--xc-color-surface); color: inherit; }
.workspace-line { display: flex; align-items: end; gap: 8px; flex-wrap: wrap; }
.workspace-line label { flex: 1 1 90px; }
.workspace-error { color: var(--xc-color-danger); }
.workspace-card h2:not(:first-child) { margin-top: 20px; }
@media (max-width: 680px) { .workspace-layout { grid-template-columns: minmax(0, 1fr); } }
</style>
