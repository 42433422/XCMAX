<script setup lang="ts">
import { DIRECT_AND_VISION_ACCEPT } from '../../utils/directAttachments'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 1366–1674 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  LLM_CATEGORY_ORDER, wbSidebar, inputRef, planSession, llmMobilePickerSummary, knowledgeUploading,
  knowledgeError, knowledgeFileInputRef, composerIntent, modFrontendEnabled, platformChatMode, directAttachedFiles,
  directVisibleAttachedFiles, directHiddenAttachmentCount, directAttachmentMentions, composerPanelEnter, makeVoicePhase, makeVoiceBtnClass,
  makeVoiceAria, makeVoiceStatusText, makeVoiceCanCancel, directFileChipTitle, directAttachmentKind, directAttachmentKindLabel,
  removeDirectAttachedFile, isFileEmployeePurposeToggle, isFileAutoReadEmployee, setFilePurpose, onComposerFocus, llmCatalog,
  llmCatalogError, selectedProvider, selectedModel, modelMode, llmDdOpen, llmMobileSheetOpen,
  intentRepoPickShow, showIntentGuide, makeHasActiveTask, hasWorkflow, placeholder, makeComposerInput,
  makeComposerPlaceholder, composerSendDisabled, currentProviderLabel, modelModeHint, modelPickerEnabled, categoryLabel,
  modelsForWorkbenchCategory, toggleLlmDd, pickProvider, pickModel, cancelInlineVoice, toggleMakeVoice,
  openKnowledgeFilePicker, onKnowledgeFileChange, onComposerSendClick, onComposerKeydown,
} = props.wb
</script>

