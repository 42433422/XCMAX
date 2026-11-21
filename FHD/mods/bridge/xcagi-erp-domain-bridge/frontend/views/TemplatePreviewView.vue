<template>
  <div class="page-view" id="view-template-preview">
    <div class="page-content tpl-library">
      <div class="page-header">
        <h2>模板库</h2>
        <div class="tpl-library__actions">
          <button type="button" class="btn btn-secondary" :disabled="loading" @click="refreshLibrary">
            {{ loading ? '刷新中…' : '刷新' }}
          </button>
          <RouterLink to="/business-docking" class="btn btn-secondary">AI 识别与映射</RouterLink>
          <button type="button" class="btn btn-primary" @click="openCreateModal()">
            <i class="fa fa-plus" aria-hidden="true"></i> 创建模板
          </button>
        </div>
      </div>

      <div v-if="searchKeyword || activeScopeTab !== 'all'" class="tpl-library__actions" role="status">
        <span>当前筛选：{{ searchKeyword || '全部关键词' }} / {{ activeScopeTab }}</span>
        <button type="button" class="btn btn-secondary" data-testid="reset-template-filters" @click="resetLibraryFilters">清除筛选，显示全部模板</button>
      </div>

      <p v-if="error" class="tpl-library__error" role="alert">{{ error }}</p>

      <div class="tpl-library__body">
        <div class="tpl-library__browser">
          <VueFinder
            v-if="!loading"
            :key="libraryVersion"
            id="template-library"
            :driver="driver"
            :config="config"
            :features="features"
            locale="zhCN"
            selection-mode="single"
            selection-filter-type="files"
            @select="onSelect"
            @file-dclick="onFileDclick"
          />
          <div v-else class="tpl-library__loading" role="status">模板加载中…</div>
        </div>

        <aside v-if="selectedTemplate" class="tpl-library__detail" aria-label="模板详情">
          <div class="tpl-detail__head">
            <h3>{{ selectedTemplate.name }}</h3>
            <button type="button" class="tpl-detail__close" aria-label="关闭详情" @click="clearSelection">&times;</button>
          </div>
          <dl class="tpl-detail__meta">
            <dt>分类</dt><dd>{{ getTemplateCategoryLabel(selectedTemplate) }}</dd>
            <dt>业务范围</dt><dd>{{ getTemplateScopeLabel(selectedTemplate) }}</dd>
            <dt>来源</dt><dd>{{ getTemplateSourceLabel(selectedTemplate) }}</dd>
            <dt>文件</dt><dd class="tpl-detail__file">{{ selectedTemplate.filename || selectedTemplate.name }}</dd>
            <template v-if="selectedTemplate.virtual">
              <dt>状态</dt><dd>未配置</dd>
            </template>
            <template v-else-if="isGridTemplateCategory(selectedTemplate)">
              <dt>词条</dt><dd>{{ getTemplateDisplayTermsText(selectedTemplate) || '—' }}</dd>
              <template v-if="getTemplateCoverage(selectedTemplate)">
                <dt>完整度</dt>
                <dd>{{ getTemplateCoverage(selectedTemplate)!.matchedCount }}/{{ getTemplateCoverage(selectedTemplate)!.requiredCount }}</dd>
              </template>
            </template>
          </dl>

          <div class="tpl-detail__actions">
            <button v-if="selectedTemplate.virtual" type="button" class="btn btn-sm btn-success" @click="startCreateForScope(selectedTemplate.business_scope)">快速创建</button>
            <template v-else>
              <button type="button" class="btn btn-sm btn-primary" @click="previewTemplate(selectedTemplate)">预览</button>
              <button type="button" class="btn btn-sm btn-secondary" @click="openTemplateTarget(selectedTemplate)">打开</button>
              <button type="button" class="btn btn-sm btn-secondary" @click="editTemplate(selectedTemplate)">编辑</button>
              <button v-if="selectedTemplate.category === 'excel'" type="button" class="btn btn-sm btn-secondary" @click="openReplaceTemplateDialog(selectedTemplate)">替代到…</button>
              <button v-if="selectedTemplate.preview_data?.reviewed_excel" type="button" class="btn btn-sm btn-secondary" @click="downloadReviewedTemplate(selectedTemplate)">下载清理后的模板</button>
              <button v-if="canDeleteTemplate(selectedTemplate)" type="button" class="btn btn-sm btn-danger" @click="confirmDeleteTemplate(selectedTemplate)">删除</button>
            </template>
          </div>
        </aside>
      </div>
    </div>

    <TpCreateModal :tp="tp" />
    <TpPreviewModal :tp="tp" />
    <TpEditModal :tp="tp" />
    <TpReplaceModal :tp="tp" />
  </div>
</template>

<script setup lang="ts">
import { getCurrentInstance } from 'vue'
import { VueFinder, VueFinderPlugin, zhCN } from '@/components/template/vuefinder'
import TpCreateModal from './template-preview/TpCreateModal.vue'
import TpPreviewModal from './template-preview/TpPreviewModal.vue'
import TpEditModal from './template-preview/TpEditModal.vue'
import TpReplaceModal from './template-preview/TpReplaceModal.vue'
import { assembleTemplatePreview } from './template-preview/assemble'
import { useTpVueFinder } from './template-preview/useTpVueFinder'
import templatePreviewApi from '@/api/templatePreview'
import { appAlert } from '@/utils/appDialog'
import type { TplRecord } from './template-preview/tpTemplateMeta'

defineOptions({ name: 'TemplatePreviewView' })

