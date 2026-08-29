<template>
  <main class="customer-deliveries">
    <header class="delivery-hero">
      <div>
        <p>ACCOUNT DELIVERY</p>
        <h1>我的交付</h1>
        <span>首次交付前的定制生产、测试和返工已包含在永久账户中；交付后新增需求将重新报价、付款后生产。</span>
      </div>
      <button type="button" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新进度' }}
      </button>
    </header>

    <section class="delivery-rules" aria-label="交付规则">
      <article>
        <strong>1</strong>
        <div><b>购买永久账户</b><span>企业启航版、企业成长版、集团协同版、企业旗舰版</span></div>
      </article>
      <article>
        <strong>2</strong>
        <div><b>首次定制交付内含</b><span>交付前的开发和返工不重新报价</span></div>
      </article>
      <article>
        <strong>3</strong>
        <div><b>客户本人验收安装</b><span>下载令牌与安装回执同步到交付中心</span></div>
      </article>
    </section>

    <div v-if="message" class="notice is-ok">{{ message }}</div>
    <div v-if="error" class="notice is-error">{{ error }}</div>

    <section class="create-card">
      <header>
        <div>
          <h2>提交定制交付</h2>
          <p>系统会自动判断是首次内含交付，还是交付后新增开发。</p>
        </div>
        <button type="button" class="toggle-button" @click="formOpen = !formOpen">{{ formOpen ? '收起' : '新建需求' }}</button>
      </header>
      <form v-if="formOpen" @submit.prevent="createDelivery">
        <label
          ><span>交付类型</span
          ><select v-model="form.kind">
            <option value="module">定制业务模块</option>
            <option value="employee">定制 AI 员工</option>
            <option value="bundle">Mod + AI 员工</option>
          </select></label
        >
        <label
          ><span>需求名称</span
          ><input v-model.trim="form.title" required minlength="2" maxlength="128" placeholder="例如：合同审核与风险复核"
        /></label>
        <label class="is-wide"
          ><span>需求说明</span
          ><textarea v-model.trim="form.requirements" required minlength="8" rows="4" placeholder="写清业务输入、处理步骤和希望的输出。" />
        </label>
        <label class="is-wide"
          ><span>验收标准</span
          ><textarea v-model.trim="form.acceptance_criteria" required minlength="4" rows="3" placeholder="写清可以判定通过或返工的标准。" />
        </label>
        <label><span>建议标识（可选）</span><input v-model.trim="form.suggested_id" maxlength="64" placeholder="contract-review" /></label>
        <button type="submit" class="primary" :disabled="creating">{{ creating ? '提交中…' : '提交到生产员工' }}</button>
      </form>
    </section>

    <section class="delivery-list" aria-label="我的定制交付工单">
      <div v-if="loading && !tickets.length" class="empty">正在读取交付证据…</div>
      <div v-else-if="!tickets.length" class="empty">暂无定制交付工单。</div>
      <article v-for="ticket in tickets" v-else :key="ticket.id" class="ticket-card">
        <header>
          <div>
            <div class="ticket-title">
              <h2>{{ ticket.custom_delivery?.title || ticket.title }}</h2>
              <span>{{ ticket.custom_delivery?.pricing_label }}</span>
            </div>
            <p>{{ ticket.ticket_no }} · {{ kindLabel(ticket.custom_delivery?.kind) }}</p>
          </div>
          <strong :class="`stage is-${ticket.custom_delivery?.stage || 'queued'}`">{{
            ticket.custom_delivery?.stage_label || ticket.custom_delivery?.stage
          }}</strong>
        </header>

        <div v-if="ticket.custom_delivery?.pricing_mode === 'post_delivery_addon'" class="commerce-strip">
          <b>交付后新增开发</b>
          <span v-if="ticket.custom_delivery?.crm?.quote?.amount"
            >报价 {{ money(ticket.custom_delivery.crm.quote.amount, ticket.custom_delivery.crm.quote.currency) }} ·
            {{ ticket.custom_delivery.crm.quote.quote_no || '待发送报价单' }}</span
          >
          <span v-else>{{ (ticket.custom_delivery?.commerce_blockers || []).join('、') || '待报价付款' }}</span>
          <small>真实支付订单确认后，生产员工才会自动开始。</small>
          <div v-if="canPay(ticket)" class="payment-actions">
            <a v-if="paymentStatusPath(ticket)" :href="paymentStatusPath(ticket)">查看当前支付单</a>
            <button type="button" class="primary" :disabled="busyPayment === ticket.id" @click="startPayment(ticket)">
              {{ busyPayment === ticket.id ? '正在创建支付单…' : ticket.custom_delivery?.crm?.payment?.reference ? '重新发起支付' : '支付已确认报价' }}
            </button>
          </div>
        </div>

        <dl>
          <div>
            <dt>需求</dt>
            <dd>{{ ticket.custom_delivery?.requirements }}</dd>
          </div>
          <div>
            <dt>验收标准</dt>
            <dd>{{ ticket.custom_delivery?.acceptance_criteria }}</dd>
          </div>
          <div>
            <dt>质量门</dt>
            <dd>{{ ticket.custom_delivery?.gate_message || '等待生产运行结果' }}</dd>
          </div>
        </dl>

        <section v-if="canDecide(ticket)" class="decision-box">
          <strong>请由购买账户本人验收</strong>
          <textarea v-model.trim="decisionNotes[ticket.id]" rows="2" placeholder="验收意见；如要返工，请至少写 4 个字。" />
          <div>
            <button type="button" class="ghost" :disabled="busyId === ticket.id" @click="decide(ticket, 'rework')">要求返工</button
            ><button type="button" class="primary" :disabled="busyId === ticket.id" @click="decide(ticket, 'accept')">本人确认验收</button>
          </div>
        </section>

        <section v-if="canInstall(ticket)" class="artifact-box">
          <header>
            <div><strong>下载并安装定制产物</strong><span>回执令牌仅在本次下载后签发，且只能使用一次。</span></div>
          </header>
          <div v-for="artifact in ticket.custom_delivery?.artifacts || []" :key="`${artifact.kind}:${artifact.id}`" class="artifact-row">
            <div>
              <b>{{ artifact.id }}</b
              ><span>{{ artifact.kind === 'employee' ? 'AI 员工包' : 'Mod 模块' }}</span>
            </div>
            <button
              type="button"
              class="ghost"
              :disabled="busyArtifact === artifactKey(ticket, artifact)"
              @click="downloadArtifact(ticket, artifact)"
            >
              下载产物
            </button>
            <input v-model.trim="installVersions[artifactKey(ticket, artifact)]" placeholder="已安装版本，例 1.0.0" />
            <button
              type="button"
              class="primary"
              :disabled="!downloadTokens[artifactKey(ticket, artifact)] || busyArtifact === artifactKey(ticket, artifact)"
              @click="confirmInstalled(ticket, artifact)"
            >
              确认桌面端已安装
            </button>
          </div>
        </section>

        <footer v-if="ticket.custom_delivery?.stage === 'delivered'">✓ 客户验收和全部安装回执已闭环</footer>
      </article>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import type { CustomerDeliveryArtifact, CustomerDeliveryTicket } from '../api/delivery'

