<template>
  <section class="enterprise-roster" aria-label="购买账户标准交付台账">
    <header class="enterprise-roster__head">
      <div>
        <p>{{ isTrial ? 'TRIAL ACCOUNT DELIVERY SSOT' : 'PURCHASED ACCOUNT DELIVERY SSOT' }}</p>
        <h3>{{ isTrial ? '¥99 体验账户交付台账' : '购买账户标准交付台账' }}</h3>
        <span>
          {{
            isTrial
              ? '只读取 ¥99 体验（saas-trial-30）的有效账户；内部本 Mac 不计交付，仅客户侧安装并首次登录后自动完成。'
              : '内部本 Mac 不计交付；仅客户侧 macOS/Windows 安装并首次登录后自动完成。'
          }}
        </span>
      </div>
      <div class="enterprise-roster__policy">
        <strong>{{ deliveries.length }} 个{{ isTrial ? '体验账户' : '永久账户' }}</strong>
        <span :class="{ 'is-enabled': policy.internal_device_exclusion_enabled }">
          {{ policy.internal_device_exclusion_enabled
            ? `${policy.internal_device_ids_configured || 0} 台内部本机已排除`
            : '内部本机尚未登记' }}
        </span>
      </div>
    </header>

    <div class="enterprise-roster__toolbar">
      <label>
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model.trim="query" type="search" placeholder="搜索账户、交付单、订单、档位或安装版本" />
      </label>
      <select v-model="status" aria-label="按标准交付状态筛选">
        <option value="">全部状态</option>
        <option value="pending_install">待安装</option>
        <option value="pending_first_login">待首次登录</option>
        <option value="completed">已自动完成</option>
      </select>
      <span>显示 {{ rows.length }} / {{ deliveries.length }} 项</span>
    </div>

    <div v-if="!rows.length" class="enterprise-roster__empty">
      {{ deliveries.length ? '没有符合筛选条件的标准交付' : isTrial ? '尚无有效的体验账户' : '尚无有效的永久购买账户' }}
    </div>

    <div v-else class="enterprise-roster__grid">
      <article v-for="delivery in rows" :key="delivery.delivery_no" :class="`is-${delivery.status}`">
        <span class="enterprise-roster__avatar">{{ accountName(delivery).slice(0, 1).toUpperCase() }}</span>
        <div class="enterprise-roster__identity">
          <strong>{{ accountName(delivery) }}</strong>
          <span>{{ delivery.account.email || `账号：${delivery.account.username}` }}</span>
          <code>{{ delivery.delivery_no }}</code>
        </div>
        <div class="enterprise-roster__plan">
          <strong>{{ delivery.plan.title }}</strong>
          <span>{{ tierLabel(delivery.plan.account_tier) }} · {{ isTrial ? '30 天体验' : '永久授权' }}</span>
          <small v-if="isTrial && delivery.expires_at">到期 {{ formatDate(delivery.expires_at) }}</small>
          <small v-if="delivery.order?.order_no">订单 {{ delivery.order.order_no }}</small>
        </div>
        <div class="enterprise-roster__proof">
          <span :class="['proof-pill', delivery.install.ok ? 'is-ok' : 'is-wait']">
            <i :class="`fa ${delivery.install.ok ? 'fa-check-circle' : 'fa-download'}`" aria-hidden="true"></i>
            {{ delivery.install.ok ? `${delivery.install.installed_devices} 台客户设备已安装` : '待客户设备安装' }}
          </span>
          <span
            v-if="delivery.install.ok"
            :class="['proof-pill', installedVersion(delivery) ? 'is-version' : 'is-version-unknown']"
            :title="installedVersionDetail(delivery)"
          >
            <i class="fa fa-code-fork" aria-hidden="true"></i>
            {{ installedVersion(delivery) ? `当前版本 ${installedVersion(delivery)}` : '当前版本未上报' }}
            <small v-if="installedPlatform(delivery)">· {{ installedPlatform(delivery) }}</small>
          </span>
          <span v-if="delivery.install.internal_devices_excluded" class="proof-pill is-internal">
            <i class="fa fa-shield" aria-hidden="true"></i>
            {{ delivery.install.internal_devices_excluded }} 台内部本机已排除
          </span>
          <span :class="['proof-pill', delivery.first_login.ok ? 'is-ok' : 'is-wait']">
            <i :class="`fa ${delivery.first_login.ok ? 'fa-check-circle' : 'fa-sign-in'}`" aria-hidden="true"></i>
            {{ delivery.first_login.ok ? '首次登录成功' : '待首次登录' }}
          </span>
        </div>
        <div class="enterprise-roster__state">
          <strong :class="`delivery-state is-${delivery.status}`">{{ delivery.status_label }}</strong>
          <small v-if="delivery.completed_at">{{ formatDate(delivery.completed_at) }}</small>
          <button v-if="ticketCount(delivery)" type="button" @click="emit('open-custom', delivery.account)">
            查看 {{ ticketCount(delivery) }} 个定制工单
          </button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  CustomDeliveryTicket,
  MarketAdminUser,
  StandardDeliveryPolicy,
  StandardDeliveryRecord,
  UpdateInstallReceipt,
} from '@/api/xcmaxAdmin'

