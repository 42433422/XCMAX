<template>
  <div class="store-page">
    <header class="store-top">
      <div class="store-top__brand">
        <p class="store-eyebrow">XC AGI · AI 市场</p>
        <h1 class="store-title">选购 AI 员工与数字素材</h1>
      </div>
      <form class="store-search" @submit.prevent="applyFilters">
        <label class="sr-only" for="store-search">搜索</label>
        <input
          id="store-search"
          v-model="searchQ"
          class="input store-search__input"
          type="search"
          placeholder="搜索名称、包名…"
        />
        <button type="submit" class="btn btn-ghost">搜索</button>
      </form>
    </header>

    <div v-if="err" class="flash flash-err">{{ err }}</div>
    <div v-if="attachModId" class="flash flash-ok store-attach-banner" role="status">
      正在为 Mod <code class="mono">{{ attachModId }}</code> 选择 AI 员工包。选好后点「添加到 Mod」即可返回制作页。
    </div>

    <div class="store-shell">
      <aside class="store-sidebar" aria-label="分类与筛选">
        <nav class="store-nav" aria-label="商品分类">
          <button
            v-for="tab in storeNavTabsDisplay"
            :key="tab.id"
            type="button"
            class="store-nav__item"
            :class="{ active: storeNav === tab.id }"
            @click="setStoreNav(tab.id)"
          >
            <EmployeePackTypeIcon v-if="tab.icon" :kind="tab.icon" class="store-nav__icon" />
            <span class="store-nav__label">{{ tab.label }}</span>
            <span v-if="tab.badge" class="store-nav__badge">{{ tab.badge }}</span>
          </button>
        </nav>

        <div v-if="storeNav === 'office_aux'" class="office-spotlight office-aux-spotlight">
          <p class="office-spotlight__text">
            {{ OFFICE_AUX_PACK_1_PKG_IDS.length }} 个附属扩展：JSON 量化报告员 + 柱状/折线/饼图/看板可视化员，供报告与小猫分析图表（上架后显示）。
          </p>
        </div>

        <div v-if="storeNav === 'office'" class="office-spotlight">
          <p class="office-spotlight__text">
            {{ OFFICE_EMPLOYEE_PKG_IDS.length }} 个员工：Excel/CSV/PDF/PPT/Word 读+写，真实解析文件供 LLM 继续处理。
          </p>
          <button
            type="button"
            class="btn btn-primary btn-block"
            :disabled="bundleDownloading"
            @click="downloadOfficeBundle"
          >
            {{ bundleDownloading ? '打包中…' : '一键下载合集' }}
          </button>
        </div>

        <div v-if="storeNav === 'host_foundation'" class="office-spotlight host-foundation-spotlight">
          <p class="office-spotlight__text">
            1 个预装员工包：安装后自动写入对话/ERP/审批/客服等 bridge，无需在商店逐项安装基础设施 Mod。
          </p>
          <button
            type="button"
            class="btn btn-primary btn-block"
            :disabled="bundleDownloading"
            @click="downloadHostFoundationPack"
          >
            {{ bundleDownloading ? '下载中…' : '下载宿主基础员工包' }}
          </button>
        </div>

        <div v-if="storeNav === 'workflow'" class="office-spotlight workflow-spotlight">
          <p class="office-spotlight__text">6 个工作流员工 Mod：微信/电话/出货/标签等，一键打包下载到本地或 FHD/mods。</p>
          <button
            type="button"
            class="btn btn-primary btn-block"
            :disabled="bundleDownloading"
            @click="downloadWorkflowBundle"
          >
            {{ bundleDownloading ? '打包中…' : '一键下载合集' }}
          </button>
        </div>

        <button
          type="button"
          class="store-adv-toggle"
          :aria-expanded="showAdvancedFilters"
          @click="showAdvancedFilters = !showAdvancedFilters"
        >
          <span>高级筛选</span>
          <span v-if="advancedFilterCount" class="store-adv-toggle__count">{{ advancedFilterCount }}</span>
          <span class="store-adv-toggle__chev" :class="{ open: showAdvancedFilters }">›</span>
        </button>

        <div v-show="showAdvancedFilters" class="store-adv-filters">
          <div
            v-if="!isPackCollectionNav"
            class="filter-block"
          >
            <span class="filter-label">类目</span>
            <div class="chip-row">
              <button type="button" class="chip" :class="{ active: !filters.materialCategory }" @click="setMaterialCategory('')">全部</button>
              <button
                v-for="cat in facetMaterialCategories"
                :key="'cat-' + cat"
                type="button"
                class="chip"
                :class="{ active: filters.materialCategory === cat }"
                @click="setMaterialCategory(cat)"
              >
                {{ materialCategoryLabel(cat) }}
              </button>
            </div>
          </div>
          <div
            v-if="!isPackCollectionNav"
            class="filter-block"
          >
            <span class="filter-label">工件类型</span>
            <div class="chip-row">
              <button type="button" class="chip" :class="{ active: !filters.artifact }" @click="setArtifact('')">全部</button>
              <button
                v-for="art in facetArtifacts"
                :key="'art-' + art"
                type="button"
                class="chip"
                :class="{ active: filters.artifact === art }"
                @click="setArtifact(art)"
              >
                {{ artifactLabel(art) }}
              </button>
            </div>
          </div>
          <div class="filter-block">
            <span class="filter-label">行业</span>
            <div class="chip-row">
              <button type="button" class="chip" :class="{ active: !filters.industry }" @click="setIndustry('')">全部</button>
              <button
                v-for="ind in facetIndustries"
                :key="'ind-' + ind"
                type="button"
                class="chip"
                :class="{ active: filters.industry === ind }"
                @click="setIndustry(ind)"
              >
                {{ ind }}
              </button>
            </div>
          </div>
          <div class="filter-block">
            <span class="filter-label">授权</span>
            <div class="chip-row">
              <button type="button" class="chip" :class="{ active: !filters.licenseScope }" @click="setLicenseScope('')">全部</button>
              <button
                v-for="scope in facetLicenseScopes"
                :key="'lic-' + scope"
                type="button"
                class="chip"
                :class="{ active: filters.licenseScope === scope }"
                @click="setLicenseScope(scope)"
              >
                {{ licenseScopeLabel(scope) }}
              </button>
            </div>
          </div>
          <div class="filter-block">
            <span class="filter-label">保密级</span>
            <div class="chip-row">
              <button type="button" class="chip" :class="{ active: !filters.securityLevel }" @click="setSecurityLevel('')">全部</button>
              <button type="button" class="chip" :class="{ active: filters.securityLevel === 'personal' }" @click="setSecurityLevel('personal')">个人</button>
              <button type="button" class="chip" :class="{ active: filters.securityLevel === 'enterprise' }" @click="setSecurityLevel('enterprise')">企业</button>
              <button type="button" class="chip" :class="{ active: filters.securityLevel === 'confidential' }" @click="setSecurityLevel('confidential')">保密</button>
            </div>
          </div>
          <button v-if="advancedFilterCount || appliedQ" type="button" class="btn btn-text btn-block" @click="resetFilters">清除筛选</button>
        </div>
      </aside>

      <main class="store-main" aria-labelledby="store-results-heading">
        <div class="store-main__bar">
          <div>
            <h2 id="store-results-heading" class="store-main__title">{{ mainListTitle }}</h2>
            <p v-if="!loading" class="store-main__meta">共 {{ total }} 件 · 展示 {{ items.length }} 件</p>
          </div>
        </div>

        <div v-if="loading" class="state-msg">加载中…</div>
        <div v-else-if="!items.length" class="state-msg muted">
          <template v-if="storeNav === 'office_aux'">暂无商品。JSON 量化报告员与 chart-* 可视化员上架后将显示在此。</template>
          <template v-else>暂无商品，可切换左侧分类或调整筛选。</template>
        </div>

        <template v-else>
          <section
            v-for="group in displayGroups"
            :key="group.key"
            class="store-group"
            :class="{ 'store-group--flat': !group.title }"
          >
            <header v-if="group.title" class="store-group__hd">
              <EmployeePackTypeIcon :kind="group.kind" />
              <h3 class="store-group__title">{{ group.title }}</h3>
              <span class="store-group__count">{{ group.items.length }} 个</span>
            </header>
            <div class="store-grid">
              <article v-for="item in group.items" :key="item.id" class="store-card">
                <header class="store-card__head">
                  <EmployeePackTypeIcon :pkg-id="item.pkg_id" class="store-card__avatar" />
                  <div class="store-card__titles">
                    <div class="store-card__title-line">
                      <h3 class="card-title">{{ item.name }}</h3>
                      <span v-if="employeeRoleLabel(item.pkg_id)" class="card-role" :class="'card-role--' + employeeRoleLabel(item.pkg_id)">
                        {{ employeeRoleLabel(item.pkg_id) === 'read' ? '读取' : '生成' }}
                      </span>
                    </div>
                    <p class="card-meta">{{ item.pkg_id }} · v{{ item.version }}</p>
                  </div>
                </header>
                <p class="card-desc">{{ truncate(item.description, 88) }}</p>
                <div class="card-badges">
                  <span class="tag tag-industry">{{ item.industry || '通用' }}</span>
                  <span
                    v-if="item.license_scope === 'enterprise' && item.security_level === 'enterprise'"
                    class="tag tag-enterprise"
                  >企业级</span>
                  <span v-if="item.purchased" class="tag tag-owned">已购</span>
                  <span v-if="item.compliance_status && item.compliance_status !== 'approved'" class="tag tag-review">
                    {{ complianceStatusLabel(item.compliance_status) }}
                  </span>
                </div>
                <footer class="card-footer">
                  <div class="card-footer__left">
                    <span class="price" :class="{ free: item.price <= 0 }">
                      {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
                    </span>
                    <button
                      v-if="attachModId && item.artifact === 'employee_pack'"
                      type="button"
                      class="btn btn-primary btn-sm"
                      :disabled="attachingId === item.id"
                      @click="attachCardToMod(item)"
                    >
                      {{ attachingId === item.id ? '添加中…' : '添加到 Mod' }}
                    </button>
                    <button
                      v-else
                      type="button"
                      class="btn btn-download btn-sm"
                      :disabled="downloadingId === item.id"
                      @click="downloadCard(item)"
                    >
                      {{ downloadingId === item.id ? '下载中…' : '下载' }}
                    </button>
                  </div>
                  <div class="card-footer__social">
                    <button
                      type="button"
                      class="card-social card-social--like"
                      :class="{ 'card-social--on': item.favorited }"
                      :disabled="favBusyId === item.id"
                      :aria-pressed="!!item.favorited"
                      :title="item.favorited ? '取消点赞' : '点赞'"
                      @click="toggleLike(item)"
                    >
                      <span class="card-social__icon" aria-hidden="true">
                        <svg class="card-social__svg" viewBox="0 0 24 24" focusable="false">
                          <path
                            class="card-social__glyph card-social__glyph--heart"
                            d="M12 20.5s-6.2-4.35-8.2-7.4C2.4 10.6 2.8 6.9 5.5 5.2c1.6-.9 3.6-.5 4.9 1 1.3-1.5 3.3-1.9 4.9-1 2.7 1.7 3.1 5.4 1.7 7.9-2 3.05-8.2 7.4-8.2 7.4z"
                          />
                        </svg>
                      </span>
                      <span class="card-social__label">{{ formatSocialCount(item.favorite_count) }}</span>
                    </button>
                    <button
                      type="button"
                      class="card-social card-social--save"
                      :class="{ 'card-social--on': isItemSaved(item.id) }"
                      :aria-pressed="isItemSaved(item.id)"
                      :title="isItemSaved(item.id) ? '取消收藏' : '收藏'"
                      @click="toggleSaved(item)"
                    >
                      <span class="card-social__icon" aria-hidden="true">
                        <svg class="card-social__svg" viewBox="0 0 24 24" focusable="false">
                          <path
                            class="card-social__glyph card-social__glyph--star"
                            d="M12 3.2l2.35 4.76 5.25.77-3.8 3.7.9 5.23L12 15.9l-4.7 2.76.9-5.23-3.8-3.7 5.25-.77L12 3.2z"
                          />
                        </svg>
                      </span>
                      <span class="card-social__label">收藏</span>
                    </button>
                  </div>
                  <div class="card-actions">
                    <button
                      v-if="authStore.isAdmin"
                      type="button"
                      class="btn btn-danger btn-sm"
                      :disabled="delistingId === item.id"
                      @click="delistItem(item)"
                    >
                      {{ delistingId === item.id ? '下架中' : '下架' }}
                    </button>
                    <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn btn-detail btn-sm">
                      详情
                    </router-link>
                    <router-link :to="customerServiceLink(item, 'complaint')" class="card-link-muted">申诉</router-link>
                  </div>
                </footer>
              </article>
            </div>
          </section>
        </template>

        <p v-if="!loading && total > items.length" class="pager-hint">共 {{ total }} 条，当前展示前 {{ items.length }} 条。</p>
      </main>
    </div>

    <AdminDigestUnlockModal
      v-if="digestOpen"
      :open="digestOpen"
      :code="digestCode"
      :error="digestErr"
      :busy="digestBusy"
      :title="digestDialogTitle"
      :submit-label="digestDialogSubmitLabel"
      :hint="digestDialogHint"
      @update:code="digestCode = $event"
      @blur-code="onDigestInputBlur()"
      @submit="submitDigestVerify()"
      @cancel="closeDigestModal()"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { MOD_AUTHORING_ATTACH_KEY } from '../features/mod-authoring/types'
import { ApiError } from '../infrastructure/http/client'
import { useAuthStore } from '../stores/auth'
import AdminDigestUnlockModal from '../components/admin/AdminDigestUnlockModal.vue'
import EmployeePackTypeIcon from '../components/store/EmployeePackTypeIcon.vue'
import { useAdminDigestUnlock } from '../composables/useAdminDigestUnlock'
import { isCatalogSaved, toggleCatalogSaved } from '../utils/catalogSaved'
import {
  OFFICE_AUX_PACK_1_COLLECTION,
  OFFICE_AUX_PACK_1_PKG_IDS,
  OFFICE_AUX_GROUP_ORDER,
  OFFICE_EMPLOYEE_COLLECTION,
  OFFICE_EMPLOYEE_PKG_IDS,
  OFFICE_GROUP_LABELS,
  OFFICE_GROUP_ORDER,
  employeePackIconKind,
  employeePackRole,
  isOfficeAuxPack1Pkg,
  isOfficeEmployeePkg,
  type EmployeePackIconKind,
} from '../constants/officeEmployeePack'
import { WORKFLOW_EMPLOYEE_COLLECTION } from '../constants/workflowEmployeePack'
import { HOST_FOUNDATION_COLLECTION } from '../constants/hostFoundationPack'

type StoreNavId = 'all' | 'host_foundation' | 'office' | 'office_aux' | 'workflow' | 'ai_employee'

const ARTIFACT_LABELS = {
  mod: 'MOD 插件',
  employee_pack: 'AI 员工包',
  bundle: '资源包',
  surface: '界面扩展',
  workflow_template: '工作流模板',
}

const MATERIAL_CATEGORY_LABELS = {
  ai_employee: 'AI 员工',
  agent_prompt: 'Agent 提示词',
  skill: 'Skill',
  tts_voice: 'TTS 声音模型',
  mod_asset: 'MOD 包素材',
  page_style: '页面风格',
  personal_design: '个性化设计',
  workflow_template: '工作流模板',
  other: '其他素材',
}

const LICENSE_SCOPE_LABELS = {
  personal: '个人使用',
  commercial: '商业授权',
  free_personal: '免费个人用',
  enterprise: '企业级',
}

const COMPLIANCE_STATUS_LABELS = {
  approved: '已审核',
  under_review: '投诉处理中',
  restricted: '已降权',
  delisted: '已下架',
}

const SECURITY_LABELS = {
  personal: '个人',
  team: '团队',
  enterprise: '企业级',
  confidential: '保密',
}

interface AiStoreItem {
  id: number | string
  pkg_id?: string
  name?: string
  version?: string
  industry?: string
  artifact?: string
  material_category?: string
  material_category_label?: string
  license_scope?: string
  license_scope_label?: string
  security_level?: string
  compliance_status?: string
  purchased?: boolean
  favorited?: boolean
  favorite_count?: number
  description?: string
  price: number
}

interface CatalogFacets {
  industries: string[]
  artifacts: string[]
  material_categories: string[]
  license_scopes: string[]
  security_levels: string[]
}

const loading = ref(true)
const err = ref('')
const items = ref<AiStoreItem[]>([])
const total = ref(0)
const delistingId = ref<number | string | null>(null)
const activeTheme = ref<'host_foundation' | 'office' | 'office_aux' | 'workflow' | ''>('')
const storeNav = ref<StoreNavId>('all')
const showAdvancedFilters = ref(false)
const bundleDownloading = ref(false)
let suppressFilterWatch = false
let loadItemsTimer: ReturnType<typeof setTimeout> | null = null
const downloadingId = ref<number | string | null>(null)
const attachingId = ref<number | string | null>(null)
const favBusyId = ref<number | string | null>(null)
const route = useRoute()
const router = useRouter()
const attachModId = computed(() => String(route.query.attachModId || '').trim())
const savedRevision = ref(0)

const storeNavTabs = [
  { id: 'all' as StoreNavId, label: '全部商品', icon: undefined as EmployeePackIconKind | undefined, badge: '' },
  {
    id: 'host_foundation' as StoreNavId,
    label: '宿主基础员工',
    icon: undefined,
    badge: '1',
  },
  {
    id: 'office' as StoreNavId,
    label: '办公员工包',
    icon: 'office' as EmployeePackIconKind,
    badge: String(OFFICE_EMPLOYEE_PKG_IDS.length),
  },
  {
    id: 'office_aux' as StoreNavId,
    label: '办公员工附属包1',
    icon: 'report' as EmployeePackIconKind,
    badge: '',
  },
  { id: 'workflow' as StoreNavId, label: '工作流员工', icon: undefined, badge: '6' },
  { id: 'ai_employee' as StoreNavId, label: 'AI 员工', icon: undefined, badge: '' },
]

/** 附属包角标与市场上架数一致（未上架时为 0，不再写死为 1） */
const officeAuxNavBadge = ref('')

const storeNavTabsDisplay = computed(() =>
  storeNavTabs.map((tab) =>
    tab.id === 'office_aux' ? { ...tab, badge: officeAuxNavBadge.value } : tab,
  ),
)

async function refreshOfficeAuxNavBadge() {
  try {
    const res = await api.catalog(
      '',
      'employee_pack',
      20,
      0,
      '',
      '',
      'ai_employee',
      '',
      false,
      OFFICE_AUX_PACK_1_COLLECTION,
    )
    let list = ((res.items || []) as AiStoreItem[]).filter((it) => isOfficeAuxPack1Pkg(it.pkg_id))
    officeAuxNavBadge.value = String(list.length)
  } catch {
    officeAuxNavBadge.value = '0'
  }
}

const mainListTitle = computed(() => {
  if (activeTheme.value === 'host_foundation') return '宿主基础能力（预装员工）'
  if (activeTheme.value === 'office') return '办公员工包'
  if (activeTheme.value === 'office_aux') return '办公员工附属包1'
  if (activeTheme.value === 'workflow') return '工作流员工'
  if (filters.materialCategory === 'ai_employee') return 'AI 员工'
  if (appliedQ.value) return `搜索「${appliedQ.value}」`
  return '全部商品'
})

const advancedFilterCount = computed(() => {
  let n = 0
  if (filters.industry) n++
  if (filters.licenseScope) n++
  if (filters.securityLevel) n++
  if (!isPackCollectionNav.value && filters.materialCategory) n++
  if (!isPackCollectionNav.value && filters.artifact) n++
  return n
})

const isPackCollectionNav = computed(
  () =>
    storeNav.value === 'office' ||
    storeNav.value === 'office_aux' ||
    storeNav.value === 'workflow' ||
    storeNav.value === 'host_foundation',
)

function buildPackGroups(order: EmployeePackIconKind[]) {
  const map = new Map<EmployeePackIconKind, AiStoreItem[]>()
  for (const item of items.value) {
    const kind = employeePackIconKind(item.pkg_id)
    if (!order.includes(kind)) continue
    const list = map.get(kind) || []
    list.push(item)
    map.set(kind, list)
  }
  return order.filter((k) => map.has(k)).map((kind) => ({
    kind,
    title: OFFICE_GROUP_LABELS[kind],
    items: map.get(kind) || [],
  }))
}

const officeGroups = computed(() => {
  if (activeTheme.value !== 'office') return []
  return buildPackGroups([...OFFICE_GROUP_ORDER])
})

const officeAuxGroups = computed(() => {
  if (activeTheme.value !== 'office_aux') return []
  return buildPackGroups([...OFFICE_AUX_GROUP_ORDER])
})

const displayGroups = computed(() => {
  if (activeTheme.value === 'office' && officeGroups.value.length) {
    return officeGroups.value.map((g) => ({
      key: g.kind,
      title: g.title,
      kind: g.kind,
      items: g.items,
    }))
  }
  if (activeTheme.value === 'office_aux' && officeAuxGroups.value.length) {
    return officeAuxGroups.value.map((g) => ({
      key: g.kind,
      title: g.title,
      kind: g.kind,
      items: g.items,
    }))
  }
  if (activeTheme.value === 'office_aux') {
    return [{ key: 'aux-flat', title: '', kind: 'report' as EmployeePackIconKind, items: items.value }]
  }
  return [{ key: 'all', title: '', kind: undefined as EmployeePackIconKind | undefined, items: items.value }]
})

function employeeRoleLabel(pkgId?: string) {
  return employeePackRole(pkgId)
}

function formatSocialCount(n?: number) {
  const v = Number(n ?? 0) || 0
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

function isItemSaved(id: number | string | undefined) {
  savedRevision.value
  return isCatalogSaved(id)
}

function toggleSaved(item: AiStoreItem) {
  if (!item?.id) return
  toggleCatalogSaved(item.id)
  savedRevision.value++
}

async function toggleLike(item: AiStoreItem) {
  if (!item?.id || favBusyId.value) return
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再点赞'
    return
  }
  favBusyId.value = item.id
  err.value = ''
  try {
    const r = (await api.catalogToggleFavorite(item.id)) as { favorited?: boolean }
    const on = !!r.favorited
    const delta = on ? 1 : -1
    item.favorited = on
    item.favorite_count = Math.max(0, (item.favorite_count ?? 0) + delta)
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    favBusyId.value = null
  }
}

async function downloadCard(item: AiStoreItem) {
  if (!item?.id || downloadingId.value) return
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再下载'
    return
  }
  downloadingId.value = item.id
  err.value = ''
  try {
    await api.downloadItem(item.id)
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    downloadingId.value = null
  }
}

