<template>
  <div class="page-view admin-business-customers-view">
    <div class="page-content">
      <header class="admin-business-customers-head">
        <div>
          <h2>业务对象</h2>
          <p class="muted">显示平台注册客户、企业客户与业务库客户，用于核对真实客户资产是否完整。</p>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="loadCustomers">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </header>

      <div v-if="errorMessage" class="admin-business-customers-alert" role="alert">
        {{ errorMessage }}
      </div>

      <section class="admin-business-customers-summary" aria-label="客户统计">
        <article>
          <span>平台客户</span>
          <strong>{{ platformCustomerCount }}</strong>
        </article>
        <article>
          <span>ERP 客户</span>
          <strong>{{ erpCustomerCount }}</strong>
        </article>
        <article>
          <span>企业账号</span>
          <strong>{{ enterpriseCustomerCount }}</strong>
        </article>
        <article>
          <span>VIP/SVIP</span>
          <strong>{{ vipCustomerCount }}</strong>
        </article>
      </section>

      <section class="admin-business-customers-toolbar" aria-label="客户筛选">
        <input
          v-model="searchText"
          type="search"
          class="admin-business-customers-search"
          placeholder="搜索客户名称 / 账号 / 邮箱 / 电话 / 行业 / VIP"
        />
        <span class="muted">共 {{ filteredCustomers.length }} / {{ customers.length }} 个业务对象</span>
      </section>

      <section class="admin-business-customers-table-wrap" aria-label="具体客户列表">
        <table class="admin-business-customers-table">
          <thead>
            <tr>
              <th>来源</th>
              <th>客户名称</th>
              <th>账号/联系人</th>
              <th>联系方式</th>
              <th>账号身份</th>
              <th>VIP体系</th>
              <th>企业档位</th>
              <th>行业/地址</th>
              <th>Mod/余额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !customers.length">
              <td colspan="9" class="admin-business-customers-empty">加载中...</td>
            </tr>
            <tr v-else-if="!filteredCustomers.length">
              <td colspan="9" class="admin-business-customers-empty">暂无客户数据</td>
            </tr>
            <template v-else>
              <tr v-for="customer in filteredCustomers" :key="customer.key">
                <td>
                  <span class="admin-business-source" :class="`admin-business-source--${customer.source}`">
                    {{ customer.sourceLabel }}
                  </span>
                </td>
                <td>
                  <strong>{{ customer.name }}</strong>
                  <small v-if="customer.id">ID {{ customer.id }}</small>
                </td>
                <td>{{ customer.accountText }}</td>
                <td>{{ customer.contactText }}</td>
                <td>{{ customer.identityLabel }}</td>
                <td>{{ customer.membershipLabel }}</td>
                <td>{{ customer.accountTierLabel }}</td>
                <td>{{ customer.industryText }}</td>
                <td>{{ customer.businessText }}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/core'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

type MarketCustomerRow = {
  id?: number | string
  user_id?: number
  username?: string
  name?: string
  company?: string
  company_name?: string
  email?: string
  phone?: string
  mobile?: string
  is_admin?: boolean
  is_enterprise?: boolean
  mod_ids?: string[]
  tier?: string
  industry_id?: string
  account_tier?: string
  budget_range?: string
  entitled_industries?: string[]
  market_membership_tier?: string
  membership_tier?: string
  plan_tier?: string
  membership?: { tier?: string; label?: string }
}

type LocalProfile = {
  tier?: string
  industry_id?: string
  account_tier?: string
  budget_range?: string
  entitled_industries?: string[]
}

type WalletRow = {
  user_id?: number
  balance?: number | string | null
}

type ErpCustomerRow = {
  id?: number | string
  name?: string
  customer_name?: string
  unit_name?: string
  contact_person?: string
  contact_phone?: string
  contact_address?: string
  address?: string
}

type BusinessCustomerRow = {
  key: string
  source: 'platform' | 'erp'
  sourceLabel: string
  id: string
  name: string
  accountText: string
  contactText: string
  identityLabel: string
  membershipLabel: string
  accountTierLabel: string
  industryText: string
  businessText: string
  searchText: string
}

type AnyObject = Record<string, unknown>

