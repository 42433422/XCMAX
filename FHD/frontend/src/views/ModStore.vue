<template>
  <div class="mod-store store-page">
    <header class="store-top">
      <button type="button" class="store-back" @click="goBackFromStore">
        <i class="fa fa-arrow-left" aria-hidden="true"></i>
        <span>返回 AI 生态</span>
      </button>
      <div class="store-top__row">
        <div class="store-top__brand">
          <p class="store-eyebrow">XCAGI · 能力库</p>
          <h1 class="store-title">AI 员工市场</h1>
          <p class="store-sub">浏览并安装 AI 员工包；分类与修茈 AI 市场同源，安装后自动上岗至企业四部门编制。</p>
        </div>
        <form class="store-search" @submit.prevent="searchMods">
          <input v-model="searchQuery" type="search" class="store-search__input" placeholder="搜索名称、包名…" />
          <button type="submit" class="btn btn-primary store-search__btn">
            <i class="fa fa-search"></i>
            搜索
          </button>
        </form>
      </div>
    </header>

    <div v-if="onboardingBanner" class="onboarding-banner">
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
        type="button"
        class="btn btn-primary btn-sm store-toolbar__cta"
        data-tour="store-one-click-install"
        :disabled="bootstrapBusy"
        @click="runOneClickInstallAndOnboard"
      >
        <i class="fa fa-bolt" :class="{ 'fa-spin': bootstrapBusy }" aria-hidden="true"></i>
        {{ oneClickCtaLabel }}
      </button>
      <span v-if="oneClickProgress" class="store-toolbar__hint muted">{{ oneClickProgress }}</span>
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

    <div class="store-shell" data-tour="store-shell">
      <aside class="store-sidebar" aria-label="分类与筛选">
        <nav class="store-nav" aria-label="商品分类">
          <button
            v-for="tab in storeNavTabs"
            :key="tab.id"
            type="button"
            class="store-nav__item"
            :class="{ active: currentTab === tab.id }"
            :data-tour="tab.id === 'office' ? 'store-nav-office' : undefined"
            @click="switchTab(tab.id)"
          >
            <i :class="['fa', tab.icon, 'store-nav__icon']" aria-hidden="true"></i>
            <span class="store-nav__label">{{ tab.label }}</span>
          </button>
        </nav>

        <div class="store-sidebar-filters">
          <label class="store-filter-check">
            <input type="checkbox" v-model="filterInstalled" @change="applyFilters" />
            仅显示已安装
          </label>
          <select v-model="sortBy" class="store-sort" @change="applyFilters">
            <option value="name">按名称</option>
            <option value="downloads">按下载量</option>
            <option value="rating">按评分</option>
            <option value="created_at">最新上架</option>
          </select>
        </div>
      </aside>

      <main class="store-main" aria-labelledby="store-results-heading">
        <div class="store-main__bar">
          <div>
            <h2 id="store-results-heading" class="store-main__title">{{ mainListTitle }}</h2>
            <p v-if="!loading || filteredMods.length" class="store-main__meta">
              共 {{ filteredMods.length }} 件
              <span v-if="refreshing" class="store-sync-hint"> <i class="fa fa-refresh fa-spin" aria-hidden="true"></i> 同步中… </span>
              <span v-else-if="fromCache" class="store-cache-hint muted">已缓存</span>
            </p>
          </div>
        </div>

        <div v-if="loading && !filteredMods.length" class="state-msg">
          <i class="fa fa-spinner fa-spin"></i> 加载中…
          <span v-if="isMarketCollectionTab(currentTab)" class="store-load-hint muted">
            正在拉取修茈 AI 市场目录；若已有本地目录会先显示，后台继续同步。
          </span>
        </div>

        <div v-else-if="loadError && !filteredMods.length" class="state-msg store-load-error">
          <i class="fa fa-exclamation-triangle"></i> {{ loadError }}
        </div>

        <div v-else-if="filteredMods.length === 0" class="state-msg muted">暂无商品，可切换左侧分类或调整搜索条件。</div>

        <div v-if="loadError && filteredMods.length" class="state-msg store-load-warn">
          <i class="fa fa-info-circle"></i> {{ loadError }}
        </div>

        <div v-if="filteredMods.length" class="store-grid">
          <article v-for="mod in filteredMods" :key="mod.id" class="store-card" :class="{ 'store-card--installed': mod.is_installed }">
            <template v-if="isMobileViewport">
              <div class="mod-card-compact">
                <div class="store-card__avatar"><i :class="modIconClass(mod)"></i></div>
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
                <div class="store-card__avatar"><i :class="modIconClass(mod)"></i></div>
                <div class="store-card__titles">
                  <div class="store-card__title-line">
                    <h3 class="card-title">{{ mod.name }}</h3>
                    <span v-if="mod.is_installed" class="tag tag-owned">已安装</span>
                  </div>
                  <p class="card-meta">{{ mod.pkg_id || mod.id }} · v{{ mod.version }} · {{ mod.author || 'Unknown' }}</p>
                </div>
              </header>
              <p class="card-desc">{{ mod.description || '暂无描述' }}</p>
              <div class="card-badges">
                <span v-if="isEmployeePackItem(mod)" class="tag tag-employee-pack">员工包</span>
                <span v-if="enterpriseModLabel(mod)" class="tag tag-enterprise-mod">{{ enterpriseModLabel(mod) }}</span>
                <span v-if="enterpriseLayerLabel(mod)" class="tag tag-enterprise-layer" :style="enterpriseLayerTagStyle(mod)">{{
                  enterpriseLayerLabel(mod)
                }}</span>
                <span v-if="collectionLabel(mod)" class="tag tag-industry">{{ collectionLabel(mod) }}</span>
                <span class="tag" :class="mod.source === 'remote' ? 'tag-remote' : 'tag-local'">
                  {{ mod.source === 'remote' ? '远端 Catalog' : '本机' }}
                </span>
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
                  <a
                    v-if="mod.source === 'remote'"
                    class="btn btn-ghost btn-sm"
                    :href="marketModUrl(mod)"
                    target="_blank"
                    rel="noopener noreferrer"
                    >网页查看</a
                  >
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

    <Modal v-if="selectedMod" :title="selectedMod.name" @close="selectedMod = null">
      <ModDetails :mod="selectedMod" @install="installMod" @uninstall="uninstallMod" />
    </Modal>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import Modal from '@/components/Modal.vue'
