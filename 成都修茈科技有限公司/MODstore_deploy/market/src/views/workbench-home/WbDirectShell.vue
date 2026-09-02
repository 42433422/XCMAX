<script setup lang="ts">
import DirectFlowPanel from '../../components/workbench/direct/DirectFlowPanel.vue'
import DirectMediaSettingsRail from '../../components/workbench/direct/DirectMediaSettingsRail.vue'
import { DIRECT_AND_VISION_ACCEPT } from '../../utils/directAttachments'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 272–712 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  LLM_CATEGORY_ORDER, wbNav, inputRef, llmMobilePickerSummary, directDraft, directPlaceholder,
  directFileInputRef, directAttachedFiles, directLoading, directSendPending, directError, directVoiceListening,
  directWaveformCanvas, directWebSearchEnabled, directWebSearching, directImageGenEnabled, directVideoGenEnabled, directMediaGenerating,
  directImageSize, directImageStyle, directImageCount, directVideoAspect, directVideoDurationSec, directMessages,
  directIsDragging, activeBot, speakingMessageId, directSendDisabled, directAttachHint, directComposerVisibleFiles,
  directComposerHiddenCount, directAttachmentMentions, contentEnter, directBoxEnter, directAttachExpanded, directVoicePhase,
  directVoiceBtnClass, directVoiceAria, directVoiceStatusText, directVoiceCanCancel, directFileChipTitle, directAttachmentKind,
  directAttachmentKindLabel, openDirectFilePicker, onDirectFilesChange, removeDirectAttachedFile, sendDirectChat, stopGeneration,
  downloadOutput, regenerateAssistant, startEditUserMessage, setMessageFeedback, speakMessage, isFileEmployeePurposeToggle,
  isFileAutoReadEmployee, setFilePurpose, onComposerPaste, onSurfaceDragEnter, onSurfaceDragOver, onSurfaceDragLeave,
  onSurfaceDrop, clearActiveBot, onDirectKeydown, onComposerFocus, llmCatalog, llmCatalogLoading,
  llmCatalogError, selectedProvider, selectedModel, modelMode, llmDdOpen, llmMobileSheetOpen,
  placeholder, currentProviderLabel, modelModeHint, modelPickerEnabled, categoryLabel, modelsForWorkbenchCategory,
  toggleLlmDd, pickProvider, pickModel, cancelInlineVoice, onDirectVoicePointerDown, onDirectVoicePointerMove,
  onDirectVoicePointerUp, onDirectVoiceClick,
} = props.wb
</script>