const customers = ref<BusinessCustomerRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
const searchText = ref('')

const ACCOUNT_TIER_LABELS: Record<string, string> = {
  normal: '普通',
  pro: 'Pro',
  max: 'Max',
  ultra: 'Ultra',
}

const MEMBERSHIP_TIER_LABELS: Record<string, string> = {
  free: 'Free',
  vip: 'VIP',
  vip_plus: 'VIP+',
  svip: 'SVIP',
  svip1: 'SVIP1',
  svip2: 'SVIP2',
  svip3: 'SVIP3',
  svip4: 'SVIP4',
  svip5: 'SVIP5',
  svip6: 'SVIP6',
  svip7: 'SVIP7',
  svip8: 'SVIP8',
}

const filteredCustomers = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return customers.value
  return customers.value.filter((customer) => customer.searchText.includes(q))
})

const platformCustomerCount = computed(() => customers.value.filter((customer) => customer.source === 'platform').length)
const erpCustomerCount = computed(() => customers.value.filter((customer) => customer.source === 'erp').length)
const enterpriseCustomerCount = computed(() => customers.value.filter((customer) => customer.identityLabel === '企业').length)
const vipCustomerCount = computed(() => customers.value.filter((customer) => !['-', 'Free'].includes(customer.membershipLabel)).length)

function unwrapArray<T>(body: unknown, keys: string[]): T[] {
  for (const key of keys) {
    const value = key.split('.').reduce<unknown>((acc, part) => {
      if (!acc || typeof acc !== 'object') return undefined
      return (acc as AnyObject)[part]
    }, body)
    if (Array.isArray(value)) return value as T[]
  }
  return []
}

