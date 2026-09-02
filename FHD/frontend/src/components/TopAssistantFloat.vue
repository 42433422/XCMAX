<template>
  <div class="assistant-float-root">
    <button
      ref="floatToggleRef"
      class="assistant-float-toggle"
      type="button"
      data-tour="assistant-float-toggle"
      @click="toggleOpen"
      :title="isOpen ? '收起副窗' : '打开副窗'"
      :aria-expanded="isOpen ? 'true' : 'false'"
      aria-controls="xcagi-assistant-float-panel"
      :class="{ pulse: hasUnreadPush }"
    >
      <i class="fa fa-comments-o" aria-hidden="true"></i>
      <span>副窗</span>
    </button>

    <div v-if="popupNotice" class="assistant-popup-notice" @click="openFromNotice">
      <div class="assistant-popup-title">{{ popupNotice.title }}</div>
      <div class="assistant-popup-desc">{{ popupNotice.description }}</div>
      <div class="assistant-popup-hint">点击查看</div>
    </div>

    <Teleport to="body">
    <div
      v-if="isOpen"
      id="xcagi-assistant-float-panel"
      ref="assistantPanelRef"
      class="assistant-float-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="xcagi-assistant-float-title"
      data-tutorial-spotlight="assistant-panel"
      tabindex="-1"
      @keydown="onAssistantPanelKeydown"
    >
      <div class="assistant-float-header">
        <div id="xcagi-assistant-float-title" class="assistant-title">助手副窗</div>
        <button type="button" class="assistant-close" aria-label="关闭副窗" data-tour="assistant-float-close" @click="closeAssistantPanelUi">
          ×
        </button>
      </div>

      <AssistantTabsBar
        :active-tab="activeTab"
        @select="activeTab = $event"
        @open-tutorial="openTutorialTab"
      />

      <div v-if="activeTab === 'push'" class="assistant-body">
        <div v-if="pushFeed.length === 0" class="assistant-empty">暂无推送</div>
        <div v-else class="push-list">
          <div v-for="item in pushFeed" :key="item.id" class="push-item">
            <div class="push-item-title">{{ item.title }}</div>
            <div class="push-item-desc">{{ item.description }}</div>
          </div>
        </div>
      </div>

      <div v-else-if="activeTab === 'assistant'" class="assistant-body" data-tutorial-assistant-body>
        <div class="assistant-block">
          <div class="assistant-block-title">{{ uiText.queryTitle.value }}</div>
          <div class="assistant-block-desc">{{ uiText.queryDescription.value }}</div>
        </div>
        <div class="product-search-row">
          <input
            v-model.trim="productKeyword"
            type="text"
            :placeholder="uiText.queryPlaceholder.value"
            @keydown.enter.prevent="searchProducts"
          >
          <button type="button" class="btn btn-primary btn-sm" @click="searchProducts" :disabled="loadingProducts">
            查询
          </button>
        </div>
        <div class="product-result">
          <div v-if="loadingProducts" class="assistant-empty">查询中...</div>
          <div v-else-if="productRows.length === 0" class="assistant-empty">{{ productEmptyMessage }}</div>
          <div v-else class="product-list">
            <div v-for="row in productRows" :key="row.id" class="product-item">
              <div class="product-item-head">
                <span class="product-id-label">编号 {{ row.id }}</span>
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-name-' + row.id">{{ uiText.nameLabel.value }}</label>
                <input :id="'pf-name-' + row.id" v-model.trim="row.name" type="text" class="product-input" :placeholder="uiText.nameLabel.value">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-model-' + row.id">{{ uiText.modelLabel.value }}</label>
                <input :id="'pf-model-' + row.id" v-model.trim="row.model_number" type="text" class="product-input" :placeholder="uiText.modelLabel.value">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-price-' + row.id">{{ productPriceLabel }}</label>
                <input :id="'pf-price-' + row.id" v-model.number="row.price" type="number" step="0.01" class="product-input" :placeholder="productPriceLabel">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-unit-' + row.id">{{ productCategoryLabel }}/{{ productUnitLabel }}</label>
                <input :id="'pf-unit-' + row.id" v-model.trim="row.unit" type="text" class="product-input" :placeholder="`${productCategoryLabel}、${productUnitLabel}`">
              </div>
              <div class="product-actions">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  @click="saveProductRow(row)"
                  :disabled="savingProductId === row.id"
                >
                  {{ savingProductId === row.id ? '保存中...' : '保存修改' }}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="assistant-divider"></div>
        <div class="assistant-block">
          <div class="assistant-block-title">关联表网格布局</div>
          <div class="assistant-block-desc">
            <template v-if="linkedSheetName">
              当前：Sheet {{ linkedSheetIndex }}（{{ linkedSheetName }}）
            </template>
            <template v-else>
              尚未关联 Sheet，请先在聊天页点击关联工作表按钮
            </template>
          </div>
          <div class="assistant-grid-actions">
            <button type="button" class="btn btn-secondary btn-sm" @click="triggerGridReadFromChat">
              调用上传并提取读取网格
            </button>
          </div>
          <div v-if="linkedGridData && Array.isArray(linkedGridData.rows) && linkedGridData.rows.length" class="linked-grid-preview">
            <div class="linked-grid-caption">业务对接真实网格缩略预览</div>
            <div ref="topScrollRef" class="linked-grid-top-scroll" @scroll="onTopScroll">
              <div class="linked-grid-top-scroll-inner" :style="{ width: `${topScrollInnerWidth}px` }"></div>
            </div>
            <ExcelPreview
              ref="excelPreviewRef"
              :title="`Sheet ${linkedSheetIndex || ''}（${linkedSheetName || ''}）真实网格`"
              :fields="linkedSheetFields"
              :sample-rows="linkedSheetSampleRows"
              :grid-data="linkedGridData"
              :rows="24"
              :columns="16"
            />
          </div>
          <div v-else class="assistant-empty">当前关联表暂无可展示网格（可先分析Excel或上传并提取）。</div>
        </div>
      </div>

      <AssistantStarterPackTab
        v-else-if="activeTab === 'starterPack'"
        :presets="starterPackPresets"
        @select="onStarterPackItemClick"
      />

      <AssistantTutorialTab
        v-else-if="activeTab === 'tutorial'"
        :show-advanced-courses="showAdvancedCourses"
        :tutorial-tracks="tutorialTracks"
        :advanced-track-hint="advancedTrackHint"
        @back="showAdvancedCourses = false"
        @close="isOpen = false"
        @start="startTutorialGuide"
      />
    </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useRouter } from 'vue-router';