async function attachCardToMod(item: AiStoreItem) {
  const modId = attachModId.value
  const pkgId = String(item.pkg_id || '').trim()
  if (!modId || !pkgId || attachingId.value) return
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再添加到 Mod'
    return
  }
  if (item.artifact !== 'employee_pack') {
    err.value = '仅支持将 AI 员工包添加到 Mod'
    return
  }
  attachingId.value = item.id
  err.value = ''
  try {
    if (item.price > 0 && !item.purchased) {
      await api.buyItem(item.id)
      item.purchased = true
    }
    await api.attachCatalogEmployeeToMod(modId, {
      pkg_id: pkgId,
      catalog_item_id: typeof item.id === 'number' ? item.id : undefined,
    })
    try {
      sessionStorage.removeItem(MOD_AUTHORING_ATTACH_KEY)
    } catch {
      /* ignore */
    }
    await router.push({ name: 'mod-authoring', params: { modId } })
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    attachingId.value = null
  }
}
const searchQ = ref('')
const appliedQ = ref('')
const facets = ref<CatalogFacets>({ industries: [], artifacts: [], material_categories: [], license_scopes: [], security_levels: [] })
const authStore = useAuthStore()
const {
  open: digestOpen,
  code: digestCode,
  err: digestErr,
  busy: digestBusy,
  dialogTitle: digestDialogTitle,
  dialogSubmitLabel: digestDialogSubmitLabel,
  dialogHint: digestDialogHint,
  onInputBlur: onDigestInputBlur,
  close: closeDigestModal,
  submitVerify: submitDigestVerify,
  ensureAdminDigestUnlocked,
} = useAdminDigestUnlock()