function unwrapProfiles(body: unknown): Record<string, LocalProfile> {
  if (!body || typeof body !== 'object') return {}
  const data = (body as AnyObject).data
  return data && typeof data === 'object' && !Array.isArray(data) ? (data as Record<string, LocalProfile>) : {}
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

function formatIdentity(row: MarketCustomerRow): string {
  const tier = text(row.tier)
  if (tier === 'admin' || row.is_admin) return '管理员'
  if (tier === 'enterprise' || row.is_enterprise) return '企业'
  return '个人'
}

function formatMembership(row: MarketCustomerRow): string {
  const tier = text(row.membership?.label || row.market_membership_tier || row.membership_tier || row.plan_tier || row.membership?.tier)
  if (!tier) return '-'
  return MEMBERSHIP_TIER_LABELS[tier] || tier.toUpperCase()
}

function formatAccountTier(row: MarketCustomerRow): string {
  const tier = text(row.account_tier)
  if (!tier) return '-'
  return ACCOUNT_TIER_LABELS[tier] || tier
}

function formatBalance(row: WalletRow | undefined, walletQuerySucceeded = true): string {
  if (!walletQuerySucceeded) return '余额查询失败'
  const raw = row?.balance
  if (raw === null || raw === undefined || raw === '') return '余额 ¥0.00'
  const n = typeof raw === 'string' ? parseFloat(raw) : raw
  if (!Number.isFinite(n)) return '余额 -'
  return `余额 ¥${n.toFixed(2)}`
}

function buildSearchText(row: BusinessCustomerRow): string {
  return [
    row.sourceLabel,
    row.id,
    row.name,
    row.accountText,
    row.contactText,
    row.identityLabel,
    row.membershipLabel,
    row.accountTierLabel,
    row.industryText,
    row.businessText,
  ]
    .join(' ')
    .toLowerCase()
}

function normalizeMarketCustomers(
  rawRows: MarketCustomerRow[],
  profiles: Record<string, LocalProfile>,
  wallets: Map<number, WalletRow>,
  walletQuerySucceeded = true,
): BusinessCustomerRow[] {
  return rawRows.map((raw, index) => {
    const username = text(raw.username || raw.name)
    const profile = profiles[username] || {}
    const row: MarketCustomerRow = {
      ...raw,
      tier: raw.tier || profile.tier,
      industry_id: raw.industry_id || profile.industry_id,
      account_tier: raw.account_tier || profile.account_tier,
      budget_range: raw.budget_range || profile.budget_range,
      entitled_industries: raw.entitled_industries || profile.entitled_industries,
    }
    const numericId = typeof row.id === 'number' ? row.id : typeof row.user_id === 'number' ? row.user_id : undefined
    const wallet = numericId === undefined ? undefined : wallets.get(numericId)
    const company = text(row.company || row.company_name)
    const displayName = company || username || `客户 ${index + 1}`
    const contact = [row.email, row.phone || row.mobile].map(text).filter(Boolean).join(' / ') || '-'
    const modCount = Array.isArray(row.mod_ids) ? row.mod_ids.length : 0
    const keySeed = text(row.id ?? row.user_id) || username || String(index)
    const out: BusinessCustomerRow = {
      key: `platform:${keySeed}`,
      source: 'platform',
      sourceLabel: '平台客户',
      id: text(row.id ?? row.user_id),
      name: displayName,
      accountText: username || '-',
      contactText: contact,
      identityLabel: formatIdentity(row),
      membershipLabel: formatMembership(row),
      accountTierLabel: formatAccountTier(row),
      industryText: text(row.industry_id) || '通用',
      businessText: `${modCount} 个 Mod · ${formatBalance(wallet, walletQuerySucceeded)}`,
      searchText: '',
    }
    out.searchText = buildSearchText(out)
    return out
  })
}

function erpName(row: ErpCustomerRow): string {
  return text(row.name || row.customer_name || row.unit_name) || '-'
}

function normalizeErpCustomers(rawRows: ErpCustomerRow[]): BusinessCustomerRow[] {
  return rawRows.map((row, index) => {
    const name = erpName(row)
    const keySeed = text(row.id) || name || String(index)
    const out: BusinessCustomerRow = {
      key: `erp:${keySeed}`,
      source: 'erp',
      sourceLabel: 'ERP客户',
      id: text(row.id),
      name,
      accountText: text(row.contact_person) || '-',
      contactText: text(row.contact_phone) || '-',
      identityLabel: '-',
      membershipLabel: '-',
      accountTierLabel: '-',
      industryText: text(row.contact_address || row.address) || '-',
      businessText: '业务库客户',
      searchText: '',
    }
    out.searchText = buildSearchText(out)
    return out
  })
}

async function loadCustomers() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [usersRes, profilesRes, walletsRes, erpRes] = await Promise.allSettled([
      xcmaxAdminApi.listUsers(),
      xcmaxAdminApi.getUserProfiles(),
      xcmaxAdminApi.listWallets(500, 0),
      api.get('/api/customers/list', { page: 1, per_page: 1000 }),
    ])

    const errors: string[] = []
    const userRows = usersRes.status === 'fulfilled' ? unwrapArray<MarketCustomerRow>(usersRes.value, ['users', 'data.users', 'data']) : []
    if (usersRes.status === 'rejected') errors.push(`平台客户读取失败：${usersRes.reason}`)

    const profiles = profilesRes.status === 'fulfilled' ? unwrapProfiles(profilesRes.value) : {}
    if (profilesRes.status === 'rejected') errors.push(`账号档位读取失败：${profilesRes.reason}`)

    const walletRows = walletsRes.status === 'fulfilled' ? unwrapArray<WalletRow>(walletsRes.value, ['items', 'data.items', 'data']) : []
    if (walletsRes.status === 'rejected') errors.push(`钱包读取失败：${walletsRes.reason}`)
    const walletMap = new Map<number, WalletRow>()
    for (const wallet of walletRows) {
      if (typeof wallet?.user_id === 'number') walletMap.set(wallet.user_id, wallet)
    }

    const erpRows = erpRes.status === 'fulfilled' ? unwrapArray<ErpCustomerRow>(erpRes.value, ['data', 'customers', 'data.customers']) : []
    if (erpRes.status === 'rejected') errors.push(`ERP客户读取失败：${erpRes.reason}`)

    customers.value = [
      ...normalizeMarketCustomers(userRows, profiles, walletMap, walletsRes.status === 'fulfilled'),
      ...normalizeErpCustomers(erpRows),
    ]
    errorMessage.value = errors.join('；')
  } catch (e) {
    customers.value = []
    errorMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadCustomers()
})
</script>

<style scoped src="./AdminBusinessCustomersView.css"></style>
