<template>
  <div class="repo-page">
    <RepositoryHeader
      :authoring-industry-id="authoringIndustryId"
      :industry-presets="industryPresets"
      :header-more-open="headerMoreOpen"
      :purge-library-busy="purgeLibraryBusy"
      @update:authoringIndustryId="authoringIndustryId = $event"
      @persist-industry="persistAuthoringIndustry"
      @open-create="showCreate = true"
      @import="onImport"
      @open-scaffold="openScaffoldModal"
      @toggle-more="headerMoreOpen = !headerMoreOpen"
      @purge="onPurgeFromMenu"
    />

    <div v-if="message" :class="['flash', messageOk ? 'flash-ok' : 'flash-err']">{{ message }}</div>

    <section class="repo-shelf-filters" aria-label="能力货架筛选">
      <input v-model.trim="shelfQ" class="input shelf-search" type="search" placeholder="搜索名称、ID、描述…" />
      <select v-model="shelfIndustry" class="input shelf-select">
        <option value="">全部行业</option>
        <option v-for="p in industryPresets" :key="'shelf-' + p.id" :value="p.id">
          {{ p.name }}
        </option>
      </select>
      <select v-model="shelfStatus" class="input shelf-select">
        <option value="">全部状态</option>
        <option value="primary">主扩展</option>
        <option value="bundle">组合包</option>
        <option value="mod">普通 Mod</option>
      </select>
      <select v-model="shelfVersion" class="input shelf-select">
        <option value="">全部版本</option>
        <option v-for="v in versionOptions" :key="v" :value="v">v{{ v }}</option>
      </select>
      <select v-model="shelfTest" class="input shelf-select">
        <option value="">全部测试结果</option>
        <option value="pass">通过</option>
        <option value="fix">待修正</option>
      </select>
      <select v-model="shelfScope" class="input shelf-select">
        <option value="">全部企业授权</option>
        <option value="assigned">已分配企业</option>
        <option value="unassigned">未配置企业授权</option>
      </select>
      <button v-if="hasActiveShelfFilters" type="button" class="btn btn-sm shelf-clear-btn" @click="clearShelfFilters">清空筛选</button>
    </section>
    <p class="repo-shelf-meta">
      展示 {{ filteredMods.length }} / {{ mods.length }} 个能力
      <template v-if="usageLoadError"> · 启用范围未读取：{{ usageLoadError }}</template>
    </p>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="filteredMods.length" class="mods-grid">
      <RepositoryModCard
        v-for="m in filteredMods"
        :key="m.id"
        :mod="m"
        :menu-open="openCardMenuId === m.id"
        :card-delete-busy="deleteModBusy === modIdForDeleteApi(m)"
        :register-busy="registerBusy"
        :industry-label="modIndustryLabel(m)"
        :usage-text="usageText(m.id)"
        :usage-muted="!usageNames(m.id).length && !usageLoadError"
        @toggle-menu="toggleCardMenu(m.id)"
        @delete="onDeleteFromCardMenu(m)"
        @view="viewMod(m.id)"
        @test="testModInSandbox(m.id)"
        @prefill-employee="(e, idx) => goEmployeePrefill(m.id, e, idx)"
        @register-workflow="registerWorkflowToCatalog(m.id, $event)"
      />
    </div>
    <div v-else class="empty-state">
      <p>{{ mods.length ? '没有符合筛选的能力' : '库中暂无扩展包' }}</p>
      <p v-if="mods.length && hasActiveShelfFilters" class="empty-hint">
        试试
        <button type="button" class="empty-link" @click="clearShelfFilters">清空筛选</button>
        或修改搜索关键词
      </p>
      <p v-else class="empty-hint">
        {{ mods.length ? '调整搜索或筛选条件' : '新建或导入 Mod 开始' }}
      </p>
    </div>

    <!-- AI 脚手架 -->
    <RepositoryScaffoldModal
      v-if="showScaffold"
      :industry-id="scaffoldIndustryId"
      :brief="scaffoldBrief"
      :id-hint="scaffoldIdHint"
      :replace="scaffoldReplace"
      :industry-presets="industryPresets"
      :scaffold-busy="scaffoldBusy"
      @update:industryId="scaffoldIndustryId = $event"
      @update:brief="scaffoldBrief = $event"
      @update:idHint="scaffoldIdHint = $event"
      @update:replace="scaffoldReplace = $event"
      @cancel="showScaffold = false"
      @submit="submitScaffold"
    />

    <!-- 新建 Mod 弹窗 -->
    <RepositoryCreateModal
      v-if="showCreate"
      :name="createName"
      :industry-id="createIndustryId"
      :industry-presets="industryPresets"
      @update:name="createName = $event"
      @update:industryId="createIndustryId = $event"
      @cancel="showCreate = false"
      @create="submitCreate"
    />
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./repository-view/，模板子组件在 ./repository-view/，样式在 ./repository-view/repository-view.css。
import { onMounted, onUnmounted } from 'vue'
import RepositoryHeader from './repository-view/RepositoryHeader.vue'
import RepositoryModCard from './repository-view/RepositoryModCard.vue'
import RepositoryScaffoldModal from './repository-view/RepositoryScaffoldModal.vue'
import RepositoryCreateModal from './repository-view/RepositoryCreateModal.vue'
import { useRepositoryCatalog } from './repository-view/useRepositoryCatalog'
import { useRepositoryActions } from './repository-view/useRepositoryActions'
import * as repositoryTypes from './repository-view/repositoryTypes'

// 顶层 const 保持 wrapper.vm 对拆分前绑定的可访问面一致。
const formatUpdatedAt = repositoryTypes.formatUpdatedAt
const getUsageScene = repositoryTypes.getUsageScene
const modIndustryId = repositoryTypes.modIndustryId
const modShelfStatus = repositoryTypes.modShelfStatus
const modIdFromDisplayName = repositoryTypes.modIdFromDisplayName
const isCreateModConflictError = repositoryTypes.isCreateModConflictError
const libraryFolderForDeleteApi = repositoryTypes.libraryFolderForDeleteApi
const modIdForDeleteApi = repositoryTypes.modIdForDeleteApi
const getBlurb = repositoryTypes.getBlurb
const artifactLabel = repositoryTypes.artifactLabel
const isBundle = repositoryTypes.isBundle
const registerKey = repositoryTypes.registerKey

const {
  industryPresets, mods, loading, message, messageOk, usageLoadError,
  shelfQ, shelfIndustry, shelfStatus, shelfVersion, shelfTest, shelfScope,
  versionOptions, hasActiveShelfFilters, filteredMods,
  modIndustryLabel, usageNames, usageText, clearShelfFilters, flash, load, loadEnterpriseUsage,
} = useRepositoryCatalog()

const {
  authoringIndustryId, createIndustryId, showCreate, createName,
  showScaffold, scaffoldBrief, scaffoldIndustryId, scaffoldIdHint, scaffoldReplace, scaffoldBusy,
  registerBusy, deleteModBusy, purgeLibraryBusy, headerMoreOpen, openCardMenuId,
  persistAuthoringIndustry, toggleCardMenu, onDocumentPointerDown,
  onPurgeFromMenu, onDeleteFromCardMenu, purgeRepoLibraryAndLocalState, deleteModFromLibrary,
  viewMod, testModInSandbox, registerWorkflowToCatalog, goEmployeePrefill,
  openScaffoldModal, submitScaffold, submitCreate, onImport,
} = useRepositoryActions({ flash, load, mods, industryPresets, message })

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  void load()
  void loadEnterpriseUsage()
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<style scoped src="./repository-view/repository-view.css"></style>