import ModDetails from './ModDetails.vue'
import { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import { HOST_FOUNDATION_EMPLOYEE_PACK_ID } from '@/constants/genericModPack'
import { useModStoreState } from './mod-store/useModStoreState'
import { useModStoreMeta } from './mod-store/useModStoreMeta'
import { useModStoreCatalog } from './mod-store/useModStoreCatalog'
import { useModStoreActions } from './mod-store/useModStoreActions'
import { useModStoreOnboarding } from './mod-store/useModStoreOnboarding'

export default {
  name: 'ModStore',
  components: {
    Modal,
    ModDetails,
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
      searchQuery,
      filterInstalled,
      sortBy,
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
      switchTab,
    } = catalog

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

    onMounted(() => {
      const tabQuery = typeof route.query.tab === 'string' ? route.query.tab.trim() : ''
      const allowedTabs = new Set([
        'all',
        'host_foundation',
        'office',
        'office_aux',
        'workflow',
        'ai_employee',
        'industry_mod',
        'installed',
      ])
      currentTab.value = allowedTabs.has(tabQuery) ? tabQuery : 'host_foundation'
      void warmCatalogSnapshot()
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
      mainListTitle,
      modIconClass,
    }
  },
}
</script>

<style scoped src="./mod-store/mod-store.css"></style>