import { useTutorialStore } from '@/stores/tutorial';
import { useTutorialCatalog } from '@/composables/useTutorialCatalog';
import { useModsStore } from '@/stores/mods';
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees';

import { useWorkflowModsRuntimeContext } from '@/composables/useWorkflowModsRuntimeContext';
import { resolveLabel } from '@/utils/workflowEmployeeRegistry';
import { useIndustryUiText } from '@/composables/useIndustryUiText';

import { resolveWorkflowVisualizationLocation } from '@/utils/workflowNav';
import { useWorkflowPanoramaNavVisible } from '@/composables/useWorkflowPanoramaNavVisible';
import { useEnterpriseScopedWorkflowRegistry } from '@/composables/useEnterpriseScopedWorkflowRegistry';
import { syncEnterpriseWorkflowRegistry } from '@/utils/syncEnterpriseWorkflowRegistry';
import ExcelPreview from '@/components/template/ExcelPreview.vue';

import AssistantTabsBar from './top-assistant-float/AssistantTabsBar.vue';
import AssistantStarterPackTab from './top-assistant-float/AssistantStarterPackTab.vue';
import AssistantTutorialTab from './top-assistant-float/AssistantTutorialTab.vue';
import { useAssistantFloatState } from './top-assistant-float/useAssistantFloatState';
import { useAssistantPanelActions } from './top-assistant-float/useAssistantPanelActions';
import { useAssistantProductSearch } from './top-assistant-float/useAssistantProductSearch';
import { useAssistantLinkedGrid } from './top-assistant-float/useAssistantLinkedGrid';
import { useAssistantChatAndNav } from './top-assistant-float/useAssistantChatAndNav';
import { useAssistantTutorialLaunch } from './top-assistant-float/useAssistantTutorialLaunch';
import { useAssistantFloatEvents } from './top-assistant-float/useAssistantFloatEvents';