const filters = reactive({
  industry: '',
  artifact: '',
  materialCategory: '',
  licenseScope: '',
  securityLevel: '',
})

const facetIndustries = computed(() => facets.value.industries || [])
const facetArtifacts = computed(() => facets.value.artifacts || [])
const facetMaterialCategories = computed(() => facets.value.material_categories || [])
const facetLicenseScopes = computed(() => facets.value.license_scopes || [])
const facetSecurityLevels = computed(() => facets.value.security_levels || [])

function artifactLabel(art: string | undefined): string {
  return (art && (ARTIFACT_LABELS as Record<string, string>)[art]) || art || '其他'
}

function materialCategoryLabel(cat: string | undefined): string {
  return (cat && (MATERIAL_CATEGORY_LABELS as Record<string, string>)[cat]) || cat || '其他素材'
}

function licenseScopeLabel(scope: string | undefined): string {
  return (scope && (LICENSE_SCOPE_LABELS as Record<string, string>)[scope]) || scope || '个人使用'
}

function complianceStatusLabel(status: string | undefined): string {
  return (status && (COMPLIANCE_STATUS_LABELS as Record<string, string>)[status]) || status || '待处理'
}

function securityLabel(level: string | undefined): string {
  return (level && (SECURITY_LABELS as Record<string, string>)[level]) || '个人'
}