const tickets = ref<CustomerDeliveryTicket[]>([])
const loading = ref(false)
const creating = ref(false)
const formOpen = ref(false)
const busyId = ref<number | null>(null)
const busyArtifact = ref('')
const busyPayment = ref<number | null>(null)
const message = ref('')
const error = ref('')
const decisionNotes = reactive<Record<number, string>>({})
const downloadTokens = reactive<Record<string, string>>({})
const installVersions = reactive<Record<string, string>>({})
const form = reactive({
  kind: 'bundle' as 'module' | 'employee' | 'bundle',
  title: '',
  requirements: '',
  acceptance_criteria: '',
  suggested_id: '',
})

function describeError(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await api.customerDeliveryList(50)
    tickets.value = result.items || []
    for (const ticket of tickets.value) {
      for (const artifact of ticket.custom_delivery?.artifacts || []) {
        const key = artifactKey(ticket, artifact)
        downloadTokens[key] = localStorage.getItem(`xcagi-delivery-token:${key}`) || ''
      }
    }
  } catch (value) {
    error.value = describeError(value)
  } finally {
    loading.value = false
  }
}

async function createDelivery() {
  creating.value = true
  error.value = ''
  message.value = ''
  try {
    const created = await api.customerDeliveryCreate({ ...form })
    message.value = created.custom_delivery?.pricing_label || '定制交付已提交'
    Object.assign(form, { kind: 'bundle', title: '', requirements: '', acceptance_criteria: '', suggested_id: '' })
    formOpen.value = false
    await load()
  } catch (value) {
    error.value = describeError(value)
  } finally {
    creating.value = false
  }
}

