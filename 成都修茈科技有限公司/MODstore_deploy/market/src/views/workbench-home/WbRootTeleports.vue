<script setup lang="ts">
import EmployeeSixDimModal from '../../components/workbench/EmployeeSixDimModal.vue'
import PersonalSettings from '../../components/workbench/PersonalSettings.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 1778–1920 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  LLM_CATEGORY_ORDER, employeeSixDimModalOpen, employeeSixDimReport, conversations, activeConversationId, personalSettings,
  personalSettingsOpen, onPersonalSettingsUpdate, convPopoverOpen, pickConversation, convTimeFormat, llmCatalog,
  selectedModel, modelMode, llmDdOpen, llmMobileSheetOpen, currentProviderLabel, modelPickerEnabled,
  categoryLabel, modelsForWorkbenchCategory, toggleLlmDd, pickProvider, pickModel, planDiagramPreviewIdx,
  planDiagramPreviewMountRef, planDiagramPreviewViewportRef, planDiagramPreviewPanStyle, onPlanDiagramPreviewWheel, onPlanDiagramPreviewPointerDown, planDiagramPreviewZoomStep,
  planDiagramPreviewFitView, closePlanDiagramPreview, closeEmployeeSixDimModal,
} = props.wb
</script>

<template>
    <Teleport to="body">
      <div v-if="llmMobileSheetOpen" class="wb-llm-mobile-sheet-backdrop" role="presentation" @click="llmMobileSheetOpen = false" />
      <div
        v-if="llmMobileSheetOpen"
        class="wb-llm-mobile-sheet"
        role="dialog"
        aria-label="模型选择"
        @click.stop
      >
        <div class="wb-llm-mobile-sheet__head">
          <h3 class="wb-llm-mobile-sheet__title">模型</h3>
          <button type="button" class="wb-llm-mobile-sheet__close" aria-label="关闭" @click="llmMobileSheetOpen = false">×</button>
        </div>
        <div class="wb-llm-inline" aria-label="模型选择">
          <div class="wb-mode-segment" role="radiogroup" aria-label="模型模式">
            <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'auto' }" @click="modelMode = 'auto'">Auto</button>
            <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'manual' }" @click="modelMode = 'manual'">自选</button>
          </div>
          <template v-if="modelMode === 'manual' && llmCatalog?.providers?.length">
            <div class="wb-llm-dd">
              <span class="wb-sr-only">厂商</span>
              <button type="button" class="wb-dd-trigger" @click.stop="toggleLlmDd('directProvider')">
                <span class="wb-dd-trigger__text">{{ currentProviderLabel }}</span>
              </button>
              <ul v-show="llmDdOpen === 'directProvider'" class="wb-dd-panel" role="listbox">
                <li
                  v-for="b in llmCatalog.providers"
                  :key="`ms-${b.provider}`"
                  role="option"
                  class="wb-dd-item"
                  @click.stop="pickProvider(b.provider); llmMobileSheetOpen = false"
                >
                  {{ b.label || b.provider }}
                </li>
              </ul>
            </div>
            <div class="wb-llm-dd">
              <button type="button" class="wb-dd-trigger wb-dd-trigger--model" :disabled="!modelPickerEnabled" @click.stop="toggleLlmDd('directModel')">
                <span class="wb-dd-trigger__text">{{ selectedModel || '选择模型' }}</span>
              </button>
              <ul v-show="llmDdOpen === 'directModel' && modelPickerEnabled" class="wb-dd-panel wb-dd-panel--tall" role="listbox">
                <template v-for="cat in LLM_CATEGORY_ORDER" :key="`ms-cat-${cat}`">
                  <template v-if="modelsForWorkbenchCategory(cat).length">
                    <li class="wb-dd-cat" role="presentation">{{ categoryLabel(cat) }}</li>
                    <li
                      v-for="row in modelsForWorkbenchCategory(cat)"
                      :key="`ms-m-${row.id}`"
                      role="option"
                      class="wb-dd-item"
                      @click.stop="pickModel(row.id); llmMobileSheetOpen = false"
                    >
                      {{ row.id }}
                    </li>
                  </template>
                </template>
              </ul>
            </div>
          </template>
        </div>
        <button type="button" class="wb-llm-mobile-sheet__done" @click="llmMobileSheetOpen = false">完成</button>
      </div>
      <div
        v-if="planDiagramPreviewIdx !== null"
        class="wb-plan-diagram-preview-backdrop"
        role="presentation"
        @click.self="closePlanDiagramPreview"
      >
        <div
          class="wb-plan-diagram-preview-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wb-plan-diagram-preview-title"
        >
          <div class="wb-plan-diagram-preview-head">
            <h2 id="wb-plan-diagram-preview-title" class="wb-plan-diagram-preview-title">架构图预览</h2>
            <button
              type="button"
              class="wb-plan-diagram-preview-close"
              aria-label="关闭预览"
              @click="closePlanDiagramPreview"
            >
              ×
            </button>
          </div>
          <div class="wb-plan-diagram-preview-body">
            <div class="wb-plan-diagram-preview-toolbar" @pointerdown.stop>
              <button type="button" class="wb-plan-preview-tool" aria-label="缩小" @click="planDiagramPreviewZoomStep(-1)">−</button>
              <button type="button" class="wb-plan-preview-tool wb-plan-preview-tool--primary" @click="planDiagramPreviewFitView">
                适应窗口
              </button>
              <button type="button" class="wb-plan-preview-tool" aria-label="放大" @click="planDiagramPreviewZoomStep(1)">+</button>
              <span class="wb-plan-preview-hint">滚轮缩放 · 按住左键拖拽平移</span>
            </div>
            <div
              ref="planDiagramPreviewViewportRef"
              class="wb-plan-diagram-preview-viewport"
              @wheel.prevent="onPlanDiagramPreviewWheel"
              @pointerdown="onPlanDiagramPreviewPointerDown"
            >
              <div class="wb-plan-diagram-preview-panlayer" :style="planDiagramPreviewPanStyle">
                <div ref="planDiagramPreviewMountRef" class="wb-plan-diagram-preview-canvas" tabindex="-1" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
    <EmployeeSixDimModal
      :open="employeeSixDimModalOpen"
      :report="employeeSixDimReport"
      @close="closeEmployeeSixDimModal"
    />
    <Teleport to="body">
      <div v-if="convPopoverOpen" class="wb-conv-backdrop" @click="convPopoverOpen = false"></div>
    </Teleport>
    <Teleport to="body">
      <div v-if="convPopoverOpen" class="wb-conv-popover">
        <div class="wb-conv-popover__head">
          <span>对话历史</span>
          <button type="button" @click="convPopoverOpen = false">×</button>
        </div>
        <div class="wb-conv-popover__list">
          <div
            v-for="c in conversations"
            :key="c.id"
            class="wb-conv-item"
            :class="{ 'wb-conv-item--active': c.id === activeConversationId }"
            @click="pickConversation(c.id); convPopoverOpen = false"
          >
            <span class="wb-conv-item__title">{{ c.title || '新对话' }}</span>
            <span class="wb-conv-item__time">{{ convTimeFormat(c.updatedAt) }}</span>
          </div>
        </div>
      </div>
    </Teleport>
    <Teleport to="body">
      <PersonalSettings
        :open="personalSettingsOpen"
        :model-value="personalSettings"
        @close="personalSettingsOpen = false"
        @update:model-value="onPersonalSettingsUpdate"
      />
    </Teleport>
</template>