function securityLevelClass(level: string | undefined): string {
  if (level === 'confidential') return 'tag-confidential'
  if (level === 'enterprise') return 'tag-enterprise'
  return 'tag-personal'
}

function truncate(str: string | undefined | null, len: number): string {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}

async function loadFacets() {
  try {
    const res = await api.catalogFacets()
    facets.value = {
      industries: res.industries || [],
      artifacts: res.artifacts || [],
      material_categories: res.material_categories || [],
      license_scopes: res.license_scopes || [],
      security_levels: res.security_levels || [],
    }
  } catch {
    facets.value = { industries: [], artifacts: [], material_categories: [], license_scopes: [], security_levels: [] }
  }
}

async function loadItems(cacheBust = false) {
  loading.value = true
  err.value = ''
  try {
    const res = await api.catalog(
      appliedQ.value,
      filters.artifact,
      80,
      0,
      filters.industry,
      filters.securityLevel,
      filters.materialCategory,
      filters.licenseScope,
      cacheBust,
      activeTheme.value === 'host_foundation'
        ? HOST_FOUNDATION_COLLECTION
        : activeTheme.value === 'office'
          ? OFFICE_EMPLOYEE_COLLECTION
          : activeTheme.value === 'office_aux'
            ? OFFICE_AUX_PACK_1_COLLECTION
            : activeTheme.value === 'workflow'
              ? WORKFLOW_EMPLOYEE_COLLECTION
              : '',
    )
    let list = ((res.items || []) as AiStoreItem[]).map((it) => ({
      ...it,
      price: Number(it.price ?? 0) || 0,
      favorite_count: Number(it.favorite_count ?? 0) || 0,
      favorited: !!it.favorited,
    }))
    // 服务端未识别 collection 时会退回「全部 ai_employee」；前端按导航再收窄，避免附属包误展示主包 11 件
    if (activeTheme.value === 'office') {
      list = list.filter((it) => isOfficeEmployeePkg(it.pkg_id))
    } else if (activeTheme.value === 'office_aux') {
      list = list.filter((it) => isOfficeAuxPack1Pkg(it.pkg_id))
    }
    items.value = list
    total.value =
      activeTheme.value === 'office' || activeTheme.value === 'office_aux'
        ? list.length
        : (res.total ?? list.length)
    if (activeTheme.value === 'office_aux') {
      officeAuxNavBadge.value = String(list.length)
    }
  } catch (e: unknown) {
    if (e instanceof ApiError && e.status === 429) {
      err.value = '请求过于频繁，请稍等几秒后刷新页面'
    } else {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    }
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function setIndustry(v: string) {
  filters.industry = v
}

function setArtifact(v: string) {
  filters.artifact = v
}

function setMaterialCategory(v: string) {
  filters.materialCategory = v
}

function setLicenseScope(v: string) {
  filters.licenseScope = v
}

function setSecurityLevel(v: string) {
  filters.securityLevel = v
}

function applyFilters() {
  appliedQ.value = searchQ.value.trim()
  loadItems()
}

function resetFilters() {
  searchQ.value = ''
  appliedQ.value = ''
  filters.industry = ''
  filters.artifact = ''
  filters.materialCategory = ''
  filters.licenseScope = ''
  filters.securityLevel = ''
  activeTheme.value = ''
  storeNav.value = 'all'
  loadItems()
}

function setStoreNav(id: StoreNavId) {
  if (storeNav.value === id && id !== 'all') return
  suppressFilterWatch = true
  storeNav.value = id
  if (id === 'host_foundation') {
    activeTheme.value = 'host_foundation'
    filters.materialCategory = 'ai_employee'
    filters.artifact = 'employee_pack'
    scheduleLoadItems()
    suppressFilterWatch = false
    return
  }
  if (id === 'office') {
    activeTheme.value = 'office'
    filters.materialCategory = 'ai_employee'
    filters.artifact = 'employee_pack'
    scheduleLoadItems()
    suppressFilterWatch = false
    return
  }
  if (id === 'office_aux') {
    activeTheme.value = 'office_aux'
    filters.materialCategory = 'ai_employee'
    filters.artifact = 'employee_pack'
    scheduleLoadItems()
    suppressFilterWatch = false
    return
  }
  if (id === 'workflow') {
    activeTheme.value = 'workflow'
    filters.materialCategory = 'ai_employee'
    filters.artifact = 'mod'
    scheduleLoadItems()
    suppressFilterWatch = false
    return
  }
  activeTheme.value = ''
  if (id === 'ai_employee') {
    filters.materialCategory = 'ai_employee'
    filters.artifact = ''
  } else {
    filters.materialCategory = ''
    filters.artifact = ''
  }
  scheduleLoadItems()
  suppressFilterWatch = false
}

function scheduleLoadItems(cacheBust = false) {
  if (loadItemsTimer) clearTimeout(loadItemsTimer)
  loadItemsTimer = setTimeout(() => {
    loadItemsTimer = null
    void loadItems(cacheBust)
  }, 80)
}

function selectOfficeTheme() {
  setStoreNav('office')
}

function clearTheme() {
  setStoreNav('all')
}

async function downloadOfficeBundle() {
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再下载办公员工包'
    return
  }
  bundleDownloading.value = true
  err.value = ''
  try {
    await api.downloadOfficeEmployeePack()
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    bundleDownloading.value = false
  }
}

async function downloadWorkflowBundle() {
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再下载工作流员工包'
    return
  }
  bundleDownloading.value = true
  err.value = ''
  try {
    await api.downloadWorkflowEmployeePack()
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    bundleDownloading.value = false
  }
}