<template>
      <div
        v-if="hasWorkflow && wbSidebar.activeMode === 'make' && !platformChatMode"
        class="wb-composer-column"
        :class="{ 'wb-composer-column--task-slim': makeHasActiveTask }"
      >
        <div class="wb-composer-panel" :class="{ 'wb-composer-panel--enter': composerPanelEnter }" @keydown="onComposerKeydown">
          <div class="wb-direct-box-main">
            <input
              ref="knowledgeFileInputRef"
              type="file"
              class="wb-direct-file-input"
              :accept="DIRECT_AND_VISION_ACCEPT"
              multiple
              :disabled="knowledgeUploading || !!planSession"
              @change="onKnowledgeFileChange"
            />
            <div class="wb-direct-composer-line">
            <div class="wb-direct-composer-row">
              <button
                type="button"
                class="wb-direct-attach-btn"
                :disabled="knowledgeUploading || !!planSession"
                aria-label="添加附件"
                @click="openKnowledgeFilePicker"
              >
                <svg class="wb-direct-attach-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21.44 11.05l-8.49 8.48a5.66 5.66 0 01-8-8l9.19-9.2a3.77 3.77 0 015.33 5.33L8.95 19.07a2.36 2.36 0 01-3.33-3.33l8.49-8.48" />
                </svg>
              </button>
              <textarea
                id="wb-home-input-make"
                ref="inputRef"
                v-model="makeComposerInput"
                class="wb-direct-input"
                rows="1"
                :placeholder="makeComposerPlaceholder"
                spellcheck="false"
                @keydown="onComposerKeydown"
                @focus="onComposerFocus"
              />
            <div class="wb-llm-inline wb-llm-inline--desktop" aria-label="模型选择">
              <div class="wb-mode-segment" role="radiogroup" aria-label="模型模式">
                <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'auto' }" role="radio" :aria-checked="modelMode === 'auto'" title="Auto：根据任务自动选择合适模型" @click="modelMode = 'auto'">Auto</button>
                <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'manual' }" role="radio" :aria-checked="modelMode === 'manual'" title="自选：手动指定厂商与模型" @click="modelMode = 'manual'">自选</button>
              </div>
              <p v-if="modelModeHint" class="wb-llm-hint">{{ modelModeHint }}</p>
              <template v-if="modelMode === 'manual' && llmCatalog && llmCatalog.providers?.length && !llmCatalogError">
                <div class="wb-llm-dd">
                  <span class="wb-sr-only" id="wb-home-provider-lbl">厂商</span>
                  <button
                    type="button"
                    class="wb-dd-trigger"
                    :class="{ 'wb-dd-trigger--open': llmDdOpen === 'provider' }"
                    aria-haspopup="listbox"
                    :aria-expanded="llmDdOpen === 'provider'"
                    aria-labelledby="wb-home-provider-lbl"
                    title="厂商"
                    @click.stop="toggleLlmDd('provider')"
                  >
                    <span class="wb-dd-trigger__text">{{ currentProviderLabel }}</span>
                    <svg class="wb-dd-trigger__icon" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                  </button>
                  <ul
                    v-show="llmDdOpen === 'provider'"
                    class="wb-dd-panel"
                    role="listbox"
                    aria-labelledby="wb-home-provider-lbl"
                  >
                    <template v-for="b in llmCatalog.providers" :key="b.provider">
                      <li v-if="b.title" class="wb-dd-cat" role="presentation">{{ b.title }}</li>
                      <li
                        v-for="item in b.items || [b]"
                        :key="item.provider"
                        role="option"
                        class="wb-dd-item"
                        :class="{ 'wb-dd-item--on': selectedProvider === item.provider }"
                        :aria-selected="selectedProvider === item.provider"
                        @click.stop="pickProvider(item.provider)"
                      >
                        {{ item.label || item.provider }}
                      </li>
                    </template>
                  </ul>
                </div>
                <div class="wb-llm-dd wb-llm-dd--model">
                  <span class="wb-sr-only" id="wb-home-model-lbl">模型</span>
                  <button
                    type="button"
                    class="wb-dd-trigger wb-dd-trigger--model"
                    :class="{ 'wb-dd-trigger--open': llmDdOpen === 'model' }"
                    :disabled="!modelPickerEnabled"
                    aria-haspopup="listbox"
                    :aria-expanded="llmDdOpen === 'model'"
                    aria-labelledby="wb-home-model-lbl"
                    title="模型"
                    @click.stop="modelPickerEnabled && toggleLlmDd('model')"
                  >
                    <span class="wb-dd-trigger__text">{{ selectedModel || '选择模型' }}</span>
                    <svg class="wb-dd-trigger__icon" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                  </button>
                  <ul
                    v-show="llmDdOpen === 'model' && modelPickerEnabled"
                    class="wb-dd-panel wb-dd-panel--tall"
                    role="listbox"
                    aria-labelledby="wb-home-model-lbl"
                  >
                    <template v-for="cat in LLM_CATEGORY_ORDER" :key="cat">
                      <template v-if="modelsForWorkbenchCategory(cat).length">
                        <li class="wb-dd-cat" role="presentation">{{ categoryLabel(cat) }}</li>
                        <li
                          v-for="row in modelsForWorkbenchCategory(cat)"
                          :key="row.id"
                          role="option"
                          class="wb-dd-item"
                          :class="{ 'wb-dd-item--on': selectedModel === row.id }"
                          :aria-selected="selectedModel === row.id"
                          @click.stop="pickModel(row.id)"
                        >
                          {{ row.id }}
                        </li>
                      </template>
                    </template>
                  </ul>
                </div>
              </template>
            </div>
              <button
                type="button"
                class="wb-direct-send-btn"
                :disabled="composerSendDisabled"
                :aria-label="composerSendDisabled ? '发送（请输入内容）' : (planSession?.phase === 'chat' ? '发送追问' : '发送')"
                :aria-disabled="composerSendDisabled"
                @click="() => void onComposerSendClick()"
              >
                <svg class="wb-direct-send-arrow-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
              </button>
            </div>
            <button
              type="button"
              class="wb-direct-voice-btn"
              :class="makeVoiceBtnClass"
              :aria-label="makeVoiceAria"
              :title="makeVoiceAria"
              :aria-pressed="makeVoicePhase === 'recording' || makeVoicePhase === 'recognizing'"
              :disabled="makeVoicePhase === 'recognizing'"
              @click="toggleMakeVoice"
            >
              <span
                v-if="makeVoicePhase === 'recognizing'"
                class="wb-direct-voice-btn__spinner"
                aria-hidden="true"
              />
              <svg
                v-else
                class="wb-direct-voice-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
            </div>
            <div
              v-if="makeVoiceStatusText || makeVoiceCanCancel"
              class="wb-direct-voice-bar"
            >
              <p
                v-if="makeVoiceStatusText"
                class="wb-direct-voice-status"
                :class="{
                  'wb-direct-voice-status--recording': makeVoicePhase === 'recording',
                  'wb-direct-voice-status--recognizing': makeVoicePhase === 'recognizing',
                  'wb-direct-voice-status--permission': makeVoicePhase === 'permission',
                }"
                role="status"
                aria-live="polite"
              >
                <span
                  v-if="makeVoicePhase === 'recording'"
                  class="wb-direct-voice-status__dot"
                  aria-hidden="true"
                />
                {{ makeVoiceStatusText }}
              </p>
              <button
                v-if="makeVoiceCanCancel"
                type="button"
                class="wb-direct-voice-cancel"
                aria-label="取消语音输入"
                @click="cancelInlineVoice('make')"
              >
                取消
              </button>
            </div>
            <div class="wb-direct-composer-tools">
            <button
              type="button"
              class="wb-llm-mobile-trigger"
              aria-haspopup="dialog"
              :aria-expanded="llmMobileSheetOpen"
              @click="llmMobileSheetOpen = true"
            >
              <span class="wb-llm-mobile-trigger__text">{{ llmMobilePickerSummary }}</span>
            </button>
            <button
              v-if="intentRepoPickShow"
              type="button"
              :class="{ 'wb-scene-toolbar-btn--on': showIntentGuide }"
              :aria-expanded="showIntentGuide"
              aria-label="展开说明"
              @click="showIntentGuide = !showIntentGuide"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            </button>
            <button
              v-if="composerIntent === 'mod'"
              type="button"
              :class="{ 'wb-scene-toolbar-btn--on': modFrontendEnabled }"
              role="switch"
              :aria-checked="modFrontendEnabled"
              title="打开后会为本Mod生成可路由Vue前端页面，关闭则仅生成后端API。"
              @click="modFrontendEnabled = !modFrontendEnabled"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </button>
            </div>
          </div>
          <TransitionGroup
            v-if="directAttachedFiles.length"
            name="wb-direct-file-card"
            tag="div"
            class="wb-direct-file-stack wb-composer-file-stack"
          >
            <article
              v-for="(f, i) in directVisibleAttachedFiles"
              :key="`composer-${f.id}`"
              class="wb-direct-file-card"
              :class="[
                `wb-direct-file-card--${f.status}`,
                `wb-direct-file-card--${directAttachmentKind(f)}`,
                { 'wb-direct-file-card--ingesting': f.ingesting },
              ]"
              :style="{ '--att-index': i }"
              :title="directFileChipTitle(f)"
            >
              <span class="wb-direct-file-card__deck" aria-hidden="true">
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--back"></span>
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--mid"></span>
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--front">
                  <span class="wb-direct-file-card__deck-label">{{ directAttachmentKindLabel(f) }}</span>
                </span>
              </span>
              <span class="wb-direct-file-card__state" aria-hidden="true">
                <span v-if="f.status === 'uploading' || f.ingesting" class="wb-direct-file-card__spinner" />
                <span v-else-if="f.status === 'ready' || f.status === 'inline'" class="wb-direct-file-card__check">✓</span>
                <span v-else class="wb-direct-file-card__warn">!</span>
              </span>
              <div v-if="isFileEmployeePurposeToggle(f)" class="wb-direct-file-card__purpose" @click.stop>
                <button type="button" class="wb-direct-file-card__purpose-btn" :class="{ 'wb-direct-file-card__purpose-btn--on': f.purpose !== 'employee' }" :disabled="knowledgeUploading || f.status === 'uploading'" title="作为知识参考" @click="setFilePurpose(String(f.id || ''), 'knowledge')">知识</button>
                <button type="button" class="wb-direct-file-card__purpose-btn" :class="{ 'wb-direct-file-card__purpose-btn--on': f.purpose === 'employee' }" :disabled="knowledgeUploading || f.status === 'uploading'" title="给员工处理" @click="setFilePurpose(String(f.id || ''), 'employee')">员工</button>
              </div>
              <div v-else-if="isFileAutoReadEmployee(f)" class="wb-direct-file-card__purpose" @click.stop>
                <span class="wb-direct-file-card__purpose-tag">读取员工</span>
              </div>
              <button
                type="button"
                class="wb-direct-file-card__remove"
                :aria-label="`移除 ${f.name}`"
                :disabled="knowledgeUploading || f.status === 'uploading'"
                @click="() => void removeDirectAttachedFile(f.id)"
              >×</button>
            </article>
            <div
              v-if="directHiddenAttachmentCount"
              key="composer-more"
              class="wb-direct-file-card wb-direct-file-card--more"
              aria-label="更多附件"
            >
              <span class="wb-direct-file-card__deck" aria-hidden="true">
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--back"></span>
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--mid"></span>
                <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--front">
                  <span class="wb-direct-file-card__deck-plus">+{{ directHiddenAttachmentCount }}</span>
                </span>
              </span>
            </div>
          </TransitionGroup>
          <div v-if="directAttachmentMentions.length" class="wb-file-mention-row wb-file-mention-row--composer" aria-label="二档已引用附件">
            <span
              v-for="(m, i) in directAttachmentMentions"
              :key="`make-ref-${m}`"
              class="wb-file-mention-token"
            >@附件{{ i + 1 }} {{ m }}</span>
          </div>
          <p v-if="knowledgeError" class="wb-research-msg wb-research-msg--err" role="status">{{ knowledgeError }}</p>
        </div>
      </div>
</template>
