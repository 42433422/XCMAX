<template>
  <div class="mod-store store-page">
    <header class="store-top">
      <div class="store-topbar">
        <button type="button" class="store-back" @click="goBackFromStore">
          <i class="fa fa-arrow-left" aria-hidden="true"></i>
          <span>返回 AI 生态</span>
        </button>
        <div class="store-brandline">
          <h1 class="store-title">AI 市场</h1>
          <p class="store-sub">发现业务模块，挑选 AI 员工</p>
        </div>
        <div class="store-hero__stats">
          <span><strong>{{ filteredMods.length }}</strong> 个结果</span>
          <span><strong>{{ installedCount }}</strong> 已安装</span>
        </div>
      </div>
      <ElSegmented class="store-types" :model-value="marketType" :options="marketTypes" aria-label="市场类型" @change="switchMarketType" />
      <form class="store-search store-search--hero" @submit.prevent="searchMods">
        <i class="fa fa-search store-search__icon" aria-hidden="true"></i>
        <input v-model="searchQuery" type="search" class="store-search__input" :placeholder="marketType === 'module' ? '搜索模块、行业或能力' : '搜索员工、岗位或包名'" />
        <button type="submit" class="btn btn-primary store-search__btn">搜索</button>
      </form>
      <div v-if="marketType === 'employee'" class="store-hot">
        <span class="store-hot__label">热门搜索</span>
        <button v-for="kw in hotKeywords" :key="kw" type="button" class="store-hot__item" @click="applyQuickSearch(kw)">
          {{ kw }}
        </button>
      </div>
    </header>

    <div v-if="marketType === 'employee' && onboardingBanner" class="onboarding-banner">
      <p>
        请先安装宿主基础员工包。
        <span v-if="missingModHint" class="mono">缺少：{{ missingModHint }}</span>
      </p>
      <button type="button" class="btn btn-primary" :disabled="bootstrapBusy" @click="runOneClickInstallAndOnboard">
        <i class="fa fa-download" :class="{ 'fa-spin': bootstrapBusy }"></i>
        安装宿主基础员工包
      </button>
      <button v-if="route.query.onboarding === '1'" type="button" class="btn btn-ghost" @click="finishOnboardingFromStore">
        完成引导，进入对话
      </button>
    </div>

    <div class="store-toolbar">
      <button
        v-if="marketType === 'employee'"
        type="button"
        class="btn btn-primary btn-sm store-toolbar__cta"
        data-tour="store-one-click-install"
        :disabled="bootstrapBusy"
        @click="runOneClickInstallAndOnboard"
      >
        <i class="fa fa-bolt" :class="{ 'fa-spin': bootstrapBusy }" aria-hidden="true"></i>
        {{ oneClickCtaLabel }}
      </button>
      <span v-if="marketType === 'module'" class="store-toolbar__hint muted">安装业务模块，扩展工作台能力。</span>
      <span v-else-if="oneClickProgress" class="store-toolbar__hint muted">{{ oneClickProgress }}</span>
      <span v-else-if="currentTab !== 'all' && oneClickPendingCount > 0" class="store-toolbar__hint muted">
        将装齐「{{ mainListTitle }}」全部 {{ oneClickPendingCount }} 个员工并入驻
      </span>
      <span v-else-if="!deliverableOk" class="store-toolbar__hint muted"> 将先装齐宿主基础员工包，再安装当前分类员工 </span>
      <span class="store-toolbar__spacer" aria-hidden="true"></span>
      <a :href="modstoreWebUrl" target="_blank" rel="noopener noreferrer" class="btn btn-ghost btn-sm">
        <i class="fa fa-external-link"></i> 打开工作台
      </a>
      <a :href="marketBaseUrl" target="_blank" rel="noopener noreferrer" class="btn btn-ghost btn-sm">
        <i class="fa fa-store"></i> 修茈市场首页
      </a>
      <button type="button" class="btn btn-ghost btn-sm" :disabled="loading || refreshing" @click="loadMods(true)">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }"></i> 刷新目录
      </button>
    </div>

    <nav v-if="marketType === 'employee'" class="store-tabs" aria-label="员工分类">
      <button
        v-for="tab in employeeNavTabs"
        :key="tab.id"
        type="button"
        class="store-tab"
        :data-tour="`store-nav-${tab.id}`"
        :class="{ active: currentTab === tab.id }"
        @click="switchTab(tab.id)"
      >
        <i :class="['fa', tab.icon]" aria-hidden="true"></i>
        <span>{{ tab.label }}</span>
      </button>
    </nav>

    <div v-if="marketType === 'employee'" class="store-hero-grid">
      <section class="store-cats" aria-label="员工分类导航">
        <header class="store-cats__head">
          <h2>员工分类</h2>
          <span>按岗位快速筛选</span>
        </header>
        <div class="store-cats__grid">
          <button
            v-for="tab in employeeNavTabs"
            :key="tab.id"
            type="button"
            class="store-cat"
            :class="{ active: currentTab === tab.id }"
            @click="switchTab(tab.id)"
          >
            <i :class="['fa', tab.icon]" aria-hidden="true"></i>
            <span>{{ tab.label }}</span>
          </button>
        </div>
      </section>

      <section v-if="featuredPacks.length" class="store-featured" aria-label="员工包">
        <button
          v-for="(pack, index) in featuredPacks"
          :key="pack.tab"
          type="button"
          class="store-feature"
          :class="`store-feature--${index + 1}`"
          @click="switchTab(pack.tab)"
        >
          <span class="store-feature__tag">员工包</span>
          <span class="store-feature__icon store-feature__icon--glyph">
            <i :class="['fa', pack.icon]" aria-hidden="true"></i>
          </span>
          <strong class="store-feature__name">{{ pack.label }}</strong>
          <span class="store-feature__desc">{{ pack.description }}</span>
          <span class="store-feature__meta">
            {{ pack.total }} 个员工<template v-if="pack.installed"> · 已装 {{ pack.installed }}</template>
          </span>
        </button>
      </section>
    </div>

    <div class="store-shell" data-tour="store-shell">
      <main class="store-main" aria-labelledby="store-results-heading">
        <div class="store-filterbar">
          <div class="store-filterbar__left">
            <h2 id="store-results-heading" class="store-main__title">{{ mainListTitle }}</h2>
            <p class="store-main__meta">
              共 {{ filteredMods.length }} 个{{ marketType === 'module' ? '模块' : '员工' }}
              <span v-if="refreshing" class="store-sync-hint"> <i class="fa fa-refresh fa-spin" aria-hidden="true"></i> 同步中… </span>
              <span v-else-if="fromCache" class="store-cache-hint muted">已缓存</span>
            </p>
          </div>
          <div class="store-filterbar__right">
            <label class="store-filter-check">
              <input type="checkbox" v-model="filterInstalled" @change="applyFilters" />
              仅看已安装
            </label>
            <select v-model="sortBy" class="store-sort" @change="applyFilters" aria-label="排序">
              <option value="name">按名称</option>
              <option value="downloads">按下载量</option>
              <option value="rating">按评分</option>
              <option value="created_at">最新上架</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !filteredMods.length" class="state-msg">
          <i class="fa fa-spinner fa-spin"></i> 加载中…
          <span v-if="isMarketCollectionTab(currentTab)" class="store-load-hint muted">
            正在同步修茈 AI 市场目录…
          </span>
        </div>

        <div v-else-if="loadError && !filteredMods.length" class="state-msg store-load-error">
          <i class="fa fa-exclamation-triangle"></i> {{ loadError }}
        </div>

        <div v-else-if="filteredMods.length === 0" class="state-msg muted">暂无符合条件的{{ marketType === 'module' ? '模块' : '员工' }}，请调整搜索条件或切换分类。</div>

        <div v-if="loadError && filteredMods.length" class="state-msg store-load-warn">
          <i class="fa fa-info-circle"></i> {{ loadError }}
        </div>

        <div v-if="filteredMods.length" class="store-grid">
          <article
            v-for="(mod, index) in filteredMods"
            :key="(mod.pkg_id || mod.id || 'mod') + '-' + index"
            class="store-card"
            :class="{ 'store-card--installed': mod.is_installed }"
          >
            <template v-if="isMobileViewport">
              <div class="mod-card-compact">
                <div class="store-card__avatar">
                  <i :class="modIconClass(mod)" aria-hidden="true"></i>
                  <img v-if="isEmployeePackItem(mod)" :src="avatarFor(mod)" alt="" loading="lazy" @error="hideAvatar" />
                </div>
                <div class="mod-compact-body">
                  <h3 class="card-title">{{ mod.name }}</h3>
                  <p class="card-desc">{{ mod.description || '暂无描述' }}</p>
                </div>
                <button type="button" class="btn btn-primary btn-sm" :disabled="mod.installationInProgress" @click="onMobileUse(mod)">
                  {{ mod.installationInProgress ? '处理中' : mod.is_installed ? '打开' : '安装' }}
                </button>
              </div>
            </template>
            <template v-else>
              <header class="store-card__head">
                <div class="store-card__avatar">
                  <i :class="modIconClass(mod)" aria-hidden="true"></i>
                  <img v-if="isEmployeePackItem(mod)" :src="avatarFor(mod)" alt="" loading="lazy" @error="hideAvatar" />
                </div>
                <div class="store-card__titles">
                  <div class="store-card__title-line">
                    <h3 class="card-title">{{ mod.name }}</h3>
                    <span v-if="mod.is_installed" class="tag tag-owned">已安装</span>
                  </div>
                  <p class="card-meta">
                    <template v-if="mod.author && mod.author !== '—'">{{ mod.author }} · </template>v{{ mod.version }}
                  </p>
                </div>
              </header>
              <p class="card-desc">{{ mod.description || '暂无描述' }}</p>
              <div class="card-badges">
                <span v-if="isEmployeePackItem(mod)" class="tag tag-employee-pack">AI 员工</span>
                <span v-else class="tag">模块</span>
                <span v-if="collectionLabel(mod)" class="tag tag-industry">{{ collectionLabel(mod) }}</span>
                <span class="tag tag-free">免费</span>
              </div>
              <footer class="card-footer">
                <div class="card-footer__actions">
                  <button
                    v-if="!mod.is_installed"
                    type="button"
                    class="btn btn-primary btn-sm"
                    :disabled="mod.installationInProgress"
                    @click="installMod(mod)"
                  >
                    <i class="fa fa-download"></i>
                    {{ mod.installationInProgress ? '安装中…' : '安装' }}
                  </button>
                  <button
                    v-else
                    type="button"
                    class="btn btn-secondary btn-sm"
                    :disabled="mod.uninstallationInProgress"
                    @click="uninstallMod(mod)"
                  >
                    <i class="fa fa-trash"></i>
                    {{ mod.uninstallationInProgress ? '卸载中…' : '卸载' }}
                  </button>
                  <button type="button" class="btn btn-ghost btn-sm" @click="viewDetails(mod)">详情</button>
                  <button
                    v-if="hasUpdate(mod)"
                    type="button"
                    class="btn btn-warning btn-sm"
                    :disabled="mod.updateInProgress"
                    @click="updateMod(mod)"
                  >
                    {{ mod.updateInProgress ? '更新中…' : '更新' }}
                  </button>
                </div>
              </footer>
            </template>
          </article>
        </div>
      </main>
    </div>

    <Modal v-if="selectedMod" :model-value="true" :title="selectedMod.name" @close="selectedMod = null">
      <ModDetails :mod="selectedMod" @install="installMod" @uninstall="uninstallMod" />
    </Modal>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { ElSegmented } from 'element-plus'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-segmented.css'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { MOD_STORE_EMPLOYEE_OPTION } from '@/constants/modStoreNavigation'