async function downloadHostFoundationPack() {
  if (!authStore.isLoggedIn) {
    err.value = '请先登录后再下载宿主基础员工包'
    return
  }
  bundleDownloading.value = true
  err.value = ''
  try {
    await api.downloadHostFoundationEmployeePack()
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    bundleDownloading.value = false
  }
}

function customerServiceLink(item: AiStoreItem, scene = 'complaint') {
  return {
    name: 'customer-service',
    query: {
      scene,
      catalog_id: String(item?.id || ''),
      pkg_id: item?.pkg_id || '',
      item_name: item?.name || '',
      material_category: item?.material_category || '',
    },
  }
}

async function delistItem(item: AiStoreItem) {
  if (!item || delistingId.value) return
  const unlocked = await ensureAdminDigestUnlocked({
    title: '下架需身份校验',
    submitLabel: '验证',
    hint: '敏感操作：须输入与「解锁管理端」相同的 6 位身份码后方可下架商品。',
  })
  if (!unlocked) return
  const ok = window.confirm(`确定下架「${item.name}」吗？下架后 AI 市场将不再展示该商品。`)
  if (!ok) return
  delistingId.value = item.id
  err.value = ''
  try {
    await api.adminDeleteCatalog(item.id)
    await loadItems(true)
    await loadFacets()
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
  } finally {
    delistingId.value = null
  }
}