<template>
              <div
                class="wb-direct-shell"
                :class="{ 'wb-direct-shell--empty': !directMessages.length, 'wb-content-enter': contentEnter && directMessages.length }"
              >
                <div
                  class="wb-direct-main"
                  :class="{
                    'wb-direct-main--empty': !directMessages.length,
                    'wb-direct-main--chatting': directMessages.length,
                    'wb-direct-main--drop': directIsDragging,
                    'wb-direct-main--media-rail': directImageGenEnabled || directVideoGenEnabled,
                  }"
                  @dragenter="onSurfaceDragEnter"
                  @dragover="onSurfaceDragOver"
                  @dragleave="onSurfaceDragLeave"
                  @drop="onSurfaceDrop"
                >
                  <div
                    v-if="directIsDragging"
                    class="wb-direct-dropzone"
                    aria-hidden="true"
                  >
                    <div class="wb-direct-dropzone__panel">
                      <div class="wb-direct-dropzone__icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M21.44 11.05l-8.49 8.48a5.66 5.66 0 01-8-8l9.19-9.2a3.77 3.77 0 015.33 5.33L8.95 19.07a2.36 2.36 0 01-3.33-3.33l8.49-8.48" />
                        </svg>
                      </div>
                      <p class="wb-direct-dropzone__title">松开以添加附件</p>
                      <p class="wb-direct-dropzone__sub">支持 PDF / Word / Excel / 文本，图片可粘贴或拖入</p>
                    </div>
                  </div>
                  <header v-if="activeBot" class="wb-direct-topbar">
                    <div class="wb-direct-topbar__l">
                      <span class="wb-direct-bot-chip">
                        <span aria-hidden="true">{{ activeBot.icon }}</span>
                        <span class="wb-direct-bot-chip__name">@{{ activeBot.name }}</span>
                        <button type="button" class="wb-direct-bot-chip__x" aria-label="切回通用助手" @click="clearActiveBot">×</button>
                      </span>
                    </div>
                  </header>

                  <div v-if="directMessages.length" class="wb-direct-flow-host">
                    <DirectFlowPanel
                      :messages="directMessages"
                      :speaking-message-id="speakingMessageId"
                      @download-output="(p) => void downloadOutput(p.jobId, p.filename, p.label)"
                      @regenerate="(id) => void regenerateAssistant(id)"
                      @speak="(id) => void speakMessage(id)"
                      @feedback="(id, fb) => setMessageFeedback(id, fb)"
                      @edit="(id) => startEditUserMessage(id)"
                    />
                  </div>

                  <div
                    class="wb-direct-box"
                    :class="{
                      'wb-direct-box--drop': directIsDragging,
                      'wb-direct-box--enter': directBoxEnter,
                      'wb-direct-box--chatting': directMessages.length,
                    }"
                    @paste="onComposerPaste"
                  >
                    <div
                      v-if="directAttachedFiles.length || directAttachmentMentions.length || directAttachHint"
                      class="wb-direct-box-attachments"
                      :class="{ 'wb-direct-box-attachments--has-uploads': directAttachedFiles.length }"
                    >
                      <p v-if="directAttachedFiles.length" class="wb-direct-upload-zone-label">待发送附件</p>
                      <TransitionGroup
                        v-if="directAttachedFiles.length"
                        name="wb-direct-file-card"
                        tag="div"
                        class="wb-direct-file-stack wb-composer-file-stack"
                      >
                        <article
                          v-for="(f, i) in directComposerVisibleFiles"
                          :key="`direct-upload-${f.id}`"
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
                          <span class="wb-direct-file-card__name">{{ f.name }}</span>
                          <span class="wb-direct-file-card__state" aria-hidden="true">
                            <span v-if="f.status === 'uploading' || f.ingesting" class="wb-direct-file-card__spinner" />
                            <span v-else-if="f.status === 'ready' || f.status === 'inline'" class="wb-direct-file-card__check">✓</span>
                            <span v-else class="wb-direct-file-card__warn">!</span>
                          </span>
                          <div v-if="isFileEmployeePurposeToggle(f)" class="wb-direct-file-card__purpose" @click.stop>
                            <button type="button" class="wb-direct-file-card__purpose-btn" :class="{ 'wb-direct-file-card__purpose-btn--on': f.purpose !== 'employee' }" :disabled="directLoading || f.status === 'uploading'" title="作为知识参考" @click="setFilePurpose(String(f.id || ''), 'knowledge')">知识</button>
                            <button type="button" class="wb-direct-file-card__purpose-btn" :class="{ 'wb-direct-file-card__purpose-btn--on': f.purpose === 'employee' }" :disabled="directLoading || f.status === 'uploading'" title="给员工处理" @click="setFilePurpose(String(f.id || ''), 'employee')">员工</button>
                          </div>
                          <div v-else-if="isFileAutoReadEmployee(f)" class="wb-direct-file-card__purpose" @click.stop>
                            <span class="wb-direct-file-card__purpose-tag">读取员工</span>
                          </div>
                          <button
                            type="button"
                            class="wb-direct-file-card__remove"
                            :aria-label="`移除 ${f.name}`"
                            :disabled="directLoading || f.status === 'uploading'"
                            @click="() => void removeDirectAttachedFile(f.id)"
                          >×</button>
                        </article>
                        <div
                          v-if="directComposerHiddenCount"
                          key="direct-upload-more"
                          class="wb-direct-file-card wb-direct-file-card--more"
                          aria-label="更多附件"
                        >
                          <span class="wb-direct-file-card__deck" aria-hidden="true">
                            <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--back"></span>
                            <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--mid"></span>
                            <span class="wb-direct-file-card__deck-card wb-direct-file-card__deck-card--front">
                              <span class="wb-direct-file-card__deck-plus">+{{ directComposerHiddenCount }}</span>
                            </span>
                          </span>
                        </div>
                      </TransitionGroup>
                      <div v-if="directAttachmentMentions.length" class="wb-file-mention-row" aria-label="已引用附件">
                        <span
                          v-for="(m, i) in directAttachmentMentions"
                          :key="`direct-ref-${m}`"
                          class="wb-file-mention-token"
                        >@附件{{ i + 1 }} {{ m }}</span>
                      </div>
                      <p v-if="directAttachHint" class="wb-direct-attach-hint" role="status">
                        {{ directAttachHint }}
                      </p>
                    </div>
                    <p
                      v-if="directWebSearchEnabled && !directLoading && !directWebSearching"
                      class="wb-direct-web-search-chip"
                      role="status"
                    >
                      联网搜索已开启
                    </p>
                    <div
                      v-if="directLoading || directWebSearching || directMediaGenerating"
                      class="wb-direct-generating-bar"
                      role="status"
                      aria-live="polite"
                    >
                      <span>{{
                        directWebSearching
                          ? '正在联网检索…'
                          : directMediaGenerating
                            ? directImageGenEnabled
                              ? '正在生成图片…'
                              : '正在提交生视频…'
                            : '正在生成…'
                      }}</span>
                      <button
                        type="button"
                        class="wb-direct-generating-bar__stop"
                        aria-label="停止生成"
                        @click="stopGeneration"
                      >
                        停止
                      </button>
                    </div>
                    <p v-else-if="directSendPending" class="wb-direct-send-hint" role="status">发送中…</p>
                    <div v-if="wbNav.isMobile && directVoiceListening" class="wb-direct-voice-wave">
                      <canvas ref="directWaveformCanvas" class="wb-voice-waveform-canvas" width="520" height="28" />
                    </div>
                    <div
                      class="wb-direct-composer-shell"
                      :class="{ 'wb-direct-composer-shell--media': directImageGenEnabled || directVideoGenEnabled }"
                    >
                      <DirectMediaSettingsRail
                        v-if="directImageGenEnabled"
                        class="wb-direct-media-rail--composer"
                        mode="image"
                        v-model:image-size="directImageSize"
                        v-model:image-style="directImageStyle"
                        v-model:image-count="directImageCount"
                      />
                      <DirectMediaSettingsRail
                        v-else-if="directVideoGenEnabled"
                        class="wb-direct-media-rail--composer"
                        mode="video"
                        v-model:video-aspect="directVideoAspect"
                        v-model:video-duration-sec="directVideoDurationSec"
                      />
                    <div class="wb-direct-box-main">
                      <input
                        ref="directFileInputRef"
                        type="file"
                        class="wb-direct-file-input"
                        :accept="DIRECT_AND_VISION_ACCEPT"
                        multiple
                        :disabled="directLoading || !!directDraft"
                        @change="onDirectFilesChange"
                      />
                      <div class="wb-direct-composer-line">
                      <div class="wb-direct-composer-row">
                        <button
                          type="button"
                          class="wb-direct-attach-btn"
                          :class="{ 'wb-direct-attach-btn--on': directAttachExpanded }"
                          :disabled="directLoading || !!directDraft"
                          aria-label="添加附件"
                          title="添加附件"
                          @click="openDirectFilePicker"
                        >
                          <svg class="wb-direct-attach-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21.44 11.05l-8.49 8.48a5.66 5.66 0 01-8-8l9.19-9.2a3.77 3.77 0 015.33 5.33L8.95 19.07a2.36 2.36 0 01-3.33-3.33l8.49-8.48" />
                          </svg>
                        </button>
                        <textarea
                          id="wb-home-input"
                          ref="inputRef"
                          v-model="directDraft"
                          class="wb-direct-input"
                          rows="1"
                          :placeholder="directPlaceholder"
                          spellcheck="false"
                          @keydown="onDirectKeydown"
                          @focus="onComposerFocus"
                        />
                        <div class="wb-llm-inline wb-llm-inline--desktop" aria-label="模型选择">
                        <div class="wb-mode-segment" role="radiogroup" aria-label="模型模式">
                          <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'auto' }" role="radio" :aria-checked="modelMode === 'auto'" title="Auto：根据任务自动选择合适模型" @click="modelMode = 'auto'"> Auto </button>
                          <button type="button" class="wb-mode-segment__btn" :class="{ 'wb-mode-segment__btn--on': modelMode === 'manual' }" role="radio" :aria-checked="modelMode === 'manual'" title="自选：手动指定厂商与模型" @click="modelMode = 'manual'"> 自选 </button>
                        </div>
                        <p v-if="modelModeHint" class="wb-llm-hint">{{ modelModeHint }}</p>
                        <template v-if="modelMode === 'manual' && llmCatalog && llmCatalog.providers?.length && !llmCatalogError">
                          <div class="wb-llm-dd">
                            <span class="wb-sr-only" id="wb-direct-provider-lbl">厂商</span>
                            <button
                              type="button"
                              class="wb-dd-trigger"
                              :class="{ 'wb-dd-trigger--open': llmDdOpen === 'directProvider' }"
                              aria-haspopup="listbox"
                              :aria-expanded="llmDdOpen === 'directProvider'"
                              aria-labelledby="wb-direct-provider-lbl"
                              title="厂商"
                              @click.stop="toggleLlmDd('directProvider')"
                            >
                              <span class="wb-dd-trigger__text">{{ currentProviderLabel }}</span>
                              <svg class="wb-dd-trigger__icon" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                                <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
                              </svg>
                            </button>
                            <ul
                              v-show="llmDdOpen === 'directProvider'"
                              class="wb-dd-panel"
                              role="listbox"
                              aria-labelledby="wb-direct-provider-lbl"
                            >
                              <li
                                v-for="b in llmCatalog.providers"
                                :key="`direct-${b.provider}`"
                                role="option"
                                class="wb-dd-item"
                                :class="{ 'wb-dd-item--on': selectedProvider === b.provider }"
                                :aria-selected="selectedProvider === b.provider"
                                @click.stop="pickProvider(b.provider)"
                              >
                                {{ b.label || b.provider }}
                              </li>
                            </ul>
                          </div>
                          <div class="wb-llm-dd wb-llm-dd--model">
                            <span class="wb-sr-only" id="wb-home-model-lbl">模型</span>
                            <button
                              type="button"
                              class="wb-dd-trigger wb-dd-trigger--model"
                              :class="{ 'wb-dd-trigger--open': llmDdOpen === 'directModel' }"
                              :disabled="!modelPickerEnabled"
                              aria-haspopup="listbox"
                              :aria-expanded="llmDdOpen === 'directModel'"
                              aria-labelledby="wb-home-model-lbl"
                              title="模型"
                              @click.stop="modelPickerEnabled && toggleLlmDd('directModel')"
                            >
                              <span class="wb-dd-trigger__text">{{ selectedModel || '选择模型' }}</span>
                              <svg class="wb-dd-trigger__icon" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                                <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
                              </svg>
                            </button>
                            <ul
                              v-show="llmDdOpen === 'directModel' && modelPickerEnabled"
                              class="wb-dd-panel wb-dd-panel--tall"
                              role="listbox"
                              aria-labelledby="wb-home-model-lbl"
                            >
                              <template v-for="cat in LLM_CATEGORY_ORDER" :key="`direct-${cat}`">
                                <template v-if="modelsForWorkbenchCategory(cat).length">
                                  <li class="wb-dd-cat" role="presentation">{{ categoryLabel(cat) }}</li>
                                  <li
                                    v-for="row in modelsForWorkbenchCategory(cat)"
                                    :key="`direct-${row.id}`"
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
                        <span
                          v-else-if="modelMode === 'manual' && (llmCatalogLoading || llmCatalogError || !llmCatalog?.providers?.length)"
                          class="wb-llm-inline__note"
                          :title="llmCatalogError || ''"
                        >{{ llmCatalogLoading ? '目录…' : '登录配置' }}</span>
                        </div>
                        <button
                          v-if="directLoading"
                          type="button"
                          class="wb-direct-send-btn wb-direct-send--stop"
                          aria-label="停止生成"
                          title="停止生成"
                          @click="stopGeneration"
                        >
                          <svg class="wb-direct-send-stop-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="1.5"/></svg>
                          <span class="wb-direct-send-btn__label">停止生成</span>
                        </button>
                        <button
                          v-else
                          type="button"
                          class="wb-direct-send-btn"
                          :disabled="directSendDisabled"
                          :aria-label="directSendDisabled ? '发送消息（请输入内容）' : '发送消息'"
                          :aria-disabled="directSendDisabled"
                          @click="() => void sendDirectChat()"
                        >
                          <svg class="wb-direct-send-arrow-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                        </button>
                      </div>
                      <button
                        type="button"
                        class="wb-direct-voice-btn"
                        :class="directVoiceBtnClass"
                        :aria-label="directVoiceAria"
                        :title="directVoiceAria"
                        :aria-pressed="directVoicePhase === 'recording' || directVoicePhase === 'recognizing'"
                        :disabled="directLoading || directVoicePhase === 'recognizing'"
                        @pointerdown.prevent="onDirectVoicePointerDown"
                        @pointermove="onDirectVoicePointerMove"
                        @pointerup="onDirectVoicePointerUp"
                        @pointercancel="onDirectVoicePointerUp"
                        @lostpointercapture="onDirectVoicePointerUp"
                        @click="onDirectVoiceClick"
                        @contextmenu.prevent
                      >
                        <span
                          v-if="directVoicePhase === 'recognizing'"
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
                      </div>
                    </div>
                    </div>
                  </div>
                  <p
                    v-if="directError && directVoicePhase !== 'permission'"
                    class="wb-direct-error"
                    role="alert"
                  >
                    {{ directError }}
                  </p>
                  <div
                    v-if="directVoiceStatusText || directVoiceCanCancel"
                    class="wb-direct-voice-bar"
                  >
                    <p
                      v-if="directVoiceStatusText"
                      class="wb-direct-voice-status"
                      :class="{
                        'wb-direct-voice-status--recording': directVoicePhase === 'recording',
                        'wb-direct-voice-status--recognizing': directVoicePhase === 'recognizing',
                        'wb-direct-voice-status--permission': directVoicePhase === 'permission',
                      }"
                      role="status"
                      aria-live="polite"
                    >
                      <span
                        v-if="directVoicePhase === 'recording'"
                        class="wb-direct-voice-status__dot"
                        aria-hidden="true"
                      />
                      {{ directVoiceStatusText }}
                    </p>
                    <button
                      v-if="directVoiceCanCancel"
                      type="button"
                      class="wb-direct-voice-cancel"
                      aria-label="取消语音输入"
                      @click="cancelInlineVoice('direct')"
                    >
                      取消
                    </button>
                  </div>

                </div>
              </div>
</template>