const props = withDefaults(
  defineProps<{
    deliveries: StandardDeliveryRecord[]
    tickets: CustomDeliveryTicket[]
    policy: StandardDeliveryPolicy
    variant?: 'permanent' | 'trial'
  }>(),
  { variant: 'permanent' },
)

const isTrial = computed(() => props.variant === 'trial')

const emit = defineEmits<{
  (event: 'open-custom', user: MarketAdminUser): void
}>()

const query = ref('')
const status = ref('')

const ticketCounts = computed(() => {
  const counts = new Map<number, number>()
  for (const ticket of props.tickets) {
    const userId = Number(ticket.user_id)
    if (Number.isFinite(userId)) counts.set(userId, (counts.get(userId) || 0) + 1)
  }
  return counts
})

const rows = computed(() => {
  const needle = query.value.toLowerCase()
  return props.deliveries.filter((delivery) => {
    if (status.value && delivery.status !== status.value) return false
    if (!needle) return true
    return [
      delivery.account.username,
      delivery.account.email,
      delivery.delivery_no,
      delivery.order?.order_no,
      delivery.plan.title,
      delivery.plan.account_tier,
      installedVersion(delivery),
      installedPlatform(delivery),
    ].some((value) => String(value || '').toLowerCase().includes(needle))
  })
})

function accountName(delivery: StandardDeliveryRecord): string {
  return String(delivery.account.company || delivery.account.username || `购买账户 #${delivery.account.id}`)
}

function tierLabel(tier: string): string {
  return ({ normal: 'Normal', pro: 'Pro', max: 'Max', ultra: 'Ultra' } as Record<string, string>)[tier] || tier
}

function ticketCount(delivery: StandardDeliveryRecord): number {
  return ticketCounts.value.get(Number(delivery.account.id)) || 0
}

function installedReceipt(delivery: StandardDeliveryRecord): UpdateInstallReceipt | null {
  if (delivery.install.latest_installed_receipt) return delivery.install.latest_installed_receipt
  const latest = delivery.install.latest_receipt
  return latest?.status === 'installed' && latest.device_scope !== 'internal' ? latest : null
}

function installedVersion(delivery: StandardDeliveryRecord): string {
  return String(installedReceipt(delivery)?.installed_version || '').trim()
}

function installedPlatform(delivery: StandardDeliveryRecord): string {
  const platform = String(installedReceipt(delivery)?.platform || '').trim().toLowerCase()
  if (platform === 'darwin' || platform === 'macos') return 'macOS'
  if (platform === 'win32' || platform === 'windows') return 'Windows'
  return platform
}