watch(
  () => [filters.industry, filters.artifact, filters.materialCategory, filters.licenseScope, filters.securityLevel],
  () => {
    if (suppressFilterWatch) return
    scheduleLoadItems()
  },
)

onMounted(async () => {
  await loadFacets()
  void refreshOfficeAuxNavBadge()
  const navHint = String(route.query.nav || route.query.collection || '').trim()
  if (
    navHint === 'office_aux' ||
    navHint === 'office_aux_2' ||
    navHint === OFFICE_AUX_PACK_1_COLLECTION ||
    navHint === 'office_employee_aux_pack_2'
  ) {
    setStoreNav('office_aux')
    return
  }
  await loadItems()
})
</script>

<style scoped>
.store-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #fff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  padding-bottom: 48px;
}

.store-attach-banner {
  max-width: var(--layout-max);
  margin: 0 auto 0.75rem;
  padding: 0 var(--layout-pad-x);
  box-sizing: border-box;
}

.store-top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px 24px;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 1.25rem var(--layout-pad-x) 1rem;
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(180deg, rgba(96, 165, 250, 0.06) 0%, transparent 100%);
  box-sizing: border-box;
}

.store-top__brand {
  min-width: 0;
}

.store-eyebrow {
  font-size: 11px;
  color: rgba(96, 165, 250, 0.85);
  letter-spacing: 0.1em;
  margin: 0 0 4px;
  text-transform: uppercase;
}

.store-title {
  font-size: clamp(20px, 3vw, 26px);
  font-weight: 600;
  margin: 0;
  letter-spacing: -0.02em;
}

.store-search {
  display: flex;
  flex: 1;
  min-width: min(100%, 280px);
  max-width: 420px;
  gap: 8px;
  align-items: center;
}

.store-search__input {
  flex: 1;
  min-width: 0;
}

.store-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 0;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 0 var(--layout-pad-x);
  box-sizing: border-box;
  align-items: start;
}

.store-sidebar {
  position: sticky;
  top: 12px;
  padding: 1rem 1rem 1rem 0;
  border-right: 0.5px solid rgba(255, 255, 255, 0.06);
  margin-right: 1rem;
}

.store-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.store-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 0.5px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: rgba(255, 255, 255, 0.72);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.store-nav__item:hover {
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
}

.store-nav__item.active {
  border-color: rgba(96, 165, 250, 0.35);
  background: rgba(96, 165, 250, 0.1);
  color: #fff;
}

.store-nav__icon :deep(.pack-type-icon) {
  width: 28px;
  height: 28px;
}

.store-nav__icon :deep(.pack-type-icon svg) {
  width: 28px;
  height: 28px;
}

.store-nav__label {
  flex: 1;
}

.store-nav__badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.2);
  color: #93c5fd;
}

.office-spotlight {
  margin-bottom: 12px;
  padding: 12px;
  border-radius: 10px;
  background: rgba(59, 130, 246, 0.08);
  border: 0.5px solid rgba(96, 165, 250, 0.2);
}

.office-spotlight__text {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.55);
}

.store-adv-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 0;
  border: none;
  background: none;
  color: rgba(255, 255, 255, 0.45);
  font-size: 12px;
  cursor: pointer;
}

.store-adv-toggle:hover {
  color: rgba(255, 255, 255, 0.8);
}

.store-adv-toggle__count {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.25);
  color: #bfdbfe;
}

.store-adv-toggle__chev {
  margin-left: auto;
  transform: rotate(90deg);
  transition: transform 0.15s;
}

