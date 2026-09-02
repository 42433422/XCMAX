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
      <AiStoreSidebar
        :store-nav="storeNav"
        :tabs="storeNavTabsDisplay"
        :show-advanced-filters="showAdvancedFilters"
        :advanced-filter-count="advancedFilterCount"
        :is-pack-collection-nav="isPackCollectionNav"
        :filters="filters"
        :facet-industries="facetIndustries"
        :facet-artifacts="facetArtifacts"
        :facet-material-categories="facetMaterialCategories"
        :facet-license-scopes="facetLicenseScopes"
        :applied-q="appliedQ"
        :bundle-downloading="bundleDownloading"
        @select-nav="setStoreNav"
        @toggle-advanced="showAdvancedFilters = !showAdvancedFilters"
        @set-material-category="setMaterialCategory"
        @set-artifact="setArtifact"
        @set-industry="setIndustry"
        @set-license-scope="setLicenseScope"
        @set-security-level="setSecurityLevel"
        @reset-filters="resetFilters"
        @download-office-bundle="downloadOfficeBundle"
        @download-host-foundation-pack="downloadHostFoundationPack"
        @download-workflow-bundle="downloadWorkflowBundle"
      />

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

        <AiStoreResults
          v-else
          :groups="displayGroups"
          :attach-mod-id="attachModId"
          :attaching-id="attachingId"
          :downloading-id="downloadingId"
          :fav-busy-id="favBusyId"
          :delisting-id="delistingId"
          :is-admin="authStore.isAdmin"
          :saved-revision="savedRevision"
          @attach="attachCardToMod"
          @download="downloadCard"
          @like="toggleLike"
          @save="toggleSaved"
          @delist="delistItem"
        />

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
// 拆分后本文件为组装入口（façade）：逻辑在 ./ai-store/，模板子组件在 ./ai-store/，样式在 ./ai-store/ai-store.css。
import AdminDigestUnlockModal from '../components/admin/AdminDigestUnlockModal.vue'
import { useAdminDigestUnlock } from '../composables/useAdminDigestUnlock'
import AiStoreSidebar from './ai-store/AiStoreSidebar.vue'
import AiStoreResults from './ai-store/AiStoreResults.vue'
import { useAiStoreCatalog } from './ai-store/useAiStoreCatalog'
import { useAiStoreActions } from './ai-store/useAiStoreActions'
import { securityLabel, securityLevelClass } from './ai-store/aiStoreTypes'
import * as aiStoreTypes from './ai-store/aiStoreTypes'

// 顶层 const 保持 wrapper.vm 对拆分前绑定的可访问面一致。
const artifactLabel = aiStoreTypes.artifactLabel
const materialCategoryLabel = aiStoreTypes.materialCategoryLabel
const licenseScopeLabel = aiStoreTypes.licenseScopeLabel
const complianceStatusLabel = aiStoreTypes.complianceStatusLabel
const truncate = aiStoreTypes.truncate
const formatSocialCount = aiStoreTypes.formatSocialCount
const customerServiceLink = aiStoreTypes.customerServiceLink

const {
  loading, err, items, total, storeNav, storeNavTabsDisplay, showAdvancedFilters, bundleDownloading,
  attachModId, mainListTitle, advancedFilterCount, isPackCollectionNav, filters, searchQ, appliedQ,
  facetIndustries, facetArtifacts, facetMaterialCategories, facetLicenseScopes,
  displayGroups, activeTheme, facets, officeAuxNavBadge, refreshOfficeAuxNavBadge,
  router, loadFacets, loadItems,
  applyFilters, setStoreNav, setMaterialCategory, setArtifact, setIndustry, setLicenseScope, setSecurityLevel,
  resetFilters,
} = useAiStoreCatalog()

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

const {
  authStore,
  delistingId, downloadingId, attachingId, favBusyId, savedRevision,
  isItemSaved, toggleLike, downloadCard, attachCardToMod, toggleSaved, delistItem,
  downloadOfficeBundle, downloadWorkflowBundle, downloadHostFoundationPack,
} = useAiStoreActions({
  err, attachModId, router, bundleDownloading, loadItems, loadFacets, ensureAdminDigestUnlocked,
})

defineExpose({ securityLabel, securityLevelClass })
</script>

<style scoped src="./ai-store/ai-store.css"></style>