function canDecide(ticket: CustomerDeliveryTicket): boolean {
  const acceptance = String(ticket.custom_delivery?.acceptance_status || 'pending')
  return ticket.custom_delivery?.stage === 'acceptance' && ticket.custom_delivery?.gate_ok === true && acceptance !== 'accepted'
}

function canInstall(ticket: CustomerDeliveryTicket): boolean {
  return (
    ticket.custom_delivery?.acceptance_status === 'accepted' &&
    ticket.custom_delivery?.commerce_ready === true &&
    Boolean(ticket.custom_delivery?.artifacts?.length) &&
    ticket.custom_delivery?.stage !== 'delivered'
  )
}

function canPay(ticket: CustomerDeliveryTicket): boolean {
  return (
    ticket.custom_delivery?.pricing_mode === 'post_delivery_addon' &&
    ticket.custom_delivery?.crm?.quote?.status === 'accepted' &&
    ticket.custom_delivery?.crm?.payment?.status !== 'paid'
  )
}

function paymentStatusPath(ticket: CustomerDeliveryTicket): string {
  const payment = ticket.custom_delivery?.crm?.payment
  if (!payment?.reference) return ''
  return payment.checkout_path || `/market/checkout/${encodeURIComponent(payment.reference)}`
}

async function startPayment(ticket: CustomerDeliveryTicket) {
  busyPayment.value = ticket.id
  error.value = ''
  message.value = ''
  try {
    const checkout = await api.customerDeliveryCheckout(ticket.id, 'alipay')
    if (checkout.redirect_url) {
      window.location.assign(checkout.redirect_url)
      return
    }
    const target = checkout.checkout_path || `/market/checkout/${encodeURIComponent(checkout.order_id)}`
    window.location.assign(target)
  } catch (value) {
    error.value = describeError(value)
  } finally {
    busyPayment.value = null
  }
}

async function decide(ticket: CustomerDeliveryTicket, action: 'accept' | 'rework') {
  const note = decisionNotes[ticket.id] || (action === 'accept' ? '客户本人确认产物符合验收标准' : '')
  if (action === 'rework' && note.trim().length < 4) {
    error.value = '请填写至少 4 个字的返工意见'
    return
  }
  busyId.value = ticket.id
  error.value = ''
  try {
    await api.customerDeliveryDecision(ticket.id, action, note)
    message.value = action === 'accept' ? '客户验收已记录，请下载并安装产物' : '返工意见已送达生产员工'
    await load()
  } catch (value) {
    error.value = describeError(value)
  } finally {
    busyId.value = null
  }
}

function artifactKey(ticket: CustomerDeliveryTicket, artifact: CustomerDeliveryArtifact): string {
  return `${ticket.id}:${artifact.kind}:${artifact.id}`
}