.store-adv-toggle__chev.open {
  transform: rotate(-90deg);
}

.store-adv-filters {
  padding-top: 8px;
}

.filter-block {
  margin-bottom: 12px;
}

.filter-block:last-child {
  margin-bottom: 8px;
}

.store-main {
  min-width: 0;
  padding: 1rem 0 0;
}

.store-main__bar {
  margin-bottom: 14px;
}

.store-main__title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
}

.store-main__meta {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
}

.store-group {
  margin-bottom: 28px;
}

.store-group--flat {
  margin-bottom: 0;
}

.store-group__hd {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
}

.store-group__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.store-group__count {
  margin-left: auto;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
}

.filter-label {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  margin-bottom: 8px;
  letter-spacing: 0.04em;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.chip:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.chip.active {
  border-color: rgba(96, 165, 250, 0.5);
  background: rgba(96, 165, 250, 0.12);
  color: #fff;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: #141414;
  color: #fff;
}

.btn-primary {
  border-color: rgba(59, 130, 246, 0.55);
  background: rgba(59, 130, 246, 0.22);
  color: #93c5fd;
}

.btn-primary:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.35);
  color: #fff;
}

.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.06);
}

.btn-text {
  border-color: transparent;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
}

.btn-text:hover {
  color: #fff;
}

.input {
  padding: 10px 12px;
  border-radius: 8px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
  font-size: 14px;
  outline: none;
}

.input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.flash {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto 16px;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 14px;
  box-sizing: border-box;
}

.flash-err {
  background: rgba(255, 80, 80, 0.1);
  color: #ff8a8a;
}

.state-msg {
  text-align: center;
  padding: 40px 24px;
  font-size: 15px;
}

.state-msg.muted {
  color: rgba(255, 255, 255, 0.35);
}

.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 15.5rem), 1fr));
  gap: 14px;
}

.store-card {
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 14px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.2s, background 0.2s, transform 0.15s;
}

.store-card:hover {
  border-color: rgba(96, 165, 250, 0.25);
  background: rgba(255, 255, 255, 0.035);
}

.store-card__head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.store-card__avatar :deep(.pack-type-icon) {
  width: 40px;
  height: 40px;
}

.store-card__avatar :deep(.pack-type-icon svg) {
  width: 40px;
  height: 40px;
}

.store-card__titles {
  flex: 1;
  min-width: 0;
}

.store-card__title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-role {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.card-role--read {
  background: rgba(45, 212, 191, 0.15);
  color: #5eead4;
}

.card-role--generate {
  background: rgba(167, 139, 250, 0.15);
  color: #c4b5fd;
}

.card-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}

.tag-industry {
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
}

.tag-type {
  background: rgba(167, 139, 250, 0.12);
  color: #c4b5fd;
}

.tag-category {
  background: rgba(45, 212, 191, 0.12);
  color: #5eead4;
}

.tag-license {
  background: rgba(251, 146, 60, 0.12);
  color: #fdba74;
}

.tag-license-enterprise {
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
}

.tag-review {
  background: rgba(250, 204, 21, 0.13);
  color: #fde047;
}

.tag-owned {
  background: rgba(74, 222, 128, 0.12);
  color: #86efac;
}

.tag-personal { background: rgba(74, 222, 128, 0.12); color: #86efac; }
.tag-enterprise { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
.tag-confidential { background: rgba(248, 113, 113, 0.15); color: #f87171; }

.card-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  line-height: 1.3;
}

.card-desc {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.48);
  margin: 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.28);
  margin: 2px 0 0;
  word-break: break-all;
}

.card-link-muted {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  text-decoration: none;
}

.card-link-muted:hover {
  color: rgba(255, 255, 255, 0.7);
}

.btn-block {
  width: 100%;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 12px;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 12px;
  margin-top: auto;
  padding-top: 4px;
  border-top: 0.5px solid rgba(255, 255, 255, 0.06);
}

.card-footer__left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.card-footer__social {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.card-social {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.58);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    transform 0.12s ease;
}

.card-social:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.16);
  color: rgba(255, 255, 255, 0.92);
}

.card-social:active:not(:disabled) {
  transform: scale(0.96);
}

.card-social:focus {
  outline: none;
}

.card-social:focus-visible {
  box-shadow: 0 0 0 2px rgba(10, 10, 10, 0.95), 0 0 0 4px rgba(96, 165, 250, 0.45);
}

.card-social--like:hover:not(:disabled):not(.card-social--on) {
  color: #fda4af;
  border-color: rgba(251, 113, 133, 0.22);
}

.card-social--like.card-social--on {
  border-color: rgba(244, 63, 94, 0.28);
  background: rgba(244, 63, 94, 0.1);
  color: #fb7185;
}

.card-social--save:hover:not(:disabled):not(.card-social--on) {
  color: #fde68a;
  border-color: rgba(251, 191, 36, 0.22);
}

.card-social--save.card-social--on {
  border-color: rgba(251, 191, 36, 0.32);
  background: rgba(251, 191, 36, 0.1);
  color: #fbbf24;
}

.card-social:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.card-social__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.card-social__svg {
  width: 16px;
  height: 16px;
  display: block;
}

.card-social__glyph {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: fill 0.18s ease, stroke 0.18s ease, transform 0.18s ease;
}

.card-social--on .card-social__glyph--heart,
.card-social--on .card-social__glyph--star {
  fill: currentColor;
  stroke: currentColor;
}

.card-social--like.card-social--on .card-social__glyph--heart {
  transform-origin: center;
  transform: scale(1.05);
}

.card-social__label {
  min-width: 1.2em;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}

.btn-download {
  border-color: rgba(74, 222, 128, 0.35);
  background: rgba(74, 222, 128, 0.12);
  color: #86efac;
}

.btn-download:hover:not(:disabled) {
  background: rgba(74, 222, 128, 0.22);
  color: #fff;
}

.btn-download:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.card-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.price {
  font-size: 18px;
  font-weight: 700;
}

.price.free {
  color: #86efac;
}

.btn-detail {
  text-decoration: none;
  border: 0.5px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  padding: 6px 12px;
  font-size: 13px;
  border-radius: 8px;
}