function installedVersionDetail(delivery: StandardDeliveryRecord): string {
  const receipt = installedReceipt(delivery)
  if (!receipt) return '客户设备已安装，但该安装回执未包含版本信息'
  const parts = [
    installedVersion(delivery) ? `安装版本 ${installedVersion(delivery)}` : '安装版本未上报',
    installedPlatform(delivery),
    receipt.installed_build_sha ? `构建 ${receipt.installed_build_sha}` : '',
    receipt.reported_at ? `上报 ${formatDate(receipt.reported_at)}` : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.enterprise-roster { margin-bottom: 18px; padding: 17px; border: 1px solid #cbddee; border-radius: 17px; background: rgba(255,255,255,.92); box-shadow: 0 10px 28px rgba(24,58,94,.06); }
.enterprise-roster__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.enterprise-roster__head p { margin: 0 0 4px; color: #3d78bc; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.enterprise-roster__head h3 { margin: 0; color: #254663; font-size: 18px; }
.enterprise-roster__head span { display: block; margin-top: 5px; color: #6e8097; font-size: 11px; }
.enterprise-roster__policy { display: grid; justify-items: end; gap: 6px; }
.enterprise-roster__policy > strong { border-radius: 999px; background: #e7f1fd; color: #276bb7; padding: 7px 11px; white-space: nowrap; }
.enterprise-roster__policy > span { border-radius: 999px; background: #fff1e8; color: #a85b25; padding: 5px 9px; font-size: 9px; font-weight: 700; white-space: nowrap; }
.enterprise-roster__policy > span.is-enabled { background: #e9f3ef; color: #27745a; }
.enterprise-roster__toolbar { display: flex; align-items: center; gap: 9px; margin: 14px 0; padding: 9px; border-radius: 11px; background: #f3f7fb; }
.enterprise-roster__toolbar label { display: flex; align-items: center; gap: 7px; flex: 1; min-width: 180px; color: #7690ac; }
.enterprise-roster__toolbar input { width: 100%; border: 0; outline: 0; background: transparent; color: #132a46; }
.enterprise-roster__toolbar select { border: 1px solid #cbdbea; border-radius: 8px; background: #fff; padding: 7px 9px; color: #34516f; }
.enterprise-roster__toolbar > span { color: #6e8097; font-size: 11px; white-space: nowrap; }
.enterprise-roster__grid { display: grid; gap: 8px; }
.enterprise-roster__grid article { display: grid; grid-template-columns: 38px minmax(150px,.9fr) minmax(165px,.75fr) minmax(220px,1fr) minmax(150px,.7fr); align-items: center; gap: 11px; padding: 12px; border: 1px solid #dce7f1; border-left: 3px solid #6a9fd6; border-radius: 11px; background: #fbfdff; }
.enterprise-roster__grid article.is-completed { border-left-color: #3b9b78; }
.enterprise-roster__grid article.is-pending-first-login { border-left-color: #8b69c8; }
.enterprise-roster__avatar { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: #e8f1fb; color: #3172b7; font-weight: 800; }
.enterprise-roster__identity strong,.enterprise-roster__identity span,.enterprise-roster__identity code,.enterprise-roster__plan strong,.enterprise-roster__plan span,.enterprise-roster__plan small { display: block; }
.enterprise-roster__identity strong,.enterprise-roster__plan strong { color: #294a68; font-size: 11px; }
.enterprise-roster__identity span,.enterprise-roster__plan span,.enterprise-roster__plan small { margin-top: 3px; color: #718399; font-size: 9px; }
.enterprise-roster__identity code { margin-top: 4px; color: #527291; font-size: 8px; overflow-wrap: anywhere; }
.enterprise-roster__proof { display: flex; flex-wrap: wrap; gap: 5px; }
.proof-pill { border-radius: 999px; padding: 5px 7px; font-size: 9px; white-space: nowrap; }
.proof-pill.is-ok { background: #e7f6ef; color: #28795c; }
.proof-pill.is-wait { background: #f2f4f7; color: #738195; }
.proof-pill.is-internal { background: #eef1f4; color: #53677d; }
.proof-pill.is-version { background: #e8f1fd; color: #2869aa; }
.proof-pill.is-version-unknown { background: #fff2df; color: #9a641d; }
.proof-pill small { font-size: inherit; }
.enterprise-roster__state { display: grid; justify-items: end; gap: 5px; text-align: right; }
.delivery-state { font-size: 10px; }
.delivery-state.is-completed { color: #28795c; }
.delivery-state.is-pending-install { color: #b26225; }
.delivery-state.is-pending-first-login { color: #6c50a7; }
.enterprise-roster__state small { color: #7a8b9c; font-size: 8px; }
.enterprise-roster__state button { border: 1px solid #d5a071; border-radius: 8px; background: #fff7ef; color: #a65d26; padding: 6px 8px; font-size: 9px; font-weight: 700; cursor: pointer; }
.enterprise-roster__empty { padding: 22px; border: 1px dashed #c7d8e8; border-radius: 11px; color: #718399; text-align: center; }
@media (max-width: 1100px) { .enterprise-roster__grid article { grid-template-columns: 38px 1fr 1fr; } .enterprise-roster__proof,.enterprise-roster__state { grid-column: 2 / -1; justify-items: start; text-align: left; } }
@media (max-width: 760px) { .enterprise-roster__toolbar { align-items: stretch; flex-direction: column; } .enterprise-roster__grid article { grid-template-columns: 38px 1fr; } .enterprise-roster__plan,.enterprise-roster__proof,.enterprise-roster__state { grid-column: 2; } }
</style>