async function downloadArtifact(ticket: CustomerDeliveryTicket, artifact: CustomerDeliveryArtifact) {
  const key = artifactKey(ticket, artifact)
  busyArtifact.value = key
  error.value = ''
  try {
    const result = await api.customerDeliveryDownload(ticket.id, artifact)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = result.filename
    anchor.click()
    URL.revokeObjectURL(url)
    downloadTokens[key] = result.receiptToken
    localStorage.setItem(`xcagi-delivery-token:${key}`, result.receiptToken)
    message.value = '产物已下载。请在 XCAGI 桌面端完成导入后再提交安装回执。'
  } catch (value) {
    error.value = describeError(value)
  } finally {
    busyArtifact.value = ''
  }
}

async function confirmInstalled(ticket: CustomerDeliveryTicket, artifact: CustomerDeliveryArtifact) {
  const key = artifactKey(ticket, artifact)
  const token = downloadTokens[key]
  if (!token) return
  busyArtifact.value = key
  error.value = ''
  try {
    await api.customerDeliveryInstalled(ticket.id, {
      artifact_kind: artifact.kind,
      artifact_id: artifact.id,
      installed_version: installVersions[key] || '',
      host: `XCAGI Desktop ${navigator.platform || ''}`.trim(),
      receipt_token: token,
    })
    localStorage.removeItem(`xcagi-delivery-token:${key}`)
    downloadTokens[key] = ''
    message.value = '安装回执已同步到客户交付中心'
    await load()
  } catch (value) {
    error.value = describeError(value)
  } finally {
    busyArtifact.value = ''
  }
}

function kindLabel(value?: string): string {
  return (
    ({ module: '定制业务模块', employee: '定制 AI 员工', bundle: 'Mod + AI 员工' } as Record<string, string>)[value || ''] || '定制交付'
  )
}