.btn-detail:hover {
  background: rgba(255, 255, 255, 0.12);
}

.btn-danger {
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(127, 29, 29, 0.18);
}

.btn-danger:hover:not(:disabled) {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.28);
}

.pager-hint {
  text-align: center;
  margin-top: 24px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

html[data-workbench-theme='light'] .store-page {
  background: #f5f5f7;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .store-top {
  background: linear-gradient(180deg, rgba(0,113,227,0.06) 0%, transparent 100%);
  border-bottom-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .store-sidebar {
  border-right-color: rgba(0,0,0,0.08);
}

html[data-workbench-theme='light'] .store-nav__item {
  color: #555;
}

html[data-workbench-theme='light'] .store-nav__item:hover,
html[data-workbench-theme='light'] .store-nav__item.active {
  color: #1d1d1f;
  background: rgba(0,113,227,0.08);
  border-color: rgba(0,113,227,0.2);
}

html[data-workbench-theme='light'] .office-spotlight {
  background: rgba(0,113,227,0.06);
  border-color: rgba(0,113,227,0.15);
}

html[data-workbench-theme='light'] .office-spotlight__text {
  color: #86868b;
}

html[data-workbench-theme='light'] .store-main__title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .store-group__hd {
  border-bottom-color: rgba(0,0,0,0.08);
}

html[data-workbench-theme='light'] .store-eyebrow {
  color: #0071e3;
}

html[data-workbench-theme='light'] .store-sub {
  color: #86868b;
}

html[data-workbench-theme='light'] .filter-label {
  color: #86868b;
}

html[data-workbench-theme='light'] .chip {
  border-color: rgba(0,0,0,0.1);
  background: rgba(0,0,0,0.03);
  color: #555;
}

html[data-workbench-theme='light'] .chip:hover {
  background: rgba(0,0,0,0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .chip.active {
  border-color: rgba(0,113,227,0.4);
  background: rgba(0,113,227,0.08);
  color: #0071e3;
}

html[data-workbench-theme='light'] .btn {
  border-color: rgba(0,0,0,0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn-ghost:hover {
  background: rgba(0,0,0,0.04);
}

html[data-workbench-theme='light'] .btn-text {
  color: #86868b;
}

html[data-workbench-theme='light'] .btn-text:hover {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .input {
  border-color: rgba(0,0,0,0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .input::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .flash-err {
  background: rgba(220,38,38,0.06);
  color: #dc2626;
}

html[data-workbench-theme='light'] .state-msg.muted {
  color: #86868b;
}

html[data-workbench-theme='light'] .store-card {
  border-color: rgba(0,0,0,0.08);
  background: #ffffff;
}

html[data-workbench-theme='light'] .store-card:hover {
  border-color: rgba(0,0,0,0.12);
  background: rgba(0,0,0,0.01);
}

html[data-workbench-theme='light'] .card-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .card-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .card-meta {
  color: #aaa;
}

html[data-workbench-theme='light'] .tag-industry {
  background: rgba(0,113,227,0.08);
  color: #0071e3;
}

html[data-workbench-theme='light'] .tag-type {
  background: rgba(129,140,248,0.08);
  color: #6366f1;
}

html[data-workbench-theme='light'] .tag-category {
  background: rgba(45,212,191,0.08);
  color: #0d9488;
}

html[data-workbench-theme='light'] .tag-license {
  background: rgba(251,146,60,0.08);
  color: #ea580c;
}

html[data-workbench-theme='light'] .tag-review {
  background: rgba(234,179,8,0.08);
  color: #ca8a04;
}

html[data-workbench-theme='light'] .tag-owned {
  background: rgba(34,197,94,0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .tag-personal {
  background: rgba(34,197,94,0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .tag-enterprise {
  background: rgba(234,179,8,0.08);
  color: #ca8a04;
}

html[data-workbench-theme='light'] .tag-confidential {
  background: rgba(220,38,38,0.08);
  color: #dc2626;
}

html[data-workbench-theme='light'] .price.free {
  color: #16a34a;
}

html[data-workbench-theme='light'] .card-footer {
  border-top-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .card-social {
  border-color: rgba(0, 0, 0, 0.1);
  background: rgba(0, 0, 0, 0.04);
  color: #6e6e73;
}

html[data-workbench-theme='light'] .card-social:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .card-social:focus-visible {
  box-shadow: 0 0 0 2px #fff, 0 0 0 4px rgba(37, 99, 235, 0.35);
}

html[data-workbench-theme='light'] .card-social--like.card-social--on {
  border-color: rgba(225, 29, 72, 0.22);
  background: rgba(225, 29, 72, 0.08);
  color: #e11d48;
}

html[data-workbench-theme='light'] .card-social--save.card-social--on {
  border-color: rgba(217, 119, 6, 0.25);
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
}

html[data-workbench-theme='light'] .btn-download {
  border-color: rgba(22, 163, 74, 0.3);
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .btn-detail {
  border-color: rgba(0,0,0,0.1);
  background: rgba(0,0,0,0.03);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn-detail:hover {
  background: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .btn-danger {
  color: #dc2626;
  border-color: rgba(220,38,38,0.25);
  background: rgba(220,38,38,0.06);
}

html[data-workbench-theme='light'] .btn-danger:hover:not(:disabled) {
  color: #b91c1c;
  background: rgba(220,38,38,0.1);
}

html[data-workbench-theme='light'] .store-main__meta,
html[data-workbench-theme='light'] .pager-hint {
  color: #86868b;
}

@media (max-width: 900px) {
  .store-shell {
    grid-template-columns: 1fr;
  }

  .store-sidebar {
    position: static;
    border-right: none;
    border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
    margin-right: 0;
    padding: 1rem 0;
  }

  .store-nav {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .store-nav__item {
    width: auto;
    flex: 1;
    min-width: 7rem;
  }
}

@media (max-width: 640px) {
  .store-top {
    padding: 1rem 16px;
  }

  .store-shell {
    padding: 0 16px;
  }

  .store-search {
    max-width: none;
    width: 100%;
  }
}
</style>