import Modal from '@/components/Modal.vue'
import ModDetails from './ModDetails.vue'
import { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import {
  HOST_FOUNDATION_EMPLOYEE_PACK_ID,
  STORE_COLLECTION_OFFICE_AUX,
  STORE_COLLECTION_OFFICE_EMPLOYEE,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
  catalogStoreCollection,
} from '@/constants/genericModPack'
import {
  OFFICE_AUX_PACK_1_PKG_IDS,
  OFFICE_EMPLOYEE_PKG_IDS,
} from '@/constants/officeEmployeePack'
import { useModStoreState } from './mod-store/useModStoreState'
import { useModStoreMeta } from './mod-store/useModStoreMeta'
import { useModStoreCatalog } from './mod-store/useModStoreCatalog'
import { useModStoreActions } from './mod-store/useModStoreActions'
import { useModStoreOnboarding } from './mod-store/useModStoreOnboarding'
import { employeeAvatarUrl } from '@/utils/employeeAvatar'

export default {
  name: 'ModStore',
  components: {
    Modal,
    ModDetails,
    ElSegmented,
  },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const modsStore = useModsStore()
    const { buildContext: tutorialBuildContext } = useTutorialCatalog()

    const modstoreWebUrl = String(import.meta.env.VITE_MODSTORE_WEB_URL || 'https://xiu-ci.com/market/workbench/unified').replace(/\/$/, '')
    const marketBaseUrl = String(import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com/market').replace(/\/$/, '')

    // 逻辑按领域拆分到 mod-store/ 下的 composables，此处仅组装（对外 vm 表面与拆分前一致）
    const state = useModStoreState()
    const meta = useModStoreMeta(state, { marketBaseUrl })
    const catalog = useModStoreCatalog(state)
    const actions = useModStoreActions(state, { modsStore, catalog, meta })
    const onboarding = useModStoreOnboarding(state, { route, router, tutorialBuildContext, catalog, actions })

    const {
      allMods,
      filteredMods,
      catalogSnapshot,
      searchQuery,
      filterInstalled,
      sortBy,
      marketType,
      currentTab,
      loading,
      refreshing,
      fromCache,
      loadError,
      selectedMod,
      deliverableOk,
      bootstrapBusy,
      oneClickProgress,
      isMobileViewport,
      missingModHint,
      setupMobileViewport,
      disposeMobileViewport,
    } = state

    const {
      modIconClass,
      collectionLabel,
      enterpriseLayerLabel,
      enterpriseLayerTagStyle,
      enterpriseModLabel,
      isEmployeePackItem,
      marketItemKindLabel,
      marketModUrl,
      resolveEnterpriseStack,
    } = meta

    const {
      storeNavTabs,
      isMarketCollectionTab,
      mainListTitle,
      warmCatalogSnapshot,
      loadMods,
      searchMods,
      applyFilters,
    } = catalog

    const marketTypes = [{ label: '模块', value: 'module' }, MOD_STORE_EMPLOYEE_OPTION]
    const employeeNavTabs = storeNavTabs.filter((tab) => tab.id !== 'industry_mod')
    const employeeTabs = new Set(employeeNavTabs.map((tab) => tab.id))
    let lastEmployeeTab = 'host_foundation'
    const selectionFromRoute = () => {
      const tab = typeof route.query.tab === 'string' ? route.query.tab.trim() : ''
      const type = route.query.type === 'module' || (route.query.type !== 'employee' && tab === 'industry_mod') ? 'module' : 'employee'
      return { type, tab: type === 'module' ? (tab === 'installed' ? tab : 'industry_mod') : employeeTabs.has(tab) ? tab : 'host_foundation' }
    }
    const selectCatalog = (type, tab) => {
      marketType.value = type
      if (type === 'employee') lastEmployeeTab = tab
      selectedMod.value = null
      return catalog.switchTab(tab)
    }
    const switchTab = (tab) => {
      const type = tab === 'industry_mod' ? 'module' : 'employee'
      void router.replace({ query: { ...route.query, type, tab } })
      return selectCatalog(type, tab)
    }
    const switchMarketType = (type) => switchTab(type === 'module' ? 'industry_mod' : lastEmployeeTab)
    watch(() => [route.query.type, route.query.tab], () => {
      const selection = selectionFromRoute()
      if (selection.type !== marketType.value || selection.tab !== currentTab.value) {
        void selectCatalog(selection.type, selection.tab)
      }
    })

    const {
      installMod,
      uninstallMod,
      updateMod,
      hasUpdate,
      viewDetails,
      onMobileUse,
    } = actions

    const {
      onboardingBanner,
      refreshDeliverable,
      finishOnboardingFromStore,
      goBackFromStore,
      runOneClickInstallAndOnboard,
      oneClickPendingCount,
      oneClickCtaLabel,
    } = onboarding

    const installedCount = computed(() => filteredMods.value.filter((mod) => mod.is_installed).length)

    const hotKeywords = ['生产日报', 'BOM', '8D', 'SPC', 'OEE', '隐患', 'ISO9001', '供应商']
    // 首页推荐位展示「员工包」，而不是把单个员工当整合包陈列。
    const FEATURED_PACKS = [
      {
        tab: 'office',
        label: '办公员工包',
        description: 'Excel / CSV / PDF / PPT / Word 读取与生成',
        icon: 'fa-file-text-o',
        collection: STORE_COLLECTION_OFFICE_EMPLOYEE,
        expected: OFFICE_EMPLOYEE_PKG_IDS.length,
      },
      {
        tab: 'office_aux',
        label: '办公员工附属包1',
        description: '量化报告与可视化图表',
        icon: 'fa-bar-chart',
        collection: STORE_COLLECTION_OFFICE_AUX,
        expected: OFFICE_AUX_PACK_1_PKG_IDS.length,
      },
      {
        tab: 'workflow',
        label: '工作流员工',
        description: '按业务流程编排的执行员工',
        icon: 'fa-users',
        collection: STORE_COLLECTION_WORKFLOW_EMPLOYEE,
      },
    ]
    const featuredPacks = computed(() => {
      const source = catalogSnapshot.value.length ? catalogSnapshot.value : allMods.value
      return FEATURED_PACKS.map((pack) => {
        const members = source.filter((mod) => isEmployeePackItem(mod) && catalogStoreCollection(mod) === pack.collection)
        return {
          ...pack,
          // 办公包不在市场全量目录里，按包定义给出成员数；其余按目录统计。
          total: pack.expected || members.length,
          installed: members.filter((mod) => mod.is_installed).length,
        }
      })
    })

    function applyQuickSearch(keyword) {
      searchQuery.value = keyword
      void searchMods()
    }

    function avatarFor(mod) {
      return employeeAvatarUrl(String(mod.pkg_id || mod.id || mod.name || ''))
    }

    function hideAvatar(event) {
      const target = event.target
      if (target instanceof HTMLImageElement) target.style.display = 'none'
    }

    onMounted(() => {
      const selection = selectionFromRoute()
      marketType.value = selection.type
      currentTab.value = selection.tab
      if (selection.type === 'employee') lastEmployeeTab = selection.tab
      filterInstalled.value = currentTab.value === 'installed'
      if (marketType.value === 'employee') void warmCatalogSnapshot()
      void loadMods(false)
      void refreshDeliverable()
      void resolveEnterpriseStack()
      setupMobileViewport()
    })

    onBeforeUnmount(() => {
      disposeMobileViewport()
    })

    return {
      route,
      modstoreWebUrl,
      marketBaseUrl,
      marketType,
      marketTypes,
      switchMarketType,
      onboardingBanner,
      missingModHint,
      deliverableOk,
      bootstrapBusy,
      oneClickProgress,
      oneClickPendingCount,
      oneClickCtaLabel,
      runOneClickInstallAndOnboard,
      finishOnboardingFromStore,
      goBackFromStore,
      allMods,
      filteredMods,
      installedCount,
      hotKeywords,
      featuredPacks,
      applyQuickSearch,
      avatarFor,
      hideAvatar,
      searchQuery,
      filterInstalled,
      sortBy,
      currentTab,
      loading,
      refreshing,
      fromCache,
      loadError,
      isMarketCollectionTab,
      selectedMod,
      loadMods,
      searchMods,
      applyFilters,
      switchTab,
      installMod,
      uninstallMod,
      updateMod,
      hasUpdate,
      viewDetails,
      onMobileUse,
      isMobileViewport,
      marketModUrl,
      collectionLabel,
      enterpriseLayerLabel,
      enterpriseLayerTagStyle,
      enterpriseModLabel,
      isEmployeePackItem,
      marketItemKindLabel,
      HOST_FOUNDATION_EMPLOYEE_PACK_ID,
      storeNavTabs,
      employeeNavTabs,
      mainListTitle,
      modIconClass,
    }
  },
}
</script>

<style scoped src="./mod-store/mod-store.css"></style>
