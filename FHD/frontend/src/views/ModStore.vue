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
          <input
            v-model="searchQuery"
            type="search"
            class="store-search__input"
            placeholder="搜索名称、包名…"
          />
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
      <button
        v-if="route.query.onboarding === '1'"
        type="button"
        class="btn btn-ghost"
        @click="finishOnboardingFromStore"
      >
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
      <span v-else-if="!deliverableOk" class="store-toolbar__hint muted">
        将先装齐宿主基础员工包，再安装当前分类员工
      </span>
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
              <span v-if="refreshing" class="store-sync-hint">
                <i class="fa fa-refresh fa-spin" aria-hidden="true"></i> 同步中…
              </span>
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

        <div v-else-if="filteredMods.length === 0" class="state-msg muted">
          暂无商品，可切换左侧分类或调整搜索条件。
        </div>

        <div v-if="loadError && filteredMods.length" class="state-msg store-load-warn">
          <i class="fa fa-info-circle"></i> {{ loadError }}
        </div>

        <div v-if="filteredMods.length" class="store-grid">
          <article
            v-for="mod in filteredMods"
            :key="mod.id"
            class="store-card"
            :class="{ 'store-card--installed': mod.is_installed }"
          >
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
                <span
                  v-if="enterpriseLayerLabel(mod)"
                  class="tag tag-enterprise-layer"
                  :style="enterpriseLayerTagStyle(mod)"
                >{{ enterpriseLayerLabel(mod) }}</span>
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
                  >网页查看</a>
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
import { ref, onMounted, onBeforeUnmount, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { apiFetch } from '@/utils/apiBase';
import { fetchMarketCatalog, installHostFoundation, reloadEmployeePacks } from '@/api/modStore';
import {
  catalogStoreCollection,
  HOST_FOUNDATION_EMPLOYEE_PACK_ID,
  isHostFoundationEmployeePackId,
  readBuildEdition,
  STORE_COLLECTION_HOST_FOUNDATION,
  STORE_COLLECTION_INDUSTRY_MOD,
  STORE_COLLECTION_OFFICE_AUX,
  STORE_COLLECTION_OFFICE_EMPLOYEE,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
} from '@/constants/genericModPack';
import {
  isOfficeAuxPack1Pkg,
  isOfficeEmployeePkg,
  OFFICE_AUX_PACK_1_COLLECTION,
  OFFICE_EMPLOYEE_COLLECTION,
} from '@/constants/officeEmployeePack';
import { markProductFlowCompleted, markHostPackAcknowledged } from '@/constants/productFlow';
import { fetchDeliverableStatus } from '@/utils/platformShellApi';
import { useModsStore } from '@/stores/mods';
import Modal from '@/components/Modal.vue';
import ModDetails from './ModDetails.vue';
import { appAlert, appConfirm } from '@/utils/appDialog';
import {
  promptAdvancedTutorialAfterInstall,
  resolveRouteNameFromPath,
} from '@/tutorial/promptAdvancedTutorial';
import { useTutorialCatalog } from '@/composables/useTutorialCatalog';
import {
  buildMarketCatalogCacheKey,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from '@/utils/marketCatalogCache';
import {
  resolveEnterpriseOrgLayerForCatalogItem,
} from '@/constants/enterpriseWorkflowEstablishment';
import { autoOnboardInstalledMarketItem } from '@/utils/workflowEmployeeOnboard';
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi';

export default {
  name: 'ModStore',
  components: {
    Modal,
    ModDetails,
  },
  setup() {
    const route = useRoute();
    const router = useRouter();
    const modstoreWebUrl = String(
      import.meta.env.VITE_MODSTORE_WEB_URL ||
        'https://xiu-ci.com/market/workbench/unified',
    ).replace(/\/$/, '');
    const marketBaseUrl = String(
      import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com/market',
    ).replace(/\/$/, '');
    const modsStore = useModsStore();
    const enterpriseStackLabel = ref('');
    const { buildContext: tutorialBuildContext } = useTutorialCatalog();

    function refreshHostMods() {
      void modsStore.refresh().catch((e) => {
        console.warn('[ModStore] modsStore.refresh:', e);
      });
    }

    const allMods = ref([]);
    const filteredMods = ref([]);
    const searchQuery = ref('');
    const filterInstalled = ref(false);
    const sortBy = ref('name');
    const currentTab = ref('all');
    const loading = ref(false);
    const refreshing = ref(false);
    const fromCache = ref(false);
    const loadError = ref('');
    const catalogSnapshot = ref([]);
    let catalogSnapshotPromise = null;
    const selectedMod = ref(null);
    const deliverableOk = ref(true);
    const missingModIds = ref([]);
    const bootstrapBusy = ref(false);
    const oneClickProgress = ref('');
    const isMobileViewport = ref(false);
    let mobileMedia = null;

    const onMobileViewportChange = (event) => {
      isMobileViewport.value = event.matches;
    };

    const onboardingBanner = computed(
      () => route.query.onboarding === '1' || deliverableOk.value === false,
    );
    const missingModHint = computed(() =>
      missingModIds.value.length ? missingModIds.value.join(', ') : '',
    );

    const onboardingRedirect = () => {
      const redirect = typeof route.query.redirect === 'string' ? route.query.redirect.trim() : '';
      return redirect.startsWith('/') ? redirect : '/';
    };

    const storeNavTabs = [
      { id: 'all', label: '全部商品', icon: 'fa-th-large' },
      { id: 'host_foundation', label: '宿主基础员工', icon: 'fa-cubes' },
      { id: 'office', label: '办公员工包', icon: 'fa-file-text-o' },
      { id: 'office_aux', label: '办公员工附属包1', icon: 'fa-bar-chart' },
      { id: 'workflow', label: '工作流员工', icon: 'fa-users' },
      { id: 'ai_employee', label: 'AI 员工', icon: 'fa-user-circle' },
      { id: 'industry_mod', label: '行业扩展', icon: 'fa-industry' },
      { id: 'installed', label: '已安装', icon: 'fa-check-circle' },
    ];

    const MARKET_TAB_QUERY = {
      host_foundation: {
        collection: 'host_foundation',
        artifact: 'employee_pack',
        material_category: 'ai_employee',
      },
      office: {
        collection: OFFICE_EMPLOYEE_COLLECTION,
        artifact: 'employee_pack',
        material_category: 'ai_employee',
      },
      office_aux: {
        collection: OFFICE_AUX_PACK_1_COLLECTION,
        artifact: 'employee_pack',
        material_category: 'ai_employee',
      },
      workflow: {
        collection: STORE_COLLECTION_WORKFLOW_EMPLOYEE,
        artifact: 'mod',
        material_category: 'ai_employee',
      },
      ai_employee: {
        material_category: 'ai_employee',
      },
    };

    const isMarketCollectionTab = (tab) => Boolean(MARKET_TAB_QUERY[tab]);

    const mainListTitle = computed(() => {
      if (currentTab.value === 'host_foundation') return '宿主基础能力（预装员工）';
      if (currentTab.value === 'office') return '办公员工包';
      if (currentTab.value === 'office_aux') return '办公员工附属包1';
      if (currentTab.value === 'workflow') return '工作流员工';
      if (currentTab.value === 'ai_employee') return 'AI 员工';
      if (currentTab.value === 'industry_mod') return '行业扩展';
      if (currentTab.value === 'installed') return '已安装';
      return '全部商品';
    });

    const modIconClass = (mod) => {
      const sc = catalogStoreCollection(mod);
      if (sc === STORE_COLLECTION_HOST_FOUNDATION) return 'fa fa-cubes';
      if (sc === STORE_COLLECTION_OFFICE_EMPLOYEE) return 'fa fa-file-text-o';
      if (sc === STORE_COLLECTION_OFFICE_AUX) return 'fa fa-bar-chart';
      if (sc === STORE_COLLECTION_WORKFLOW_EMPLOYEE) return 'fa fa-users';
      if (sc === STORE_COLLECTION_INDUSTRY_MOD) return 'fa fa-industry';
      return mod?.icon || 'fa fa-puzzle-piece';
    };

    const refreshDeliverable = async () => {
      try {
        const st = await fetchDeliverableStatus(true);
        deliverableOk.value = st.deliverable !== false;
        missingModIds.value = st.missing_mod_ids || [];
      } catch {
        deliverableOk.value = true;
      }
    };

    const onboardDestinationForTab = (tab) => {
      const redirect = onboardingRedirect();
      if (redirect !== '/') return redirect;
      if (tab === 'office' || tab === 'office_aux') return '/workflow-employee-space';
      if (tab === 'workflow') return '/employee-workspace';
      return '/';
    };

    const finishOnboardingFromStore = (dest) => {
      markProductFlowCompleted();
      markHostPackAcknowledged();
      void router.replace(dest || onboardDestinationForTab(currentTab.value));
    };

    const goBackFromStore = () => {
      const redirect = typeof route.query.redirect === 'string' ? route.query.redirect.trim() : '';
      if (redirect.startsWith('/')) {
        void router.push(redirect);
        return;
      }
      if (typeof window !== 'undefined' && window.history.length > 1) {
        router.back();
        return;
      }
      void router.push({ name: 'ai-ecosystem' });
    };

    const installModSilent = async (mod) => {
      if (isHostFoundationEmployeePackId(mod.pkg_id || mod.id)) {
        const edition = readBuildEdition();
        const data = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic');
        return { success: Boolean(data.success), message: data.message || '' };
      }
      const payload = {
        pkg_id: mod.pkg_id || mod.id,
        version: mod.version,
        package_file: mod.package_file,
        activate: true,
        verify_signature: false,
      };
      const response = await apiFetch('/api/mod-store/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      const ok = Boolean(data.success);
      if (ok) {
        try {
          await autoOnboardInstalledMarketItem(mod);
        } catch (e) {
          console.warn('[ModStore] silent auto onboard failed:', e);
        }
      }
      return {
        success: ok,
        message: data.error || data.detail || data.message || '',
      };
    };

    const ensureHostFoundationIfNeeded = async () => {
      if (deliverableOk.value) return;
      oneClickProgress.value = '正在安装宿主基础员工包…';
      const edition = readBuildEdition();
      const res = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic');
      await refreshDeliverable();
      refreshHostMods();
      if (!res.success || !deliverableOk.value) {
        throw new Error(res.message || '宿主基础员工包未装齐，请检查本机 mods 种子目录。');
      }
    };

    const completePackOnboard = async (tab) => {
      markProductFlowCompleted();
      markHostPackAcknowledged();
      const label = mainListTitle.value || '员工包';
      const dest = onboardDestinationForTab(tab);
      const promptResult = await promptAdvancedTutorialAfterInstall({
        router,
        buildContext: tutorialBuildContext.value,
        message: `${label}已装齐，正在入驻。\n\n是否现在观看进阶教程，快速熟悉菜单与智能对话？`,
        returnContext: { routeName: resolveRouteNameFromPath(router, dest) },
      });
      if (promptResult === 'started') return;
      if (promptResult === 'already_completed') {
        await appAlert(`${label}已装齐，正在入驻…`);
      }
      await router.replace(dest);
    };

    const runOneClickInstallAndOnboard = async () => {
      const tab = currentTab.value;

      if (tab === 'all') {
        await appAlert('请先在左侧选择具体员工包分类（如办公员工包），再一键安装并入驻。');
        return;
      }

      if (oneClickPendingCount.value === 0) {
        finishOnboardingFromStore();
        return;
      }

      bootstrapBusy.value = true;
      const errors = [];
      try {
        await ensureHostFoundationIfNeeded();

        if (tab === 'host_foundation') {
          await completePackOnboard(tab);
          return;
        }

        const targets = filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed);
        if (!targets.length) {
          await completePackOnboard(tab);
          return;
        }

        const label = mainListTitle.value || '员工包';
        for (let i = 0; i < targets.length; i += 1) {
          const mod = targets[i];
          oneClickProgress.value = `正在安装 ${label} ${i + 1}/${targets.length}：${mod.name}`;
          mod.installationInProgress = true;
          try {
            const res = await installModSilent(mod);
            if (res.success) {
              mod.is_installed = true;
            } else {
              errors.push(`${mod.name}：${res.message || '安装失败'}`);
            }
          } catch (e) {
            errors.push(`${mod.name}：${e instanceof Error ? e.message : '安装失败'}`);
          } finally {
            mod.installationInProgress = false;
          }
        }

        await loadMods(false);
        refreshHostMods();
        await refreshDeliverable();

        if (tab === 'office' || tab === 'office_aux') {
          try {
            await reloadEmployeePacks();
          } catch (e) {
            console.warn('[ModStore] reloadEmployeePacks:', e);
          }
        }

        const remaining = filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed);
        if (!remaining.length && !errors.length) {
          await completePackOnboard(tab);
        } else if (!errors.length && remaining.length) {
          await appAlert(
            `${label} 仍有 ${remaining.length} 项未安装，请点「刷新目录」后重试或单独安装。`,
          );
        } else {
          const detail = errors.slice(0, 6).join('\n');
          await appAlert(
            `部分员工安装失败${remaining.length ? `，仍有 ${remaining.length} 项未装` : ''}：\n${detail}${
              errors.length > 6 ? '\n…' : ''
            }`,
          );
        }
      } catch (e) {
        await appAlert(e instanceof Error ? e.message : '装包失败');
      } finally {
        bootstrapBusy.value = false;
        oneClickProgress.value = '';
      }
    };

    const collectionLabel = (mod) => {
      const sc = catalogStoreCollection(mod);
      if (sc === STORE_COLLECTION_HOST_FOUNDATION) return '宿主基础员工';
      if (sc === STORE_COLLECTION_OFFICE_EMPLOYEE) return '办公员工包';
      if (sc === STORE_COLLECTION_OFFICE_AUX) return '办公附属包1';
      if (sc === STORE_COLLECTION_WORKFLOW_EMPLOYEE) return '工作流员工';
      if (sc === STORE_COLLECTION_INDUSTRY_MOD) return '行业扩展';
      return '';
    };

    const enterpriseLayerForMod = (mod) => resolveEnterpriseOrgLayerForCatalogItem(mod || {});

    const enterpriseLayerLabel = (mod) => {
      const layer = enterpriseLayerForMod(mod);
      return layer ? `${layer.code} ${layer.label}` : '';
    };

    const isEmployeePackItem = (mod) =>
      String(mod?.artifact || '').trim().toLowerCase() === 'employee_pack';

    const enterpriseModLabel = (mod) => {
      const art = String(mod?.artifact || '').trim().toLowerCase();
      if (art !== 'employee_pack' && art !== 'mod') return '';
      const label = enterpriseStackLabel.value;
      return label ? `企业 Mod：${label}` : '';
    };

    const marketItemKindLabel = (mod) =>
      isEmployeePackItem(mod) ? '员工' : '扩展 Mod';

    const installSuccessMessage = (mod, onboardNote = '') => {
      const kind = marketItemKindLabel(mod);
      return `${kind} ${mod.name} 安装成功！${onboardNote}`;
    };

    const enterpriseLayerTagStyle = (mod) => {
      const layer = enterpriseLayerForMod(mod);
      if (!layer) return {};
      return {
        color: layer.color,
        borderColor: `${layer.color}66`,
        background: `${layer.color}14`,
      };
    };

    const refineMarketItems = (items, tab) => {
      if (tab === 'office') {
        return items.filter((m) => isOfficeEmployeePkg(m.pkg_id || m.id));
      }
      if (tab === 'office_aux') {
        return items.filter((m) => isOfficeAuxPack1Pkg(m.pkg_id || m.id));
      }
      return items;
    };

    const filterByCollectionTab = (mods) => {
      if (currentTab.value === 'host_foundation') {
        return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_HOST_FOUNDATION);
      }
      if (currentTab.value === 'office') {
        return mods.filter((m) => isOfficeEmployeePkg(m.pkg_id || m.id));
      }
      if (currentTab.value === 'office_aux') {
        return mods.filter((m) => isOfficeAuxPack1Pkg(m.pkg_id || m.id));
      }
      if (currentTab.value === 'workflow') {
        return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_WORKFLOW_EMPLOYEE);
      }
      if (currentTab.value === 'ai_employee') {
        return mods.filter((m) => {
          const sc = catalogStoreCollection(m);
          return sc !== STORE_COLLECTION_INDUSTRY_MOD;
        });
      }
      if (currentTab.value === 'industry_mod') {
        return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_INDUSTRY_MOD);
      }
      return mods;
    };

    const oneClickPendingCount = computed(() => {
      const tab = currentTab.value;
      if (tab === 'all' || tab === 'installed') return 0;
      if (tab === 'host_foundation') {
        return deliverableOk.value ? 0 : 1;
      }
      return filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed).length;
    });
    const oneClickCtaLabel = computed(() => {
      if (currentTab.value === 'all') return '一键安装并入驻';
      const pending = oneClickPendingCount.value;
      if (pending === 0) return '完成入驻';
      return `一键安装并入驻 (${pending})`;
    });

    const loadCatalogAvailable = async () => {
      const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 });
      const data = await response.json();
      if (!data.success) {
        throw new Error(data.message || data.error || '获取本地目录失败');
      }
      const rows = data.data.available || [];
      catalogSnapshot.value = rows;
      return rows;
    };

    const warmCatalogSnapshot = () => {
      if (catalogSnapshot.value.length) {
        return Promise.resolve(catalogSnapshot.value);
      }
      if (!catalogSnapshotPromise) {
        catalogSnapshotPromise = loadCatalogAvailable().catch((err) => {
          catalogSnapshotPromise = null;
          console.warn('[ModStore] catalog snapshot prefetch failed:', err);
          return [];
        });
      }
      return catalogSnapshotPromise;
    };

    const applyCatalogWarmStart = (tab) => {
      if (!catalogSnapshot.value.length) return false;
      const warmed = refineMarketItems(
        filterByCollectionTab([...catalogSnapshot.value]),
        tab,
      );
      if (!warmed.length) return false;
      allMods.value = warmed;
      applyFilters();
      if (filteredMods.value.length > 0) {
        loading.value = false;
        refreshing.value = true;
        return true;
      }
      return false;
    };

    const fetchMarketTabRemote = async (tab) => {
      const query = MARKET_TAB_QUERY[tab];
      if (!query) return false;
      const result = await fetchMarketCatalog({
        ...query,
        q: searchQuery.value.trim() || undefined,
        limit: 80,
      });
      const items = refineMarketItems(result.items || [], tab);
      allMods.value = items;
      writeMarketCatalogCache(
        buildMarketCatalogCacheKey(tab, searchQuery.value),
        tab,
        items,
      );
      fromCache.value = false;
      loadError.value = '';
      return true;
    };

    const loadMarketTab = async (tab, { force = false } = {}) => {
      const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value);
      const cached = !force ? readMarketCatalogCache(cacheKey) : null;

      if (cached?.items?.length) {
        allMods.value = cached.items;
        applyFilters();
        fromCache.value = true;
        if (isMarketCatalogCacheFresh(cached) && !force) {
          loadError.value = '';
          return true;
        }
      } else {
        fromCache.value = false;
        await warmCatalogSnapshot();
        applyCatalogWarmStart(tab);
      }

      try {
        return await fetchMarketTabRemote(tab);
      } catch (error) {
        console.warn('[ModStore] market-catalog failed, fallback to /catalog:', error);
        try {
          await loadCatalogAvailable();
          allMods.value = refineMarketItems(
            filterByCollectionTab([...catalogSnapshot.value]),
            tab,
          );
          if (allMods.value.length) {
            loadError.value =
              '市场分类接口较慢或暂不可用，已显示本地目录。可点「刷新目录」重试。';
            return true;
          }
          throw error;
        } catch (fallbackError) {
          if (filteredMods.value.length) {
            loadError.value =
              '市场同步失败，当前为缓存/本地目录。可点「刷新目录」重试。';
            return true;
          }
          loadError.value =
            error instanceof Error
              ? error.message
              : fallbackError instanceof Error
                ? fallbackError.message
                : '加载市场目录失败，请检查网络后刷新。';
          allMods.value = [];
          return false;
        }
      }
    };

    const loadMods = async (force = false) => {
      const tab = currentTab.value;
      const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value);
      const cached = !force && isMarketCollectionTab(tab)
        ? readMarketCatalogCache(cacheKey)
        : null;
      const canShowInstant = Boolean(cached?.items?.length) || catalogSnapshot.value.length;

      loading.value = !canShowInstant;
      refreshing.value = canShowInstant;
      loadError.value = '';
      if (force) fromCache.value = false;

      try {
        if (isMarketCollectionTab(tab)) {
          await loadMarketTab(tab, { force });
          applyFilters();
          return;
        }

        const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 });
        const data = await response.json();

        if (data.success) {
          catalogSnapshot.value = data.data.available || [];
          allMods.value = catalogSnapshot.value;
          applyFilters();
        }
      } catch (error) {
        console.error('Failed to load mods:', error);
        if (!filteredMods.value.length) {
          loadError.value = error instanceof Error ? error.message : '加载目录失败';
        }
      } finally {
        loading.value = false;
        refreshing.value = false;
      }
    };

    const searchMods = async () => {
      loading.value = true;
      refreshing.value = false;
      try {
        const tab = currentTab.value;
        if (isMarketCollectionTab(tab)) {
          await loadMarketTab(tab, { force: true });
          applyFilters();
          return;
        }

        if (!searchQuery.value.trim()) {
          await loadMods();
          return;
        }

        const params = new URLSearchParams({
          q: searchQuery.value,
          installed: filterInstalled.value,
          limit: 50,
        });

        const response = await apiFetch(`/api/mod-store/search?${params}`);
        const data = await response.json();

        if (data.success) {
          allMods.value = data.data || [];
          applyFilters();
        }
      } catch (error) {
        console.error('Search failed:', error);
      } finally {
        loading.value = false;
      }
    };

    const applyFilters = () => {
      let mods = [...allMods.value];

      if (filterInstalled.value) {
        mods = mods.filter(mod => mod.is_installed);
      }

      mods = filterByCollectionTab(mods);

      if (sortBy.value === 'downloads') {
        mods.sort((a, b) => (b.total_downloads || b.download_count || 0) - (a.total_downloads || a.download_count || 0));
      } else if (sortBy.value === 'rating') {
        mods.sort((a, b) => (b.avg_rating || 0) - (a.avg_rating || 0));
      } else if (sortBy.value === 'created_at') {
        mods.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      } else {
        mods.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      }

      filteredMods.value = mods;
    };

    const switchTab = async (tab) => {
      currentTab.value = tab;
      const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value);
      const cached = isMarketCollectionTab(tab) ? readMarketCatalogCache(cacheKey) : null;
      const instant = Boolean(cached?.items?.length);
      loading.value = !instant;
      refreshing.value = instant;

      try {
        if (tab !== 'installed') {
          filterInstalled.value = false;
        }
        if (tab === 'installed') {
          filterInstalled.value = true;
          if (!allMods.value.length) {
            await loadMods(false);
          } else {
            const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 });
            const data = await response.json();
            if (data.success) {
              catalogSnapshot.value = data.data.available || [];
              allMods.value = catalogSnapshot.value;
            }
          }
          applyFilters();
        } else {
          await loadMods(false);
        }
      } catch (error) {
        console.error('Failed to switch tab:', error);
      } finally {
        loading.value = false;
        refreshing.value = false;
      }
    };

    const installMod = async (mod) => {
      mod.installationInProgress = true;
      try {
        let data;
        if (isHostFoundationEmployeePackId(mod.pkg_id || mod.id)) {
          const edition = readBuildEdition();
          data = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic');
        } else {
          const payload = {
            pkg_id: mod.pkg_id || mod.id,
            version: mod.version,
            package_file: mod.package_file,
            activate: true,
            verify_signature: false,
          };
          const response = await apiFetch('/api/mod-store/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          data = await response.json();
        }

        if (data.success) {
          mod.is_installed = true;
          await loadMods();
          refreshHostMods();
          let onboardNote = '';
          try {
            const {
              onboardedIds,
              plannerRefreshed,
              enterpriseStackLabel: stackLabel,
            } = await autoOnboardInstalledMarketItem(mod);
            if (onboardedIds.length) {
              onboardNote = `，已上岗至企业 Mod「${stackLabel}」`;
            } else if (plannerRefreshed && isEmployeePackItem(mod)) {
              onboardNote = `，已注册至企业 Mod「${stackLabel}」`;
            }
          } catch (e) {
            console.warn('[ModStore] auto onboard failed:', e);
          }
          await appAlert(installSuccessMessage(mod, onboardNote));
        } else {
          await appAlert(`安装失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Installation failed:', error);
        await appAlert('安装失败，请重试');
      } finally {
        mod.installationInProgress = false;
      }
    };

    const uninstallMod = async (mod) => {
      if (!(await appConfirm(`确定要卸载 MOD "${mod.name}" 吗？`, { danger: true }))) {
        return;
      }

      mod.uninstallationInProgress = true;
      try {
        const formData = new FormData();
        formData.append('mod_id', mod.id);
        formData.append('remove_files', 'true');

        const response = await apiFetch('/api/mod-store/uninstall', {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (data.success) {
          mod.is_installed = false;
          await appAlert(`MOD ${mod.name} 卸载成功！`);
          await loadMods();
          refreshHostMods();
        } else {
          await appAlert(`卸载失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Uninstallation failed:', error);
        await appAlert('卸载失败，请重试');
      } finally {
        mod.uninstallationInProgress = false;
      }
    };

    const updateMod = async (mod) => {
      mod.updateInProgress = true;
      try {
        const payload = {
          mod_id: mod.id,
          pkg_id: mod.pkg_id || mod.id,
          version: mod.new_version || mod.version,
          package_file: mod.package_file,
          verify_signature: false,
        };

        const response = await apiFetch('/api/mod-store/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (data.success) {
          mod.version = data.data.version;
          await appAlert(`MOD ${mod.name} 更新成功！`);
          await loadMods();
          refreshHostMods();
        } else {
          await appAlert(`更新失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Update failed:', error);
        await appAlert('更新失败，请重试');
      } finally {
        mod.updateInProgress = false;
      }
    };

    const hasUpdate = (mod) => {
      return mod.is_installed && mod.new_version && mod.new_version !== mod.version;
    };

    const viewDetails = (mod) => {
      selectedMod.value = mod;
    };

    const onMobileUse = async (mod) => {
      if (mod.is_installed) {
        viewDetails(mod);
        return;
      }
      await installMod(mod);
    };

    const marketModUrl = (mod) => {
      const id = encodeURIComponent(mod.pkg_id || mod.id || '');
      return `${marketBaseUrl}/mods/${id}`;
    };

    onMounted(() => {
      const tabQuery = typeof route.query.tab === 'string' ? route.query.tab.trim() : '';
      const allowedTabs = new Set([
        'all',
        'host_foundation',
        'office',
        'office_aux',
        'workflow',
        'ai_employee',
        'industry_mod',
        'installed',
      ]);
      currentTab.value = allowedTabs.has(tabQuery) ? tabQuery : 'host_foundation';
      void warmCatalogSnapshot();
      void loadMods(false);
      void refreshDeliverable();
      void resolveEnterpriseModStack().then((stack) => {
        enterpriseStackLabel.value = stack.stackLabel;
      });
      mobileMedia = window.matchMedia('(max-width: 768px)');
      onMobileViewportChange(mobileMedia);
      if (typeof mobileMedia.addEventListener === 'function') {
        mobileMedia.addEventListener('change', onMobileViewportChange);
      } else if (typeof mobileMedia.addListener === 'function') {
        mobileMedia.addListener(onMobileViewportChange);
      }
    });

    onBeforeUnmount(() => {
      if (!mobileMedia) return;
      if (typeof mobileMedia.removeEventListener === 'function') {
        mobileMedia.removeEventListener('change', onMobileViewportChange);
      } else if (typeof mobileMedia.removeListener === 'function') {
        mobileMedia.removeListener(onMobileViewportChange);
      }
    });

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
    };
  },
};
</script>

<style scoped>
.store-load-hint {
  display: block;
  margin-top: 8px;
  font-size: 13px;
}

.store-load-error {
  color: #b45309;
  line-height: 1.5;
}

.store-load-warn {
  margin-bottom: 12px;
  padding: 12px 16px;
  text-align: left;
  font-size: 13px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
}

.store-sync-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #2563eb;
  font-weight: 500;
}

.store-cache-hint {
  margin-left: 6px;
  font-size: 12px;
}

.mod-store.store-page {
  --layout-max: 1280px;
  --layout-pad-x: 20px;
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 32px;
  background: #f8fafc;
  -webkit-overflow-scrolling: touch;
}

.store-top {
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 0.75rem var(--layout-pad-x) 0.75rem;
  border-bottom: 1px solid #e2e8f0;
  background: linear-gradient(180deg, rgba(219, 234, 254, 0.45) 0%, transparent 100%);
}

.store-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 10px;
  padding: 6px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.store-back:hover {
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
}

.store-top__row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px 24px;
}

.store-eyebrow {
  font-size: 11px;
  color: #2563eb;
  letter-spacing: 0.08em;
  margin: 0 0 4px;
  text-transform: uppercase;
}

.store-title {
  font-size: clamp(20px, 3vw, 26px);
  font-weight: 700;
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.store-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
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
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  font-size: 14px;
  background: #fff;
}

.store-search__btn {
  white-space: nowrap;
}

.store-toolbar {
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 10px var(--layout-pad-x);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.store-toolbar__cta {
  font-weight: 600;
}

.store-toolbar__hint {
  font-size: 13px;
}

.store-toolbar__spacer {
  flex: 1 1 12px;
  min-width: 0;
}

.onboarding-banner {
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 12px var(--layout-pad-x);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.onboarding-banner p {
  margin: 0;
  flex: 1 1 280px;
  color: #1e3a5f;
  font-size: 14px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.store-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 20px;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 16px var(--layout-pad-x) 0;
  align-items: start;
}

.store-sidebar {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.store-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
}

.store-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #475569;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.store-nav__item:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.store-nav__item.active {
  background: #eff6ff;
  color: #1d4ed8;
}

.store-nav__icon {
  width: 16px;
  text-align: center;
  opacity: 0.85;
}

.store-sidebar-filters {
  padding: 12px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.store-filter-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
}

.store-sort {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  font-size: 13px;
  background: #fff;
}

.store-main {
  min-width: 0;
}

.store-main__bar {
  margin-bottom: 14px;
}

.store-main__title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.store-main__meta {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}

.state-msg {
  padding: 48px 16px;
  text-align: center;
  color: #475569;
}

.state-msg.muted {
  color: #94a3b8;
}

.state-msg a {
  color: #2563eb;
}

.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.store-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 16px;
  transition: box-shadow 0.2s, border-color 0.2s, transform 0.2s;
}

.store-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1);
  transform: translateY(-1px);
}

.store-card--installed {
  border-color: #86efac;
  background: linear-gradient(180deg, #f0fdf4 0%, #fff 40%);
}

.store-card__head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.store-card__avatar {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #6366f1);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.store-card__titles {
  min-width: 0;
  flex: 1;
}

.store-card__title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.card-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
  word-break: break-all;
}

.card-desc {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.55;
  color: #475569;
  min-height: 40px;
}

.card-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
}

.tag-employee-pack {
  color: #0f766e;
  background: #ccfbf1;
  border: 1px solid #99f6e4;
  font-weight: 600;
}

.tag-enterprise-mod {
  color: #1d4ed8;
  background: #dbeafe;
  border: 1px solid #93c5fd;
  font-weight: 600;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tag-enterprise-layer {
  font-weight: 600;
  border: 1px solid transparent;
}

.tag-industry {
  background: rgba(99, 102, 241, 0.12);
  color: #4338ca;
}

.tag-owned {
  background: #dcfce7;
  color: #15803d;
}

.tag-remote {
  background: #dbeafe;
  color: #1d4ed8;
}

.tag-local {
  background: #ecfdf5;
  color: #047857;
}

.card-footer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mod-card-compact {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
}

.mod-compact-body {
  min-width: 0;
}

.btn {
  padding: 8px 14px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 12px;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-primary {
  background: #2563eb;
  color: #fff;
}

.btn-secondary {
  background: #ef4444;
  color: #fff;
}

.btn-ghost {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #e2e8f0;
}

.btn-warning {
  background: #f59e0b;
  color: #fff;
}

@media (max-width: 900px) {
  .store-shell {
    grid-template-columns: 1fr;
  }

  .store-sidebar {
    position: static;
  }

  .store-nav {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .store-nav__item {
    width: auto;
    flex: 1 1 auto;
  }

  .store-sidebar-filters {
    display: none;
  }
}

@media (max-width: 768px) {
  .mod-store.store-page {
    padding-bottom: calc(72px + env(safe-area-inset-bottom, 0));
  }

  .store-grid {
    grid-template-columns: 1fr;
  }
}
</style>