function money(amount?: number, currency?: string): string {
  return `${currency || 'CNY'} ${Number(amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
}

onMounted(() => void load())
</script>

<style scoped>
.customer-deliveries {
  min-height: 100vh;
  padding: 42px clamp(18px, 4vw, 56px) 72px;
  color: #21384d;
  background: linear-gradient(145deg, #f4f8fc, #eaf2f9 55%, #f9fbfd);
}
.delivery-hero,
.create-card > header,
.ticket-card > header,
.artifact-box > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}
.delivery-hero {
  max-width: 1180px;
  margin: 0 auto 18px;
}
.delivery-hero p {
  margin: 0;
  color: #4b82b6;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
}
.delivery-hero h1 {
  margin: 4px 0 7px;
  font-size: clamp(27px, 4vw, 40px);
}
.delivery-hero span {
  color: #647b90;
  line-height: 1.65;
}
button {
  border: 0;
  border-radius: 9px;
  padding: 9px 13px;
  cursor: pointer;
  font-weight: 700;
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.delivery-hero > button,
.toggle-button,
.ghost {
  border: 1px solid #bdd0e1;
  color: #35658e;
  background: #fff;
}
.primary {
  color: #fff;
  background: #2677bb;
}
.delivery-rules,
.create-card,
.delivery-list {
  max-width: 1180px;
  margin-right: auto;
  margin-left: auto;
}
.delivery-rules {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.delivery-rules article {
  display: flex;
  gap: 11px;
  padding: 14px;
  border: 1px solid #d5e2ed;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.86);
}
.delivery-rules article > strong {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 50%;
  color: #fff;
  background: #347db8;
}
.delivery-rules b,
.delivery-rules span {
  display: block;
}
.delivery-rules b {
  font-size: 12px;
}
.delivery-rules span {
  margin-top: 4px;
  color: #71869a;
  font-size: 10px;
  line-height: 1.5;
}
.notice {
  max-width: 1150px;
  margin: 0 auto 10px;
  padding: 10px 14px;
  border-radius: 9px;
  font-size: 12px;
}
.notice.is-ok {
  color: #1e7257;
  background: #e5f5ee;
}
.notice.is-error {
  color: #a33e3e;
  background: #fdeaea;
}
.create-card {
  margin-bottom: 14px;
  padding: 18px;
  border: 1px solid #d5e2ed;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 30px rgba(46, 83, 117, 0.06);
}
.create-card h2,
.ticket-card h2 {
  margin: 0;
  font-size: 17px;
}
.create-card header p {
  margin: 5px 0 0;
  color: #71869a;
  font-size: 11px;
}
.create-card form {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 16px;
  padding-top: 15px;
  border-top: 1px solid #e0e9f1;
}
label span {
  display: block;
  margin-bottom: 5px;
  color: #526b80;
  font-size: 11px;
  font-weight: 700;
}
input,
select,
textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #c9d8e5;
  border-radius: 9px;
  padding: 9px 10px;
  color: #243d53;
  background: #fff;
  font: inherit;
}
.is-wide {
  grid-column: 1/-1;
}
.create-card form > .primary {
  align-self: end;
}
.delivery-list {
  display: grid;
  gap: 12px;
}
.empty {
  padding: 40px;
  border: 1px dashed #bfd0df;
  border-radius: 13px;
  color: #75899b;
  text-align: center;
}
.ticket-card {
  overflow: hidden;
  padding: 18px;
  border: 1px solid #d4e1ec;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 30px rgba(46, 83, 117, 0.055);
}
.ticket-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.ticket-title span,
.stage {
  border-radius: 999px;
  padding: 5px 8px;
  font-size: 9px;
}
.ticket-title span {
  color: #82652a;
  background: #fff3d8;
}
.ticket-card > header p {
  margin: 5px 0 0;
  color: #71869a;
  font-size: 10px;
}
.stage {
  color: #315f87;
  background: #e8f1fa;
}
.stage.is-delivered {
  color: #26735a;
  background: #e4f5ed;
}
.stage.is-commerce {
  color: #9a6125;
  background: #fff0dc;
}
.commerce-strip {
  display: grid;
  gap: 3px;
  margin-top: 13px;
  padding: 12px;
  border-left: 3px solid #d58c3e;
  border-radius: 8px;
  color: #6f532c;
  background: #fff8ea;
}
.commerce-strip span,
.commerce-strip small {
  font-size: 10px;
}
.commerce-strip small {
  color: #8b7658;
}
.payment-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 7px;
}
.payment-actions a {
  color: #35658e;
  font-size: 10px;
  font-weight: 700;
}
dl {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 9px;
  margin: 14px 0 0;
}
dl > div {
  padding: 11px;
  border-radius: 9px;
  background: #f4f7fa;
}
dt {
  color: #688094;
  font-size: 9px;
  font-weight: 800;
}
dd {
  margin: 5px 0 0;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}
.decision-box,
.artifact-box {
  margin-top: 14px;
  padding: 13px;
  border: 1px solid #cdddea;
  border-radius: 11px;
  background: #f8fbfd;
}
.decision-box > strong,
.artifact-box strong,
.artifact-box span {
  display: block;
}
.decision-box textarea {
  margin: 9px 0;
}
.decision-box > div {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.artifact-box header span {
  margin-top: 3px;
  color: #71869a;
  font-size: 10px;
}
.artifact-row {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) auto minmax(150px, 0.6fr) auto;
  align-items: center;
  gap: 9px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #dbe6ee;
}
.artifact-row > div span {
  margin-top: 3px;
  color: #71869a;
  font-size: 9px;
}
.ticket-card > footer {
  margin: 14px -18px -18px;
  padding: 12px 18px;
  color: #237558;
  background: #e8f7f0;
  font-weight: 800;
}
@media (max-width: 820px) {
  .delivery-rules,
  dl {
    grid-template-columns: 1fr;
  }
  .create-card form {
    grid-template-columns: 1fr;
  }
  .is-wide {
    grid-column: auto;
  }
  .artifact-row {
    grid-template-columns: 1fr;
  }
  .delivery-hero,
  .create-card > header,
  .ticket-card > header {
    flex-direction: column;
  }
  .stage {
    align-self: flex-start;
  }
}
</style>