// VueFinder 通过 app.provide 注入 i18n 选项；未注册插件时 Provider 会在 setup 崩溃。
let vueFinderPluginReady = false
function ensureVueFinderPlugin() {
  if (vueFinderPluginReady) return
  const app = getCurrentInstance()?.appContext.app
  if (!app) return
  app.use(VueFinderPlugin, { i18n: { zhCN }, locale: 'zhCN' })
  vueFinderPluginReady = true
}
ensureVueFinderPlugin()

const tp = assembleTemplatePreview()

const {
  loading, error, refreshTemplates, openCreateModal,
  searchKeyword, activeScopeTab, resetLibraryFilters,
  getTemplateCategoryLabel, getTemplateScopeLabel, getTemplateSourceLabel,
  getTemplateDisplayTermsText, getTemplateCoverage, isGridTemplateCategory,
  canDeleteTemplate, startCreateForScope, previewTemplate, openTemplateTarget,
  editTemplate, openReplaceTemplateDialog, confirmDeleteTemplate,
} = tp

const { driver, config, features, libraryVersion, selectedTemplate, onSelect, onFileDclick } = useTpVueFinder(tp)

async function refreshLibrary() {
  await refreshTemplates()
}

function clearSelection() {
  selectedTemplate.value = null
}

async function downloadReviewedTemplate(tpl: TplRecord) {
  try {
    const response = await templatePreviewApi.downloadReviewedExcel(tpl.id)
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = `${tpl.name || '模板'}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    await appAlert(err instanceof Error ? err.message : '下载失败')
  }
}
</script>

<style scoped src="./template-preview/template-preview.css"></style>
<style scoped>
.tpl-library__actions {
  display: flex;
  gap: 8px;
}
.tpl-library__error {
  margin: 0 0 12px;
  color: #b42318;
}
.tpl-library__body {
  display: flex;
  gap: 16px;
  align-items: stretch;
}
.tpl-library__browser {
  flex: 1 1 auto;
  min-width: 0;
  height: calc(100vh - 240px);
  min-height: 460px;
  border: 1px solid rgba(213, 222, 235, 0.72);
  border-radius: var(--app-radius-md, 12px);
  overflow: hidden;
  background: #fff;
}
.tpl-library__loading {
  padding: 48px;
  text-align: center;
  color: var(--app-text-muted, #64748b);
}
.tpl-library__detail {
  flex: 0 0 300px;
  border: 1px solid rgba(213, 222, 235, 0.72);
  border-radius: var(--app-radius-md, 12px);
  padding: 16px;
  background: #fff;
  align-self: flex-start;
}
.tpl-detail__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.tpl-detail__head h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.4;
  word-break: break-word;
}
.tpl-detail__close {
  border: 0;
  background: transparent;
  font-size: 18px;
  line-height: 1;
  color: #94a3b8;
  cursor: pointer;
}
.tpl-detail__meta {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 6px 8px;
  margin: 14px 0 16px;
  font-size: 12px;
}
.tpl-detail__meta dt {
  color: #94a3b8;
}
.tpl-detail__meta dd {
  margin: 0;
  color: #334155;
  word-break: break-word;
}
.tpl-detail__file {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}
.tpl-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
<style>
/* VueFinder 与宿主面板对齐：中性表面、8px 圆角、宿主字体与主色，避免文件管理器原生外观突兀。 */
.tpl-library__browser .vuefinder {
  --vf-bg-primary: #ffffff;
  --vf-bg-secondary: #f8fafc;
  --vf-bg-tertiary: #f1f5f9;
  --vf-bg-hover: #f1f5f9;
  --vf-bg-selected: #eff6ff;
  --vf-text-primary: #1f2937;
  --vf-text-secondary: #475569;
  --vf-text-tertiary: #94a3b8;
  --vf-border-primary: #e2e8f0;
  --vf-border-secondary: #eef2f7;
  --vf-border-focus: #93c5fd;
  --vf-accent-primary: #0b72d9;
  --vf-accent-secondary: #bfdbfe;
  --vf-interactive-hover: #f1f5f9;
  --vf-interactive-active: #e2e8f0;
  --vf-interactive-focus: #eff6ff;
  font-family: inherit;
  font-size: 13px;
}
.tpl-library__browser .vuefinder__toolbar {
  padding: 6px 10px;
  background: #fff;
  border-bottom: 1px solid #eef2f7;
}
.tpl-library__browser .vuefinder__breadcrumb__path-container {
  padding: 6px 10px;
}
.tpl-library__browser .vuefinder__explorer__container,
.tpl-library__browser .vuefinder__explorer__scroll-content {
  background: #fff;
}
.tpl-library__browser .vuefinder__explorer__item-grid-content {
  border-radius: 10px;
  transition: background 0.12s ease;
}
.tpl-library__browser .vuefinder__explorer__item-grid-content:hover {
  background: #f8fafc;
}
.tpl-library__browser .vuefinder__explorer__item-name {
  color: #334155;
  font-size: 12px;
  line-height: 1.4;
}
.tpl-library__browser .vuefinder__status-bar__wrapper {
  display: none;
}
.tpl-library__browser .vuefinder__treeview__container {
  display: none;
}
.tpl-library__browser .vuefinder__item--readonly,
.tpl-library__browser .vuefinder__item--readonly--left,
.tpl-library__browser .vuefinder__item--readonly--list {
  display: none;
}
.tpl-library__browser .vf-btn,
.tpl-library__browser .vuefinder button {
  border-radius: 8px;
}
</style>
