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
        <label class="product-field">
          <input v-model="catalog.selected" type="checkbox" data-testid="protected-catalog-select">
          明确选择受保护的独立价格目录（不迁移 ERP，不自动建库）
        </label>
        <p v-if="!catalog.selected">当前为旧 ERP 查询，只读；不能在此修改产品或价格。</p>
        <div class="product-search-row">
          <input
            v-model.trim="productKeyword"
            type="text"
            :placeholder="uiText.queryPlaceholder.value"
            @keydown.enter.prevent="searchProducts"
          >
          <button type="button" class="btn btn-primary btn-sm" @click="searchProducts" :disabled="loadingProducts || catalog.loading">
            查询
          </button>
        </div>
        <div v-if="catalog.selected" class="product-result" data-testid="protected-catalog">
          <p v-if="catalog.loading" role="status">查询受保护目录中...</p>
          <p v-else-if="catalog.error" role="alert">{{ catalog.error }}</p>
          <p v-else-if="!catalog.rows.length">请查询已存在的受保护目录；没有结果不代表旧 ERP 中没有产品。</p>
          <article v-for="row in catalog.rows" :key="row.id" class="product-item">
            <h4>{{ row.name }} · {{ row.model_number }}（编号 {{ row.id }}）</h4>
            <p>客户/采购单位：{{ row.unit }}（只读，不是计价分母）</p>
            <p>当前价格：{{ row.price }} {{ row.currency }}/{{ row.price_unit }}（币种和计价单位只读）</p>
            <p>来源：{{ row.source.source_id }} · 代次 {{ row.source.epoch }}</p>
            <details>
              <summary>价格历史与来源观察（保留原期间，不代表完整历史）</summary>
              <ul>
                <li v-for="h in row.history" :key="h.source_key">
                  {{ catalog.period(h.period_start, h.period_end) }} · {{ h.price }} {{ row.currency }}/{{ row.price_unit }}
                  · {{ h.source_key }} · {{ h.effective ? '有效观察' : '历史观察' }}
                </li>
              </ul>
            </details>
            <fieldset v-if="catalog.draftFor(row.id)" :disabled="!catalog.canEdit(row)">
              <legend>仅修改价格；产品、客户身份不可编辑</legend>
              <label>操作模式
                <select v-model="catalog.draftFor(row.id).action" @change="catalog.selectMode(row, $event.target.value)">
                  <option value="append_price">新增期间价格</option>
                  <option value="correct_price">纠正原期间价格</option>
                </select>
              </label>
              <template v-if="catalog.draftFor(row.id).action === 'append_price'">
                <label>明确起日 <input v-model="catalog.draftFor(row.id).period_start" type="date"></label>
                <label>明确止日 <input v-model="catalog.draftFor(row.id).period_end" type="date"></label>
                <p>新增必须填写真实日期，不能把未标注期间当作今天。</p>
              </template>
              <template v-else>
                <label>选择原期间来源
                  <select :value="catalog.draftFor(row.id).selected_sources[0] || ''" @change="catalog.selectCorrection(row, $event.target.value)">
                    <option value="" disabled>请选择有效来源观察</option>
                    <option v-for="h in row.history.filter(h => h.effective)" :key="h.source_key" :value="h.source_key">
                      {{ catalog.period(h.period_start, h.period_end) }} · {{ h.price }} · {{ h.source_key }}
                    </option>
                  </select>
                </label>
                <p>纠错保留原期间（含未标注），不伪造新日期。同期间来源全部列入审批：</p>
                <ul><li v-for="h in catalog.selectedObservations(row)" :key="h.source_key">{{ h.source_key }} · 原金额 {{ h.price }} · {{ catalog.period(h.period_start, h.period_end) }}</li></ul>
                <p v-if="new Set(catalog.selectedObservations(row).map(h => h.price)).size > 1" role="alert">冲突警告：同期间有不同来源金额，请逐一核对；纠错不删除原观察。</p>
              </template>
              <label>新金额（{{ row.currency }}/{{ row.price_unit }}）<input v-model="catalog.draftFor(row.id).price" type="text" inputmode="decimal"></label>
              <label>变更原因 <input v-model.trim="catalog.draftFor(row.id).reason" type="text" maxlength="500"></label>
              <label><input v-model="catalog.draftFor(row.id).confirmed" type="checkbox">我已核对来源、原金额、新金额及期间，申请此价格变更</label>
              <button type="button" class="btn btn-secondary btn-sm" @click="catalog.submit(row)">提交待审批价格变更</button>
            </fieldset>
            <div v-if="catalog.statusFor(row.id)" role="status">
              <p>{{ catalog.statusFor(row.id)?.message }}</p>
              <p v-if="catalog.statusFor(row.id)?.operation">原操作：{{ catalog.statusFor(row.id)?.operation }}</p>
              <p v-if="catalog.statusFor(row.id)?.runId">原任务：{{ catalog.statusFor(row.id)?.runId }}</p>
              <template v-if="catalog.statusFor(row.id)?.preview">
                <p>原申请：{{ catalog.statusFor(row.id)?.preview?.action === 'correct_price' ? '纠正原期间' : '新增期间' }} · {{ catalog.period(catalog.statusFor(row.id).preview.period_start, catalog.statusFor(row.id).preview.period_end) }}</p>
                <p>新金额 {{ catalog.statusFor(row.id)?.preview?.price }} {{ catalog.statusFor(row.id)?.preview?.currency }}/{{ catalog.statusFor(row.id)?.preview?.price_unit }}；原因：{{ catalog.statusFor(row.id)?.preview?.reason }}</p>
                <ul><li v-for="h in catalog.statusFor(row.id)?.preview?.observations" :key="h.source_key">{{ h.source_key }}：原金额 {{ h.price }} · {{ catalog.period(h.period_start, h.period_end) }}</li></ul>
              </template>
              <button v-if="catalog.statusFor(row.id)?.state !== 'verified'" type="button" :disabled="catalog.busyId !== null" @click="catalog.check(row)">只读核对原操作</button>
              <button v-if="catalog.statusFor(row.id)?.canApprove" type="button" :disabled="catalog.busyId !== null" @click="catalog.check(row, true)">明确批准上述原价格变更</button>
              <button v-if="catalog.statusFor(row.id)?.canReconcile && !catalog.reconciliationFor(row.id)" type="button" :disabled="catalog.busyId !== null" @click="catalog.requestReconciliation(row)">核对并终结原操作…</button>
              <fieldset v-if="catalog.reconciliationFor(row.id)" :disabled="catalog.busyId !== null" data-testid="catalog-reconciliation-confirmation">
                <legend>明确确认核对原操作</legend>
                <p>仅核验并终结原操作 {{ catalog.reconciliationFor(row.id) }}；不会重放价格写入，也不代表当前价格重新保存。取消会保留待核对标记。</p>
                <button type="button" @click="catalog.confirmReconciliation(row)">确认核对并终结此原操作</button>
                <button type="button" @click="catalog.cancelReconciliation()">取消，保留原操作</button>
              </fieldset>
            </div>
          </article>
        </div>
        <div v-else class="product-result">
          <div v-if="loadingProducts" class="assistant-empty">查询中...</div>
          <div v-else-if="productRows.length === 0" class="assistant-empty">{{ productEmptyMessage }}</div>
          <div v-else class="product-list">
            <div v-for="row in productRows" :key="row.id" class="product-item">
              <div class="product-item-head">
                <span class="product-id-label">编号 {{ row.id }}</span>
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-name-' + row.id">{{ uiText.nameLabel.value }}</label>
                <input :id="'pf-name-' + row.id" :value="row.name" readonly type="text" class="product-input" :placeholder="uiText.nameLabel.value">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-model-' + row.id">{{ uiText.modelLabel.value }}</label>
                <input :id="'pf-model-' + row.id" :value="row.model_number" readonly type="text" class="product-input" :placeholder="uiText.modelLabel.value">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-price-' + row.id">{{ productPriceLabel }}</label>
                <input :id="'pf-price-' + row.id" :value="row.price" readonly type="number" step="0.01" class="product-input" :placeholder="productPriceLabel">
              </div>
              <div class="product-field">
                <label class="product-field-label" :for="'pf-unit-' + row.id">{{ productCategoryLabel }}/{{ productUnitLabel }}</label>
                <input :id="'pf-unit-' + row.id" :value="row.unit" readonly type="text" class="product-input" :placeholder="`${productCategoryLabel}、${productUnitLabel}`">
              </div>
              <div class="product-actions">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  @click="submitProductRow(row)"
                  disabled
                >
                  {{ savingProductId === row.id ? '保存中...' : '保存修改' }}
                </button>
                <p>当前数据源的审批和核对链尚未验证，副窗暂不可保存。</p>
                <div v-if="productEditStatus(row.id)" role="status">
                  <p>{{ productEditStatus(row.id).message }}</p>
                  <p v-if="productEditStatus(row.id).runId">原任务：{{ productEditStatus(row.id).runId }}</p>
                  <p v-if="productEditStatus(row.id).state !== 'verified'">请通过可信渠道核对原任务，暂不能在此解除禁止重复提交标记。</p>
                </div>
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
  catalog,
  PRODUCT_SEARCH_TIMEOUT_MS,
  searchProducts,
  productEmptyMessage,
  saveProductRow,
  submitProductRow,
  checkProductRow,
  productEditStatus,
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
    if (!open || tab !== 'assistant') catalog.cancelReconciliation();
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
