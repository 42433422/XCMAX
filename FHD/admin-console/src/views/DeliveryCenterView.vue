<template>
  <div class="delivery-center page-content admin-screen" id="view-delivery-center">
    <header class="delivery-hero">
      <div>
        <h2>客户交付中心</h2>
      </div>
      <button type="button" class="delivery-refresh" :disabled="loading" @click="loadAll">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
        {{ loading ? '同步中…' : '同步交付状态' }}
      </button>
    </header>

    <section id="delivery-overview" class="delivery-stats" aria-label="交付统计">
      <article v-for="item in summaryCards" :key="item.key" :class="`is-${item.key}`"
        :role="item.link ? 'button' : undefined" :tabindex="item.link ? 0 : undefined"
        @click="item.link && router.push(item.link)" @keydown.enter="item.link && router.push(item.link)">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </article>
    </section>
    <nav class="delivery-tabs" aria-label="交付分类">
      <button v-for="item in deliveryTabs" :key="item.key" type="button"
        :aria-pressed="activeTab === item.key" @click="activeTab = item.key">
        {{ item.label }} <span v-if="item.count !== undefined">{{ dataKnown && !errorMessage ? item.count : '—' }}</span>
      </button>
    </nav>
    <div class="admin-pane" tabindex="0" aria-label="交付内容">
    <KeepAlive><MacControlPanel v-if="activeTab === 'devices'" /></KeepAlive>
    <div v-show="activeTab !== 'devices'">
    <EnterpriseCustomerRoster id="delivery-enterprise-roster" v-show="activeTab === 'enterprise'"
      v-if="!errorMessage && (!loading || enterpriseUsers.length)"
      :users="enterpriseUsers"
      :tickets="tickets"
      :permanent-deliveries="standardDeliveries"
      :trial-deliveries="trialDeliveries"
      @open-custom="openCustomTickets"
    />

    <EnterpriseDeliveryRoster id="delivery-standard-roster" v-show="activeTab === 'standard'"
      v-if="!errorMessage && (!loading || standardDeliveries.length)"
      :deliveries="standardDeliveries"
      :tickets="tickets"
      :policy="standardPolicy"
      @open-custom="openCustomTickets"
    />

    <EnterpriseDeliveryRoster id="delivery-trial-roster" v-show="activeTab === 'trial'"
      v-if="!errorMessage && (!loading || trialDeliveries.length)"
      variant="trial"
      :deliveries="trialDeliveries"
      :tickets="tickets"
      :policy="trialPolicy"
      @open-custom="openCustomTickets"
    />

    <div v-if="errorMessage" class="delivery-alert" role="alert">
      <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
      <div>
        <strong>交付数据暂时无法读取</strong>
        <p>{{ errorMessage }}</p>
      </div>
      <button type="button" @click="loadAll">重试</button>
    </div>

    <div v-else-if="loading && !tickets.length && !enterpriseUsers.length && !standardDeliveries.length" class="delivery-empty">
      <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
      <strong>正在同步</strong>
    </div>
    </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import MacControlPanel from '../components/admin/MacControlPanel.vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import EnterpriseCustomerRoster from '../components/admin/EnterpriseCustomerRoster.vue'
import EnterpriseDeliveryRoster from '../components/admin/EnterpriseDeliveryRoster.vue'
import {
  xcmaxAdminApi,
  type CustomDeliveryTicket,
  type MarketAdminUser,
  type StandardDeliveryPolicy,
  type StandardDeliveryRecord,
} from '@/api/xcmaxAdmin'
import { fetchAllEnterpriseUsers } from '../utils/deliveryEnterpriseRoster'

const router = useRouter()
const tickets = ref<CustomDeliveryTicket[]>([])
const enterpriseUsers = ref<MarketAdminUser[]>([])
const standardDeliveries = ref<StandardDeliveryRecord[]>([])
const trialDeliveries = ref<StandardDeliveryRecord[]>([])
const standardPolicy = ref<StandardDeliveryPolicy>({})
const trialPolicy = ref<StandardDeliveryPolicy>({})
const activeTab = ref('standard')
const dataKnown = ref(false)
const deliveryTabs = computed(() => [
  { key: 'standard', label: '购买交付', count: standardDeliveries.value.length },
  { key: 'trial', label: '体验交付', count: trialDeliveries.value.length },
  { key: 'enterprise', label: '企业客户', count: enterpriseUsers.value.length },
  { key: 'devices', label: 'Mac 设备' },
])
const loading = ref(false)
const errorMessage = ref('')

type SummaryCard = { key: string; label: string; value: number | string; link?: { name: string; query: Record<string, string> } }
const summaryCards = computed<SummaryCard[]>(() => {
  const value = (count: number) => dataKnown.value && !errorMessage.value ? count : '—'
  return [
    { key: 'standard', label: '购买待安装', value: value(standardDeliveries.value.filter(row => row.status === 'pending_install').length) },
    { key: 'receipt', label: '购买待首次登录', value: value(standardDeliveries.value.filter(row => row.status === 'pending_first_login').length) },
    { key: 'custom', label: '定制待验收', value: value(tickets.value.filter(ticket => String(ticket.custom_delivery?.stage || '') === 'acceptance').length), link: { name: 'customer-service-tickets', query: { type: 'delivery' } } },
    { key: 'done', label: '购买交付完成', value: value(standardDeliveries.value.filter(row => row.status === 'completed').length) },
  ]
})

function extractTickets(raw: unknown): CustomDeliveryTicket[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.items) ? body.items : Array.isArray(nested.items) ? nested.items : []
  return rows as CustomDeliveryTicket[]
}

function extractStandardDeliveries(raw: unknown): StandardDeliveryRecord[] {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const rows = Array.isArray(body.items) ? body.items : Array.isArray(nested.items) ? nested.items : []
  return rows as StandardDeliveryRecord[]
}

function extractStandardPolicy(raw: unknown): StandardDeliveryPolicy {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const nested = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {}
  const policy = body.policy && typeof body.policy === 'object'
    ? body.policy
    : nested.policy && typeof nested.policy === 'object' ? nested.policy : {}
  return policy as StandardDeliveryPolicy
}

async function loadAll() {
  if (loading.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const [deliveryResult, enterpriseAccounts, standardResult, trialResult] = await Promise.all([
      xcmaxAdminApi.listCustomDeliveries(100),
      fetchAllEnterpriseUsers(),
      xcmaxAdminApi.listStandardDeliveries(),
      xcmaxAdminApi.listTrialDeliveries(),
    ])
    dataKnown.value = true
    tickets.value = extractTickets(deliveryResult)
    enterpriseUsers.value = enterpriseAccounts
    standardDeliveries.value = extractStandardDeliveries(standardResult)
    trialDeliveries.value = extractStandardDeliveries(trialResult)
    standardPolicy.value = extractStandardPolicy(standardResult)
    trialPolicy.value = extractStandardPolicy(trialResult)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

function openCustomTickets(user: MarketAdminUser) {
  void router.push({
    name: 'customer-service-tickets',
    query: { account_id: String(user.id), type: 'delivery' },
  })
}

onMounted(loadAll)
</script>

<style scoped src="./DeliveryCenterView.css"></style>