const router = useRouter();
const tutorialStore = useTutorialStore();
const { tutorialTracks, advancedTrackHint, buildContext: tutorialBuildContext } = useTutorialCatalog();
const modsStore = useModsStore();
const uiText = useIndustryUiText();
const productPriceLabel = computed(() => String(uiText.priceLabel?.value || '价格'));
const productCategoryLabel = computed(() => String(uiText.categoryLabel?.value || '分类'));
const productUnitLabel = computed(() => String(uiText.unitLabel?.value || '单位'));
const { modWorkflowEmployeesActive } = useWorkflowModsRuntimeContext();
const workflowAiEmployeesStore = useWorkflowAiEmployeesStore();
const { enabled: workflowEmployeesEnabled, registryLoaded: workflowRegistryLoaded } = storeToRefs(workflowAiEmployeesStore);
const { scopedRegistryEntries } = useEnterpriseScopedWorkflowRegistry();

// 状态与行为按领域拆分到 top-assistant-float/ 下的 composables，此处仅组装（对外 vm 表面与拆分前一致）
const state = useAssistantFloatState();
const panel = useAssistantPanelActions(state, { tutorialStore });
const productSearch = useAssistantProductSearch(state, { uiText, recordOperation: panel.recordOperation });
const chatNav = useAssistantChatAndNav({
  router,
  recordOperation: panel.recordOperation,
  closeAssistantPanelUi: panel.closeAssistantPanelUi,
});
const linkedGrid = useAssistantLinkedGrid(state, {
  router,
  fillChatInputWithRetry: chatNav.fillChatInputWithRetry,
});
const tutorialLaunch = useAssistantTutorialLaunch(state, {
  router,
  tutorialStore,
  tutorialBuildContext,
  recordOperation: panel.recordOperation,
});
const floatEvents = useAssistantFloatEvents(state, {
  tutorialStore,
  recordOperation: panel.recordOperation,
  searchProducts: productSearch.searchProducts,
  focusToggleAfterClose: panel.focusToggleAfterClose,
  addPush: panel.addPush,
});

const {
  isOpen,
  activeTab,
  showAdvancedCourses,
  floatToggleRef,
  assistantPanelRef,
  topScrollRef,
  excelPreviewRef,
  pushFeed,
  popupNotice,
  hasUnreadPush,
  operationHistory,
  productKeyword,
  productRows,
  loadingProducts,
  lastProductSearchQuery,
  productSearchFailed,
  productSearchErrorText,
  lastProductSearchTotal,
  savingProductId,
  linkedSheetName,
  linkedSheetIndex,
  linkedGridData,
  linkedSheetFields,
  linkedSheetSampleRows,
  topScrollInnerWidth,
} = state;

const {
  FLOAT_TAB_ORDER,
  FLOAT_TAB_DATA_ID,
  MAX_PUSH_ITEMS,
  MAX_OPERATION_LOG,
  focusToggleAfterClose,
  closeAssistantPanelUi,
  onDocumentKeydownCapture,
  recordOperation,
  toggleOpen,
  openTutorialTab,
  onAssistantPanelKeydown,
  addPush,
  openFromNotice,
  clearNoticeTimer,
} = panel;

const {
  PRODUCT_SEARCH_TIMEOUT_MS,
  searchProducts,
  productEmptyMessage,
  saveProductRow,
} = productSearch;

