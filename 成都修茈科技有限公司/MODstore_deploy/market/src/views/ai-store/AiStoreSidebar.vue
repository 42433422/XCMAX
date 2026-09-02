<script setup lang="ts">
// 拆分自 AiStoreView.vue 模板（原第 27–182 行）；模板逐字迁移，事件改为 emits，行为不变。
import EmployeePackTypeIcon from '../../components/store/EmployeePackTypeIcon.vue'
import { OFFICE_AUX_PACK_1_PKG_IDS, OFFICE_EMPLOYEE_PKG_IDS } from '../../constants/officeEmployeePack'
import { artifactLabel, licenseScopeLabel, materialCategoryLabel, type StoreNavId, type StoreNavTab } from './aiStoreTypes'

defineProps<{
  storeNav: StoreNavId
  tabs: StoreNavTab[]
  showAdvancedFilters: boolean
  advancedFilterCount: number
  isPackCollectionNav: boolean
  filters: {
    industry: string
    artifact: string
    materialCategory: string
    licenseScope: string
    securityLevel: string
  }
  facetIndustries: string[]
  facetArtifacts: string[]
  facetMaterialCategories: string[]
  facetLicenseScopes: string[]
  appliedQ: string
  bundleDownloading: boolean
}>()

defineEmits<{
  (e: 'select-nav', id: StoreNavId): void
  (e: 'toggle-advanced'): void
  (e: 'set-material-category', v: string): void
  (e: 'set-artifact', v: string): void
  (e: 'set-industry', v: string): void
  (e: 'set-license-scope', v: string): void
  (e: 'set-security-level', v: string): void
  (e: 'reset-filters'): void
  (e: 'download-office-bundle'): void
  (e: 'download-host-foundation-pack'): void
  (e: 'download-workflow-bundle'): void
}>()
</script>

<template>
  <aside class="store-sidebar" aria-label="分类与筛选">
    <nav class="store-nav" aria-label="商品分类">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        class="store-nav__item"
        :class="{ active: storeNav === tab.id }"
        @click="$emit('select-nav', tab.id)"
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
        @click="$emit('download-office-bundle')"
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
        @click="$emit('download-host-foundation-pack')"
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
        @click="$emit('download-workflow-bundle')"
      >
        {{ bundleDownloading ? '打包中…' : '一键下载合集' }}
      </button>
    </div>

    <button
      type="button"
      class="store-adv-toggle"
      :aria-expanded="showAdvancedFilters"
      @click="$emit('toggle-advanced')"
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
          <button type="button" class="chip" :class="{ active: !filters.materialCategory }" @click="$emit('set-material-category', '')">全部</button>
          <button
            v-for="cat in facetMaterialCategories"
            :key="'cat-' + cat"
            type="button"
            class="chip"
            :class="{ active: filters.materialCategory === cat }"
            @click="$emit('set-material-category', cat)"
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
          <button type="button" class="chip" :class="{ active: !filters.artifact }" @click="$emit('set-artifact', '')">全部</button>
          <button
            v-for="art in facetArtifacts"
            :key="'art-' + art"
            type="button"
            class="chip"
            :class="{ active: filters.artifact === art }"
            @click="$emit('set-artifact', art)"
          >
            {{ artifactLabel(art) }}
          </button>
        </div>
      </div>
      <div class="filter-block">
        <span class="filter-label">行业</span>
        <div class="chip-row">
          <button type="button" class="chip" :class="{ active: !filters.industry }" @click="$emit('set-industry', '')">全部</button>
          <button
            v-for="ind in facetIndustries"
            :key="'ind-' + ind"
            type="button"
            class="chip"
            :class="{ active: filters.industry === ind }"
            @click="$emit('set-industry', ind)"
          >
            {{ ind }}
          </button>
        </div>
      </div>
      <div class="filter-block">
        <span class="filter-label">授权</span>
        <div class="chip-row">
          <button type="button" class="chip" :class="{ active: !filters.licenseScope }" @click="$emit('set-license-scope', '')">全部</button>
          <button
            v-for="scope in facetLicenseScopes"
            :key="'lic-' + scope"
            type="button"
            class="chip"
            :class="{ active: filters.licenseScope === scope }"
            @click="$emit('set-license-scope', scope)"
          >
            {{ licenseScopeLabel(scope) }}
          </button>
        </div>
      </div>
      <div class="filter-block">
        <span class="filter-label">保密级</span>
        <div class="chip-row">
          <button type="button" class="chip" :class="{ active: !filters.securityLevel }" @click="$emit('set-security-level', '')">全部</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'personal' }" @click="$emit('set-security-level', 'personal')">个人</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'enterprise' }" @click="$emit('set-security-level', 'enterprise')">企业</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'confidential' }" @click="$emit('set-security-level', 'confidential')">保密</button>
        </div>
      </div>
      <button v-if="advancedFilterCount || appliedQ" type="button" class="btn btn-text btn-block" @click="$emit('reset-filters')">清除筛选</button>
    </div>
  </aside>
</template>

<style scoped src="./ai-store.css"></style>