const {
  FILL_CHAT_MAX_ATTEMPTS,
  FILL_CHAT_RETRY_MS,
  tryFillChatInput,
  fillChatInputWithRetry,
  onStarterPackItemClick,
  navigateToSubjectPage,
} = chatNav;

const {
  applyExcelSheetContext,
  syncTopScrollMetrics,
  onTopScroll,
  onExcelScroll,
  onExcelSheetContext,
  triggerGridReadFromChat,
} = linkedGrid;

const { startHostOnboardingGuide, startTutorialGuide } = tutorialLaunch;

const {
  onAssistantPush,
  onOpenAssistantFloat,
  onRestoreFloatState,
  onTutorialSetAssistantTab,
  onCloseAssistantFloat,
} = floatEvents;

const starterPackPresets = uiText.starterPackPresets;

const workflowEmployeeDefs = computed(() => {
  const i18nResolver = (key) => {
    if (key === 'shipmentOrderName') return `${uiText.shipmentOrderName.value}管理 AI 员工`;
    return key;
  };
  return scopedRegistryEntries.value.map((entry) => ({
    id: entry.id,
    label: resolveLabel(entry, i18nResolver),
  }));
});

const workflowVisualizationLocation = resolveWorkflowVisualizationLocation();
const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible();

const workflowPanoramaLinkTitle = computed(() =>
  modWorkflowEmployeesActive.value
    ? '查看固定六类与扩展工作流的执行逻辑与过程'
    : '查看固定六类工作流的执行逻辑与过程'
);

const coreWorkflowEnabled = (id) =>
  !!workflowEmployeesEnabled.value?.[id];

const toggleWorkflowEmployee = (id) => {
  workflowAiEmployeesStore.toggle(id);
};

watch(
  () => [isOpen.value, activeTab.value],
  ([open, tab]) => {
    if (open && tab === 'tutorial') {
      queueMicrotask(() => {
        window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'));
      });
    }
  }
);

onMounted(() => {
  window.addEventListener('keydown', onDocumentKeydownCapture, true);
  window.addEventListener('xcagi:assistant-push', onAssistantPush);
  window.addEventListener('xcagi:open-assistant-float', onOpenAssistantFloat);
  window.addEventListener('xcagi:close-assistant-float', onCloseAssistantFloat);
  window.addEventListener('xcagi:excel-sheet-context', onExcelSheetContext);
  window.addEventListener('xcagi:tutorial:restore-float', onRestoreFloatState);
  window.addEventListener('xcagi:tutorial:set-assistant-tab', onTutorialSetAssistantTab);
  syncTopScrollMetrics();
  if (modsStore.clientModsUiOff) {
    workflowAiEmployeesStore.stripModWorkflowEmployeeKeys();
  } else {
    void syncEnterpriseWorkflowRegistry(modsStore.modsForWorkflowUi);
  }
});

watch(
  () => modsStore.modsForWorkflowUi,
  (list) => {
    if (modsStore.clientModsUiOff) return;
    void syncEnterpriseWorkflowRegistry(list);
  },
  { deep: true }
);

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onDocumentKeydownCapture, true);
  window.removeEventListener('xcagi:assistant-push', onAssistantPush);
  window.removeEventListener('xcagi:open-assistant-float', onOpenAssistantFloat);
  window.removeEventListener('xcagi:close-assistant-float', onCloseAssistantFloat);
  window.removeEventListener('xcagi:excel-sheet-context', onExcelSheetContext);
  window.removeEventListener('xcagi:tutorial:restore-float', onRestoreFloatState);
  window.removeEventListener('xcagi:tutorial:set-assistant-tab', onTutorialSetAssistantTab);
  clearNoticeTimer();
  const root = excelPreviewRef.value?.$el || excelPreviewRef.value;
  const excelContainer = root?.querySelector?.('.excel-container');
  if (excelContainer) {
    excelContainer.removeEventListener('scroll', onExcelScroll);
  }
});

watch(() => linkedGridData.value, () => {
  syncTopScrollMetrics();
});
</script>

<style scoped src="./top-assistant-float/top-assistant-float.css"></style>
