<template>
  <div class="wb-home">
    <header class="wb-scene-header">
      <div class="wb-scene-toolbar" :class="{ 'wb-scene-toolbar--left': wbSidebar.activeMode === 'make' || wbSidebar.activeMode === 'voice' }">
        <div v-if="wbSidebar.activeMode === 'direct'" class="wb-toolbar-group" :class="{ 'wb-toolbar-group--enter': hasWorkflow }">
          <button
            v-if="hasWorkflow"
            ref="tierTriggerRef"
            type="button"
            class="wb-scene-toolbar-btn"
            :class="{ 'wb-scene-toolbar-btn--active': tierPanelOpen }"
            title="消费档位：1 省资源、10 质量更高（影响回复风格与消耗）"
            aria-haspopup="dialog"
            :aria-expanded="tierPanelOpen"
            @click="toggleTierPanel()"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M2 12h12M2 8h12M2 4h12" /><circle cx="5" cy="12" r="1.2" fill="currentColor" /><circle cx="10" cy="8" r="1.2" fill="currentColor" /><circle cx="7" cy="4" r="1.2" fill="currentColor" /></svg>
            <span>档位 {{ consumptionTier }}</span>
          </button>
          <button
            v-if="hasWorkflow"
            type="button"
            class="wb-scene-toolbar-btn wb-scene-toolbar-btn--web-search"
            :class="{ 'wb-scene-toolbar-btn--active': directWebSearchEnabled }"
            :title="directWebSearchEnabled ? '联网搜索已开启：发送时将检索网页；再点关闭' : '联网搜索：发送时检索公开网页并参考来源'"
            :aria-pressed="directWebSearchEnabled"
            @click="toggleDirectWebSearch()"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" /></svg>
            <span>联网搜索</span>
          </button>
          <button
            v-if="hasWorkflow"
            type="button"
            class="wb-scene-toolbar-btn wb-scene-toolbar-btn--gen-image"
            :class="{ 'wb-scene-toolbar-btn--active': directImageGenEnabled }"
            :title="directImageGenEnabled ? '生图已开启：输入描述后发送；再点关闭' : '生成图片：开启后可在输入框右侧调参数，发送时生图'"
            :aria-pressed="directImageGenEnabled"
            @click="toggleDirectImageGen()"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="12" height="10" rx="1.2" /><circle cx="5.5" cy="6.5" r="1" /><path d="M2 11l3.5-3 2.5 2L11 7l3 4" /></svg>
            <span>生成图片</span>
          </button>
          <button
            v-if="hasWorkflow"
            type="button"
            class="wb-scene-toolbar-btn wb-scene-toolbar-btn--gen-video"
            :class="{ 'wb-scene-toolbar-btn--active': directVideoGenEnabled }"
            :title="directVideoGenEnabled ? '生视频已开启：输入描述后发送；再点关闭' : '生成视频：开启后可在输入框右侧调参数，发送时提交生视频'"
            :aria-pressed="directVideoGenEnabled"
            @click="toggleDirectVideoGen()"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3.5" width="10" height="9" rx="1.2" /><path d="M12 6.5l3-2v7l-3-2z" fill="currentColor" stroke="none" /></svg>
            <span>生成视频</span>
          </button>
          <button
            v-if="hasWorkflow"
            ref="empTriggerRef"
            type="button"
            class="wb-scene-toolbar-btn"
            :class="{ 'wb-scene-toolbar-btn--active': empPanelOpen }"
            title="绑定 AI 员工：回答更贴近岗位知识；不绑定则通用检索"
            aria-haspopup="dialog"
            :aria-expanded="empPanelOpen"
            @click="toggleEmpPanel()"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><circle cx="8" cy="5" r="2.5" /><path d="M3 14c0-2.76 2.24-5 5-5s5 2.24 5 5" /></svg>
            <span>员工</span>
          </button>
        </div>
        <div v-if="(wbSidebar.activeMode === 'make' || wbSidebar.activeMode === 'voice') && !wbNav.isMobile" class="wb-toolbar-group" :class="{ 'wb-toolbar-group--enter': hasWorkflow }">
          <div v-if="!platformChatMode" class="wb-scene-toolbar__group">
            <button v-if="hasModRepo" type="button" class="wb-scene-toolbar-btn" :class="{ 'wb-scene-toolbar-btn--active': composerIntent === 'mod' && !voiceCasualChatMode }" :title="composerIntent === 'mod' && !voiceCasualChatMode ? '做 Mod（再点取消，留在「说」里正常聊天）' : '做 Mod'" @click="switchMakeIntent('mod')">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="2" y="2" width="5" height="5" rx="1" /><rect x="9" y="2" width="5" height="5" rx="1" /><rect x="2" y="9" width="5" height="5" rx="1" /><rect x="9" y="9" width="5" height="5" rx="1" /></svg>
              <span>做 Mod</span>
            </button>
            <button v-if="hasEmployeeIntent" type="button" class="wb-scene-toolbar-btn" :class="{ 'wb-scene-toolbar-btn--active': hasWorkflow && composerIntent === 'employee' && !voiceCasualChatMode }" :title="hasWorkflow && composerIntent === 'employee' && !voiceCasualChatMode ? '做员工（再点取消，留在「说」里正常聊天）' : '做员工'" @click="switchMakeIntent('employee')">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><circle cx="8" cy="5" r="2.5" /><path d="M3 14c0-2.76 2.24-5 5-5s5 2.24 5 5" /></svg>
              <span>做员工</span>
            </button>
            <button v-if="hasWorkflow" type="button" class="wb-scene-toolbar-btn" :class="{ 'wb-scene-toolbar-btn--active': hasWorkflow && composerIntent === CANVAS_SKILL_INTENT && !voiceCasualChatMode }" :title="hasWorkflow && composerIntent === CANVAS_SKILL_INTENT && !voiceCasualChatMode ? '生成 Skill 组（再点取消，留在「说」里正常聊天）' : '生成 Skill 组'" @click="switchMakeIntent(CANVAS_SKILL_INTENT)">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M2 12h12M2 8h12M2 4h12" /><circle cx="5" cy="12" r="1.2" fill="currentColor" /><circle cx="10" cy="8" r="1.2" fill="currentColor" /><circle cx="7" cy="4" r="1.2" fill="currentColor" /></svg>
              <span>生成 Skill 组</span>
            </button>
          </div>
          <button v-if="hasWorkflow && !platformChatMode" type="button" class="wb-scene-toolbar-btn" :class="{ 'wb-scene-toolbar-btn--active': tierPanelOpen }" title="消费档位" @click="tierPanelOpen = !tierPanelOpen">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M2 12h12M2 8h12M2 4h12" /><circle cx="5" cy="12" r="1.2" fill="currentColor" /><circle cx="10" cy="8" r="1.2" fill="currentColor" /><circle cx="7" cy="4" r="1.2" fill="currentColor" /></svg>
            <span>档位 {{ consumptionTier }}</span>
          </button>
          <button
            type="button"
            class="wb-scene-toolbar-btn"
            :class="{ 'wb-scene-toolbar-btn--active': platformChatMode }"
            :title="
              platformChatMode
                ? '当前为闲聊模式（只对话）；点击切回制作模式，显示做 Mod / 做员工 / 生成 Skill 组'
                : '点击开启闲聊模式：只对话、不触发制作；侧栏「聊」始终是文字对话'
            "
            @click.stop="togglePlatformChatMode"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 3.5h11a1.5 1.5 0 011.5 1.5v5a1.5 1.5 0 01-1.5 1.5H5.2L2.5 14V5a1.5 1.5 0 011.5-1.5z" /><path d="M5 7.5h6M5 10h4" /></svg>
            <span>{{ platformChatMode ? '制作模式' : '闲聊' }}</span>
          </button>
        </div>
      </div>
      <button type="button" class="wb-scene-toolbar-btn wb-tts-toggle" :class="{ 'wb-scene-toolbar-btn--active': ttsAutoRead }" :title="ttsAutoRead ? '自动朗读已开启' : '自动朗读已关闭'" @click="ttsAutoRead = !ttsAutoRead">
        <svg v-if="ttsAutoRead" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5.5v5l3.5 2V3.5L2 5.5z" /><path d="M8.5 5.5a2.5 2.5 0 010 5" /><path d="M8.5 3a5 5 0 010 10" /></svg>
        <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2 5.5v5l3.5 2V3.5L2 5.5z" /><path d="M13 5.5L8.5 10" /><path d="M8.5 5.5L13 10" /></svg>
      </button>
      <button type="button" class="wb-scene-toolbar-btn wb-theme-toggle" :class="{ 'wb-scene-toolbar-btn--active': isLightTheme }" :title="isLightTheme ? '切换深色模式' : '切换浅色模式'" @click="toggleTheme">
        <svg v-if="isLightTheme" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" /><circle cx="8" cy="8" r="3.5" /></svg>
        <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M13.5 10.5a6 6 0 01-8-8A6 6 0 1013.5 10.5z" /></svg>
      </button>
    </header>
    <div
      v-if="showDirectHomeFileStrip"
      class="wb-home-file-strip"
      aria-label="已生成与可下载文件"
    >
      <button
        v-if="butlerFileOverflowCount > 0"
        type="button"
        class="wb-home-file-strip__butler-link"
        :title="`在 AI 管家中查看 ${butlerFileOverflowCount} 个收纳文件`"
        @click="openButlerFileTray"
      >
        收纳 {{ butlerFileOverflowCount }} 个
      </button>
      <div class="wb-home-file-strip__chips">
        <article
          v-if="directGeneratingFile?.active"
          key="__generating"
          class="wb-file-chip wb-file-chip--generating"
          :class="[`wb-file-chip--${directGeneratingFile.format}`]"
          aria-live="polite"
          aria-label="文件生成中"
        >
          <span class="wb-file-chip__badge">{{ directGeneratingFormatLabel }}</span>
          <span class="wb-file-chip__name">{{ directGeneratingFile.label || '生成中…' }}</span>
          <span class="wb-file-chip__state" aria-hidden="true">
            <span class="wb-file-chip__spinner" />
          </span>
        </article>
        <DirectGeneratedFileStack
          layout="chip"
          :files="directGeneratedFiles"
          :max-visible="headerGeneratedStripPlan.stripGeneratedCount"
          hide-more-card
          :disabled="directLoading"
          @download="(f) => void downloadGeneratedOutput(f)"
          @remove="removeDirectGeneratedFile"
        />
      </div>
    </div>
    <main class="wb-main-area">
      <div class="wb-mode-content">
        <section
          v-if="wbSidebar.activeMode !== 'voice'"
          class="wb-mode-scene"
          :class="{
            'wb-mode-scene--direct-flow': showDirectStyleConversation && directMessages.length,
            'wb-mode-scene--direct-empty': showDirectStyleConversation && !directMessages.length,
            'wb-mode-scene--make-platform': showMakePlatformCasualChat,
            'wb-mode-scene--make-flow': wbSidebar.activeMode === 'make' && !platformChatMode && makeHasActiveTask,
          }"
          :style="directFontPxStyle"
        >
          <Teleport to="body">
            <div
              v-if="tierPanelOpen && wbSidebar.activeMode === 'direct'"
              class="wb-scene-panel wb-scene-panel--popover"
              :class="{ 'wb-scene-panel--tier-mobile': wbNav.isMobile }"
              :style="tierPanelAnchorStyle"
              :key="'tier-direct'"
              role="dialog"
              aria-label="消费档位"
            >
              <p v-if="!wbNav.isMobile" class="wb-scene-panel-hint">消费档位影响回复质量与资源消耗：1 更省，10 更强。</p>
              <ConsumptionTierControl v-model="consumptionTier" @change="tierPanelOpen = false" />
            </div>
          </Teleport>
          <Teleport to="body" :disabled="wbNav.isMobile">
            <div
              v-if="empPanelOpen && wbSidebar.activeMode === 'direct'"
              class="wb-scene-panel"
              :class="{ 'wb-scene-panel--popover': !wbNav.isMobile }"
              :style="empPanelAnchorStyle"
              :key="'emp-direct'"
              role="dialog"
              aria-label="选择员工"
            >
            <p v-if="!wbNav.isMobile" class="wb-scene-panel-hint">绑定员工后，回答会优先使用该员工的技能与知识库。</p>
            <label class="wb-scene-panel-label" for="wb-direct-employee-select">选择员工</label>
            <div class="wb-emp-select" :class="{ 'wb-emp-select--open': empDropdownOpen, 'wb-emp-select--disabled': directLoading }">
              <button type="button" class="wb-emp-select__trigger" :disabled="directLoading" aria-haspopup="listbox" :aria-expanded="empDropdownOpen" @click="empDropdownOpen = !empDropdownOpen">
                <span class="wb-emp-select__value">{{ directChatEmployeeId ? directEmployeeOptions.find(o => o.id === directChatEmployeeId)?.name || directChatEmployeeId : '不绑定（通用检索）' }}</span>
                <svg class="wb-emp-select__chevron" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3.5 5.25L7 8.75L10.5 5.25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
              <Transition name="wb-emp-dropdown">
                <div v-if="empDropdownOpen" class="wb-emp-select__dropdown">
                  <button type="button" class="wb-emp-select__option" :class="{ 'wb-emp-select__option--active': !directChatEmployeeId }" role="option" :aria-selected="!directChatEmployeeId" @click="directChatEmployeeId = ''; empDropdownOpen = false">
                    <span class="wb-emp-select__option-icon">🌐</span>
                    <span class="wb-emp-select__option-text">不绑定（通用检索）</span>
                  </button>
                  <button v-for="opt in directEmployeeOptions" :key="opt.id" type="button" class="wb-emp-select__option" :class="{ 'wb-emp-select__option--active': directChatEmployeeId === opt.id }" role="option" :aria-selected="directChatEmployeeId === opt.id" @click="directChatEmployeeId = opt.id; empDropdownOpen = false">
                    <span class="wb-emp-select__option-icon"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="3" y="4" width="10" height="7" rx="1.5"/><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5"/></svg></span>
                    <span class="wb-emp-select__option-content">
                      <span class="wb-emp-select__option-name">{{ opt.name }}</span>
                      <span class="wb-emp-select__option-meta">{{ opt.id }} · {{ opt.sourceLabel }}</span>
                    </span>
                  </button>
                </div>
              </Transition>
            </div>
            </div>
          </Teleport>
          <template v-if="showDirectStyleConversation">
              <div
                v-if="!directMessages.length"
                class="wb-direct-empty-body"
                :class="{ 'wb-content-enter': contentEnter }"
              >
              <div class="wb-direct-empty-columns">
              <div class="wb-direct-empty-stack">
              <div class="wb-direct-empty-title" :class="{ 'wb-title-enter': titleEnterDone }">
                <h1 :key="'direct-' + wbSidebar.activeMode" class="wb-direct-title">{{ directTitleTw.displayed.value }}</h1>
                <p :key="'sub-' + wbSidebar.activeMode" class="wb-direct-sub">{{ directSubTw.displayed.value }}<span v-if="directSubTw.isTyping.value" class="wb-cursor">▌</span></p>
              </div>
              <div v-if="showDirectChatSurface" class="wb-direct-starters">
                <p class="wb-direct-starters__section-title">试试这些</p>
                <div class="wb-direct-starters__cards">
                  <button
                    v-for="card in homeStarterCards"
                    :key="card.label"
                    type="button"
                    class="wb-direct-starter-card"
                    @click="applyStarterPrompt(card.prompt, { requiresAttachment: card.requiresAttachment, label: card.label })"
                  >
                    <span class="wb-direct-starter-card__label">{{ card.label }}</span>
                    <span class="wb-direct-starter-card__desc">{{ card.desc }}</span>
                  </button>
                </div>
                <template v-if="homeSuggestionChips.length">
                  <p class="wb-direct-starters__section-title">快捷提问</p>
                  <div class="wb-direct-starters__chips">
                    <button
                      v-for="(chip, i) in homeSuggestionChips"
                      :key="`chip-${i}`"
                      type="button"
                      class="wb-direct-starter-chip"
                      @click="applyStarterPrompt(chip)"
                    >
                      {{ chip }}
                    </button>
                  </div>
                </template>
                <template v-if="recentHomeConversations.length">
                  <p class="wb-direct-starters__section-title">最近对话</p>
                  <ul class="wb-direct-starters__recent-list">
                    <li v-for="conv in recentHomeConversations" :key="conv.id">
                      <button type="button" class="wb-direct-starter-recent" @click="pickHomeConversation(conv.id)">
                        <span class="wb-direct-starter-recent__title">{{ conv.title || '新对话' }}</span>
                        <span class="wb-direct-starter-recent__time">{{ formatHomeConvTime(conv.updatedAt) }}</span>
                      </button>
                    </li>
                  </ul>
                </template>
              </div>
              </div>
              </div>
              </div>
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
                        aria-label="待发送附件"
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
                        :accept="DIRECT_ATTACHMENT_ACCEPT"
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

              <AgentMarket
                :open="showAgentMarket"
                :bots="allBots"
                @close="showAgentMarket = false"
                @start="onStartWithAgent"
                @create="onCreateAgent"
                @remove="onRemoveAgent"
                @favorite="onFavoriteAgent"
              />
              <VoicePhoneModal
                :open="showVoicePhone"
                :on-turn="handleVoicePhoneTurn"
                @close="showVoicePhone = false"
              />
              <MediaGenPanel
                :open="showMediaGen"
                :initial-tab="mediaGenInitialTab"
                :runner="mediaGenRunner"
                @close="showMediaGen = false"
                @insert="insertGeneratedToChat"
              />
          </template>

        <template v-if="wbSidebar.activeMode === 'make' && !wbNav.isMobile && !platformChatMode">
          <div v-if="tierPanelOpen && hasWorkflow && wbSidebar.activeMode === 'make'" class="wb-scene-panel" :key="'tier-make'">
            <ConsumptionTierControl v-model="consumptionTier" />
          </div>
          <header class="wb-make-hero" :class="{ 'wb-title-enter': titleEnterDone }">
        <p v-if="greetingLine" :key="'kicker-' + wbSidebar.activeMode" class="wb-hero-kicker">{{ makeKickerTw.displayed.value }}<span v-if="makeKickerTw.isTyping.value" class="wb-cursor">▌</span></p>
        <h1 :key="'hero-' + wbSidebar.activeMode" class="wb-hero-title">{{ makeTitleTw.displayed.value }}<span v-if="makeTitleTw.isTyping.value" class="wb-cursor">▌</span></h1>
      </header>
      <section
        v-if="hasWorkflow && planSession"
        ref="planPanelRef"
        class="wb-plan"
        :class="{ 'wb-plan--done': planSession.phase === 'done' }"
        aria-labelledby="wb-plan-title"
      >
        <Transition name="wb-plan-shell" appear>
          <div :key="planSurfaceKey" class="wb-plan-surface">
            <div class="wb-plan-head">
              <h2 id="wb-plan-title" class="wb-plan-title">{{ planPanelTitle }}</h2>
              <span v-if="planSession.phase === 'done'" class="wb-plan-done-badge">规划已完成</span>
              <button type="button" class="wb-plan-close" aria-label="关闭规划" @click="dismissPlanSession">×</button>
            </div>
            <div class="wb-plan-employee-badge">
              <span class="wb-plan-employee-dot" /><span class="wb-plan-employee-name">任务规划员工</span>
            </div>
            <div v-if="planSession.loading" class="wb-plan-loading-block" aria-live="polite">
              <span class="wb-plan-loading-speaker">
                <span class="wb-plan-msg-speaker-dot" /><span class="wb-plan-msg-speaker-name">任务规划员工</span>
              </span>
              <p v-if="planSession.streamingText" class="wb-plan-streaming-text">{{ planSession.streamingText }}<span class="wb-plan-cursor" /></p>
              <p v-else class="wb-plan-loading-lead">
                {{ planSession.phase === 'summary' ? '正在生成任务摘要…' : '正在规划中…' }}
              </p>
              <ol v-if="planLoadingStepLabelsForUi.length" class="wb-plan-loading-steps">
                <li
                  v-for="(step, si) in planLoadingStepLabelsForUi"
                  :key="`plan-step-${si}`"
                  class="wb-plan-loading-step"
                  :class="{
                    'wb-plan-loading-step--done': si < planLoadingAdvance,
                    'wb-plan-loading-step--active': si === planLoadingAdvance,
                  }"
                >
                  {{ step }}
                </li>
              </ol>
              <div class="wb-plan-loading-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="planLoadingProgressPercent">
                <span class="wb-plan-loading-progress__bar" :style="{ width: `${planLoadingProgressPercent}%` }" />
              </div>
              <button
                v-if="planSession.phase === 'summary'"
                type="button"
                class="wb-plan-loading-cancel"
                @click="cancelPlanSummary"
              >
                取消
              </button>
            </div>
            <TransitionGroup v-if="planSession.phase !== 'summary'" name="wb-plan-msg" tag="ul" class="wb-plan-thread" aria-live="polite">
              <li
                v-for="(m, idx) in planSession.messages"
                :key="`${m.role}-${idx}`"
                class="wb-plan-msg"
                :class="m.role === 'user' ? 'wb-plan-msg--user' : 'wb-plan-msg--assistant'"
              >
                <span class="wb-plan-msg-speaker" :class="m.role === 'user' ? 'wb-plan-msg-speaker--user' : 'wb-plan-msg-speaker--assistant'">
                  <span class="wb-plan-msg-speaker-dot" /><span class="wb-plan-msg-speaker-name">{{ m.role === 'user' ? '你' : '任务规划员工' }}</span>
                </span>
                <template v-if="m.role === 'user'">
                  <div class="wb-plan-msg-body">{{ m.content }}</div>
                </template>
                <template v-else>
                  <div class="wb-plan-msg-assistant-grid">
                    <div class="wb-plan-diagram-col">
                      <button
                        v-if="planAssistantParts(m.content).hasDiagram && !planDiagramError[idx]"
                        type="button"
                        class="wb-plan-diagram-preview-open"
                        title="完整查看架构图（可滚动）"
                        @click="() => void openPlanDiagramPreview(idx)"
                      >
                        完整预览
                      </button>
                      <div
                        v-if="!planAssistantParts(m.content).hasDiagram"
                        class="wb-plan-diagram-fallback"
                      >
                        暂无流程图，见详细
                      </div>
                      <div
                        v-else
                        :id="'wb-plan-mer-' + idx"
                        class="wb-plan-diagram-host"
                        :class="{
                          'wb-plan-diagram-host--with-preview':
                            planAssistantParts(m.content).hasDiagram && !planDiagramError[idx],
                        }"
                        aria-hidden="false"
                      />
                      <p v-if="planDiagramError[idx]" class="wb-plan-diagram-err" role="alert">
                        {{ planDiagramError[idx] }}
                      </p>
                    </div>
                    <aside class="wb-plan-aside-col">
                      <details
                        class="wb-plan-details"
                        :open="!planAssistantParts(m.content).hasDiagram"
                      >
                        <summary class="wb-plan-details-summary">详细</summary>
                        <div class="wb-plan-details-expand">
                          <div class="wb-plan-details-expand-inner">
                            <div class="wb-plan-details-body">{{ planAssistantParts(m.content).details }}</div>
                          </div>
                        </div>
                      </details>
                    </aside>
                  </div>
                </template>
              </li>
            </TransitionGroup>
            <p v-if="planSession.planError" class="wb-plan-error" role="alert">{{ planSession.planError }}</p>
            <template v-if="planSession.phase === 'summary'">
              <section
                v-if="!planSession.loading && planSession.summaryText && planSession.summaryNeedsClarification"
                class="wb-plan-summary-flow wb-plan-summary-flow--clarify"
                aria-label="待澄清信息"
              >
                <h3 class="wb-plan-summary-title">还需补充</h3>
                <p class="wb-plan-summary-body">{{ planSession.summaryText }}</p>
              </section>
              <section
                v-else-if="!planSession.loading && planSession.summaryText"
                class="wb-plan-summary-flow"
                aria-label="任务摘要确认"
              >
                <h3 class="wb-plan-summary-title">{{ planSession.summaryTitle || '请确认任务' }}</h3>
                <p class="wb-plan-summary-body">{{ planSession.summaryText }}</p>
                <p v-if="planSession.displayBrief" class="wb-plan-summary-source">{{ planSession.displayBrief }}</p>
              </section>
              <div class="wb-plan-actions">
                <button
                  type="button"
                  class="wb-plan-secondary"
                  :disabled="planSession.loading || autoPilotRunning"
                  @click="backSummaryToComposer"
                >
                  返回修改
                </button>
                <button
                  type="button"
                  class="wb-plan-primary"
                  :disabled="planSession.loading || autoPilotRunning || !planSession.summaryText || planSession.summaryNeedsClarification"
                  @click="() => void confirmSummaryAndStartPlanning()"
                >
                  确认并开始规划
                </button>
                <button
                  type="button"
                  class="wb-plan-primary wb-plan-autopilot"
                  :disabled="planSession.loading || autoPilotRunning || !planSession.summaryText"
                  :title="autoPilotRunning ? 'AI 正在自主跑完整个流程…' : '跳过澄清与确认，AI 自动跑完规划→清单→制作→生成'"
                  @click="() => void runAutoPilotFromSummary({ force: true })"
                >
                  {{ autoPilotRunning ? 'AI 自主进行中…' : 'AI 自主全部进行' }}
                </button>
              </div>
              <p v-if="autoPilotError" class="wb-plan-autopilot-error" role="alert">
                AI 自主流程失败：{{ autoPilotError }}
              </p>
            </template>
            <template v-if="planSession.phase === 'chat'">
              <div
                v-if="planQuickOptions.length"
                class="wb-plan-quick"
                :aria-label="planSession.intentKey === 'mod' ? '需求澄清（宿主为 FHD，技术栈已固定）' : '快捷选择'"
              >
                <div class="wb-plan-quick-main">
                  <div v-for="q in planQuickOptions" :key="q.id" class="wb-plan-quick-block">
                  <div class="wb-plan-quick-title">{{ q.title }}</div>
                  <div class="wb-plan-quick-chips" role="group" :aria-label="q.title">
                    <button
                      v-for="c in q.choices"
                      :key="q.id + '-' + c.id"
                      type="button"
                      class="wb-plan-chip"
                      :class="{ 'wb-plan-chip--on': planOptionSelections[q.id] === c.id }"
                      :disabled="planSession.loading"
                      @click="pickPlanOption(q.id, c.id)"
                    >
                      {{ c.label }}
                    </button>
                    <button
                      type="button"
                      class="wb-plan-chip wb-plan-chip--other"
                      :class="{ 'wb-plan-chip--on': planOptionSelections[q.id] === PLAN_OPTION_OTHER_ID }"
                      :disabled="planSession.loading"
                      :aria-pressed="planOptionSelections[q.id] === PLAN_OPTION_OTHER_ID"
                      :aria-label="`${q.title}：其他（自定义输入）`"
                      @click="pickPlanOption(q.id, PLAN_OPTION_OTHER_ID)"
                    >
                      其他
                    </button>
                  </div>
                  <div
                    v-if="planOptionSelections[q.id] === PLAN_OPTION_OTHER_ID"
                    class="wb-plan-other-wrap"
                  >
                    <label class="wb-sr-only" :for="'wb-plan-other-' + q.id">自定义：{{ q.title }}</label>
                    <textarea
                      :id="'wb-plan-other-' + q.id"
                      v-model="planOptionOtherText[q.id]"
                      class="wb-plan-other-input"
                      rows="2"
                      :placeholder="`填写「${q.title}」的自定义说明…`"
                      spellcheck="false"
                      :disabled="planSession.loading"
                    />
                  </div>
                  </div>
                  <button
                    type="button"
                    class="wb-plan-primary wb-plan-quick-send"
                    :disabled="planSession.loading || !canSendPlanQuickPicks"
                    @click="() => void sendPlanReplyFromQuickPicks()"
                  >
                    用以上选择发送
                  </button>
                </div>
                <aside class="wb-plan-quick-aside" aria-label="快捷操作">
                  <button
                    type="button"
                    class="wb-plan-quick-auto"
                    :disabled="planSession.loading"
                    title="为每道题选中第一个选项，可再手动调整"
                    @click="autoPickPlanQuickOptions"
                  >
                    一键自动选择
                  </button>
                </aside>
              </div>
              <div class="wb-plan-actions">
                <button
                  type="button"
                  class="wb-plan-secondary"
                  :disabled="planSession.loading || planSession.messages.length < 2"
                  title="至少完成一轮对话后再生成清单"
                  @click="() => void requestExecutionChecklist()"
                >
                  生成执行清单
                </button>
                <button
                  v-if="planSession.intentKey === 'employee'"
                  type="button"
                  class="wb-plan-primary wb-plan-autopilot"
                  :disabled="planSession.loading || autoPilotRunning"
                  :title="autoPilotRunning ? 'AI 正在自主跑完整个流程…' : '跳过剩余澄清，直接生成员工包'"
                  @click="() => void runAutoPilotFromChat()"
                >
                  {{ autoPilotRunning ? 'AI 自主进行中…' : '跳过澄清，直接开始生成' }}
                </button>
              </div>
              <p v-if="autoPilotError && planSession.intentKey === 'employee'" class="wb-plan-autopilot-error" role="alert">
                AI 自主流程失败：{{ autoPilotError }}
              </p>
            </template>
            <template v-else-if="planSession.phase === 'checklist' || planSession.phase === 'done'">
              <h3 class="wb-plan-checklist-title">执行清单（确认后将写入制作草稿）</h3>
              <div class="wb-plan-checklist-flow">
                <MessageBody :content="planChecklistFlowMarkdown" />
              </div>
              <details class="wb-plan-checklist-details">
                <summary>查看文字清单</summary>
                <ol class="wb-plan-checklist-ol">
                  <li v-for="(line, i) in planSession.checklistLines" :key="i" class="wb-plan-checklist-li">
                    {{ line }}
                  </li>
                </ol>
              </details>
              <div v-if="planSession.phase === 'checklist'" class="wb-plan-actions">
                <button type="button" class="wb-plan-secondary" :disabled="planSession.loading" @click="backPlanToChat">
                  返回修改
                </button>
                <button type="button" class="wb-plan-primary" :disabled="planSession.loading" @click="confirmPlanAndOpenHandoff">
                  确认清单并进入制作
                </button>
              </div>
            </template>
          </div>
        </Transition>
      </section>

      <section
        v-if="
          hasWorkflow &&
          orchestrationSession?.steps?.length
        "
        class="wb-orch-flow"
        aria-label="制作进度"
      >
        <div class="wb-orch-flow-head">
          <h3 class="wb-orch-flow-title">制作进度</h3>
          <span class="wb-orch-flow-percent">{{ orchestrationProgress.done }}/{{ orchestrationProgress.total }}</span>
        </div>
        <div class="wb-orch-flow-bar" aria-hidden="true">
          <span class="wb-orch-flow-bar__fill" :style="{ width: `${orchestrationProgress.percent}%` }"></span>
        </div>
        <ul class="wb-orch-flow-thread">
          <li
            v-for="st in orchestrationSession.steps"
            :key="st.id"
            class="wb-orch-flow-msg"
            :class="`wb-orch-flow-msg--${st.status}`"
          >
            <span class="wb-orch-flow-speaker">
              <span class="wb-orch-flow-speaker-dot" :style="{ background: orchStepColor(st) }" />
              <span class="wb-orch-flow-speaker-name" :style="{ color: orchStepColor(st) }">{{ orchStepEmployee(st) }}</span>
            </span>
            <template v-if="st.status === 'done'">
              <p class="wb-orch-flow-body wb-orch-flow-body--done">
                <span class="wb-orch-flow-check">✓</span>
                <span>{{ stepMsgSummary(st) || st.label + ' 完成' }}</span>
              </p>
            </template>
            <template v-else-if="st.status === 'running'">
              <p class="wb-orch-flow-body wb-orch-flow-body--running">
                <span>{{ stepMsgSummary(st) || '正在处理…' }}</span>
                <span v-if="stepMsgCurrentTool(st)" class="wb-orch-flow-tool">⚙ {{ stepMsgCurrentTool(st) }}</span>
                <span class="wb-orch-flow-cursor">▌</span>
              </p>
              <ol v-if="stepMsgTodos(st).length" class="wb-orch-flow-todos">
                <li
                  v-for="td in stepMsgTodos(st)"
                  :key="td.id"
                  class="wb-orch-flow-todo"
                  :class="`wb-orch-flow-todo--${td.status}`"
                >
                  <span class="wb-orch-flow-todo__dot" aria-hidden="true" />
                  <span class="wb-orch-flow-todo__text">{{ td.content }}</span>
                </li>
              </ol>
              <span v-if="orchStepRunningSec(st) !== null" class="wb-orch-flow-since">已运行 {{ formatWallClockSec(orchStepRunningSec(st)) }}</span>
              <span v-if="orchStepSlowHint(st) || stepMsgSlowHint(st)" class="wb-orch-flow-slow">模型响应较慢，仍在等待…</span>
            </template>
            <template v-else-if="st.status === 'error'">
              <p class="wb-orch-flow-body wb-orch-flow-body--error">
                <span class="wb-orch-flow-err-icon">✕</span>
                <span>{{ stepMsgSummary(st) || st.message || '步骤执行失败' }}</span>
              </p>
              <button type="button" class="wb-orch-flow-retry" @click="retryOrchStep(st)">重试整个制作</button>
            </template>
            <template v-else-if="st.status === 'pending'">
              <p class="wb-orch-flow-body wb-orch-flow-body--pending">{{ st.label }}</p>
            </template>
            <template v-else-if="st.status === 'skipped'">
              <p class="wb-orch-flow-body wb-orch-flow-body--skipped">
                {{ stepMsgSummary(st) || (typeof st.message === 'string' ? st.message : '') || '已跳过' }}
              </p>
            </template>
          </li>
        </ul>
        <p
          v-if="orchestrationSession?.artifact?.execution_mode === 'script' && orchestrationSession?.status === 'done'"
          class="wb-orch-flow-script-hint"
          role="status"
        >
          本次已按「附件 + Python 脚本」生成脚本工作流，稍后会进入沙箱调试页。
          你可以继续上传同类 Excel 文件，反复验证脚本输出是否正确。
        </p>
        <div v-if="orchestrationSession.script_result?.outputs?.length" class="wb-orch-flow-outputs">
          <h4 class="wb-orch-flow-outputs-title">生成结果</h4>
          <a
            v-for="file in orchestrationSession.script_result.outputs"
            :key="file.filename"
            class="wb-orch-flow-download"
            :href="file.download_url"
            target="_blank"
            rel="noopener noreferrer"
          >
            下载 {{ file.filename }}
          </a>
        </div>
        <details v-if="orchestrationSession.script_result" class="wb-orch-flow-log">
          <summary>查看脚本日志</summary>
          <pre>{{ orchestrationSession.script_result.stderr || orchestrationSession.script_result.stdout || '暂无日志' }}</pre>
        </details>
        <p
          v-if="orchestrationSession.validate_warnings?.length"
          class="wb-orch-flow-warn"
        >
          Python 语法提示：{{ orchestrationSession.validate_warnings.join('；') }}
        </p>
        <div
          v-if="orchQualityReport.length && (orchestrationSession?.status === 'done' || orchestrationSession?.status === 'error')"
          class="wb-orch-quality"
        >
          <h4 class="wb-orch-quality-title">
            质量检查
            <span v-if="orchQualityMeta?.score != null" class="wb-orch-quality-score">{{ orchQualityMeta.score }} 分</span>
          </h4>
          <p v-if="orchQualityMeta?.pipelineLabel === 'word_full_extract'" class="wb-orch-quality-hint">
            可提取 Word：{{ orchQualityMeta?.runnable ? '是' : '否（见下方未通过项）' }}
          </p>
          <p v-if="orchQualityMeta?.criticalFailed" class="wb-orch-flow-warn">
            关键质量项未通过，员工包不可用；请查看下方明细或重新制作。
          </p>
          <p v-if="orchVibecodingMeta" class="wb-orch-quality-hint">
            Vibecoding：{{ orchVibecodingMeta.source || '—' }}
            <template v-if="orchVibecodingMeta.round != null"> · 轮次 {{ orchVibecodingMeta.round }}</template>
            <template v-if="orchVibecodingMeta.parity != null"> · 黄金 parity {{ orchVibecodingMeta.parity }}</template>
            <template v-if="orchVibecodingMeta.diffCount"> · diff {{ orchVibecodingMeta.diffCount }}</template>
            <template v-if="orchVibecodingMeta.smokeOk != null">
              · 冒烟 {{ orchVibecodingMeta.smokeOk ? '通过' : '失败' }}
            </template>
          </p>
          <ul class="wb-orch-quality-list">
            <li
              v-for="(q, i) in orchQualityReport"
              :key="i"
              class="wb-orch-quality-item"
              :class="{
                'wb-orch-quality-item--ok': q.ok === true,
                'wb-orch-quality-item--warn': q.ok === false,
                'wb-orch-quality-item--skip': q.ok == null,
                'wb-orch-quality-item--critical': q.ok === false && q.critical,
              }"
            >
              <span class="wb-orch-quality-check">{{ q.ok === true ? '✓' : q.ok === false ? '✕' : '—' }}</span>
              <span>{{ q.check }}{{ q.note ? `（${q.note}）` : '' }}</span>
            </li>
          </ul>
        </div>
        <section
          v-if="makeCompletionResult && (orchestrationSession?.status === 'done' || orchestrationSession?.status === 'error')"
          ref="makeCompletionRef"
          class="wb-make-done"
          aria-labelledby="wb-make-done-title"
        >
          <div class="wb-make-done-head">
            <h3 id="wb-make-done-title" class="wb-make-done-title">{{ makeCompletionResult.title }}</h3>
            <p v-if="makeCompletionResult.subtitle" class="wb-make-done-sub">{{ makeCompletionResult.subtitle }}</p>
          </div>
          <ul v-if="makeCompletionResult.usageLines?.length" class="wb-make-done-howto">
            <li v-for="(line, i) in makeCompletionResult.usageLines" :key="i">{{ line }}</li>
          </ul>
          <div class="wb-make-done-actions">
            <button type="button" class="wb-make-done-primary" @click="() => void openMakeCompletionPrimary()">
              {{ makeCompletionResult.primaryLabel }}
            </button>
            <button
              v-if="makeCompletionResult.secondaryLabel"
              type="button"
              class="wb-make-done-secondary"
              @click="() => void openMakeCompletionSecondary()"
            >
              {{ makeCompletionResult.secondaryLabel }}
            </button>
            <button type="button" class="wb-make-done-ghost" @click="resetMakeComposer">开始新任务</button>
          </div>
        </section>
      </section>

      <section
        v-if="hasWorkflow && workflowLinkOffer"
        class="wb-handoff wb-workflow-link"
        aria-labelledby="wb-wf-link-title"
      >
        <div class="wb-handoff-head">
          <h2 id="wb-wf-link-title" class="wb-handoff-title">Skill 组已就绪</h2>
          <button type="button" class="wb-handoff-close" aria-label="关闭" @click="dismissWorkflowLinkOffer">×</button>
        </div>
        <p class="wb-workflow-link__name">{{ workflowLinkOffer.workflowName }}</p>
        <p v-if="!workflowLinkOffer.sandboxOk && workflowLinkOffer.validationErrors?.length" class="wb-handoff-error" role="alert">
          校验提示：{{ workflowLinkOffer.validationErrors.join('；') }}
        </p>
        <p v-if="workflowLinkOffer.llmWarnings?.length" class="wb-orch-warn">
          生成提示：{{ workflowLinkOffer.llmWarnings.join('；') }}
        </p>
        <label class="wb-handoff-label" for="wb-wf-link-mod">关联到 Mod（写入 manifest.workflow_employees）</label>
        <select
          id="wb-wf-link-mod"
          v-model="linkModId"
          class="wb-handoff-input"
        >
          <option value="">请选择 Mod…</option>
          <option v-for="m in linkMods" :key="m.id" :value="m.id">
            {{ m.id }}{{ m.name ? ` — ${m.name}` : '' }}
          </option>
        </select>
        <p v-if="linkError" class="wb-handoff-error" role="alert">{{ linkError }}</p>
        <div class="wb-handoff-actions wb-workflow-link__actions">
          <button
            type="button"
            class="wb-handoff-primary"
            :disabled="linkBusy || !linkModId"
            @click="() => void confirmWorkflowModLink()"
          >
            {{ linkBusy ? '写入中…' : '关联并打开 Mod' }}
          </button>
          <button type="button" class="wb-handoff-secondary" :disabled="linkBusy" @click="() => void openWorkflowCanvasOnly()">
            仅打开 Skill 组画布
          </button>
        </div>
      </section>

      <section
        v-if="hasWorkflow && pendingHandoff"
        ref="handoffPanelRef"
        class="wb-handoff"
        :class="{ 'wb-handoff--generating': finalizeLoading }"
        aria-labelledby="wb-handoff-title"
      >
        <div class="wb-handoff-head">
          <h2 id="wb-handoff-title" class="wb-handoff-title">制作草稿</h2>
          <button type="button" class="wb-handoff-close" aria-label="关闭" @click="dismissPendingHandoff">×</button>
        </div>
        <p class="wb-handoff-intent">类型：{{ pendingHandoff.intentTitle }}</p>
        <p v-if="finalizeLoading" class="wb-handoff-generating-note" role="status">制作已启动，进度见下方；可向上滚动查看规划与清单。</p>
        <div v-show="!finalizeLoading" class="wb-handoff-fields">
          <label class="wb-handoff-label" for="wb-handoff-desc">{{ handoffDescLabel }}</label>
          <textarea
            id="wb-handoff-desc"
            v-model="pendingHandoff.description"
            class="wb-handoff-textarea"
            rows="4"
            spellcheck="false"
          />
          <template v-if="isCanvasSkillIntent(pendingHandoff.intentKey)">
            <label class="wb-handoff-label" for="wb-handoff-name">Skill 组名称 <span class="wb-handoff-req">必填</span></label>
            <input
              id="wb-handoff-name"
              v-model="pendingHandoff.workflowName"
              type="text"
              class="wb-handoff-input"
              placeholder="例如：每日出货同步"
              autocomplete="off"
            />
            <label class="wb-handoff-label" for="wb-handoff-plan">框架与排期 <span class="wb-handoff-opt">选填</span></label>
            <textarea
              id="wb-handoff-plan"
              v-model="pendingHandoff.planNotes"
              class="wb-handoff-textarea wb-handoff-textarea--sm"
              rows="3"
              placeholder="例如：先画节点框架、预计本周完成初版…"
              spellcheck="false"
            />
          </template>
          <template v-else-if="pendingHandoff.intentKey === 'mod'">
            <label class="wb-handoff-label" for="wb-handoff-suggest">
              Mod ID（根据用户需求填写，相当于关键词；已预填可改）<span class="wb-handoff-opt">选填</span>
            </label>
            <input
              id="wb-handoff-suggest"
              v-model="pendingHandoff.suggestedModId"
              type="text"
              class="wb-handoff-input"
              placeholder="如 my-qq-watch，或一句便于检索/生成标识的关键词"
              autocomplete="off"
            />
          </template>
          <template v-else-if="pendingHandoff.intentKey === 'employee'">
            <label class="wb-handoff-label" for="wb-handoff-emp-target">员工包模式</label>
            <select id="wb-handoff-emp-target" v-model="pendingHandoff.employeeTarget" class="wb-handoff-input">
              <option value="pack_only">仅员工包（快速）</option>
              <option value="pack_plus_workflow">员工包 + 画布工作流</option>
            </select>
            <label class="wb-handoff-label" for="wb-handoff-emp-wf">
              画布工作流名称 <span class="wb-handoff-opt">选填</span>
            </label>
            <input
              id="wb-handoff-emp-wf"
              v-model="pendingHandoff.employeeWorkflowName"
              type="text"
              class="wb-handoff-input"
              placeholder="留空则使用包目录名"
              autocomplete="off"
            />
            <label class="wb-handoff-label" for="wb-handoff-fhd-url">
              FHD 根 URL（末尾 GET /api/mods/ 探测）<span class="wb-handoff-opt">选填</span>
            </label>
            <input
              id="wb-handoff-fhd-url"
              v-model="pendingHandoff.fhdBaseUrl"
              type="url"
              class="wb-handoff-input"
              placeholder="https://宿主:端口"
              autocomplete="off"
            />
          </template>
        </div>
        <p v-if="finalizeError" class="wb-handoff-error" role="alert">{{ finalizeError }}</p>
        <p v-if="handoffAssetNote" class="wb-handoff-asset-note">{{ handoffAssetNote }}</p>
        <div
          v-if="finalizeLoading && !orchestrationSession?.steps?.length"
          class="wb-handoff-run"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <p class="wb-handoff-run__boot">正在创建编排会话并拉取步骤，通常数秒内显示进度。</p>
        </div>
        <div v-if="!finalizeLoading" class="wb-handoff-actions">
          <button
            type="button"
            class="wb-handoff-primary"
            :disabled="finalizeLoading || !canRunOrchestration"
            @click="() => void runOrchestration()"
          >
            {{ finalizeLoading ? orchestrationButtonPendingLabel : orchestrationButtonLabel }}
          </button>
          <div
            v-if="finalizeLoading"
            class="wb-handoff-actions__timing"
            role="status"
            aria-live="polite"
            :title="orchestrationTimingTooltip"
          >
            <span class="wb-handoff-actions__timing-line">
              <span class="wb-handoff-actions__k">耗时参考</span>
              <span class="wb-handoff-actions__v">{{ orchestrationEtaDisplay }}</span>
            </span>
            <span class="wb-handoff-actions__timing-line">
              <span class="wb-handoff-actions__k">已用</span>
              <span class="wb-handoff-actions__v">{{ orchestrationElapsedDisplay }}</span>
            </span>
          </div>
        </div>
        <p class="wb-handoff-foot">{{ handoffFootNote }}</p>
      </section>

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
              :accept="DIRECT_ATTACHMENT_ACCEPT"
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
            aria-label="二档附件"
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
        </section>

            <section
              v-if="wbSidebar.activeMode === 'voice'"
              class="wb-mode-scene wb-voice-scene wb-voice-scene--no-contain"
              :class="{
                'wb-voice-scene--chatting': voiceMessages.length > 0 || voiceListening || voiceChatBusy,
                'wb-voice-scene--mobile': wbNav.isMobile,
              }"
            >
  <div
    v-show="!wbNav.isMobile || !voiceMessages.length"
    class="wb-voice-orb-area"
    :class="{ 'wb-voice-orb-area--active': voiceOrbActive && !wbNav.isMobile }"
  >
    <button
      type="button"
      class="wb-voice-orb-btn"
      :aria-label="voiceOrbHint || voiceTitle"
      @click="onOrbClick"
    >
      <SiriOrb
        :mode="voiceOrbMode"
        :progress="voiceProgress"
        :audio-level="voiceAudioLevel"
      />
    </button>
    <p v-if="voiceOrbHint" class="wb-voice-orb-hint">{{ voiceOrbHint }}</p>
    <p v-else-if="!voiceMessages.length" class="wb-voice-orb-status">{{ voiceStatusText }}</p>
  </div>
  <VoiceTaskPanels
    v-if="!platformChatMode"
    :plan-session="planSession"
    :pending-handoff="pendingHandoff"
    :orchestration-session="orchestrationSession"
    :orch-phase="orchPhase"
    :voice-inject-queue="voiceInjectQueue"
    :can-run-orch="canRunOrchestration"
    :orchestration-progress="orchestrationProgress"
    :finalize-loading="finalizeLoading"
    :finalize-error="finalizeError"
    :make-completion-result="makeCompletionResult"
    @confirm-generate="() => void runOrchestration()"
    @dismiss-handoff="dismissPendingHandoff"
    @dismiss-plan="() => void onVoiceDismissPlanPanel()"
    @open-completion="() => void openMakeCompletionPrimary()"
  />
  <div class="wb-voice-flow-host">
    <VoiceFlowPanel
      :messages="voiceMessages"
      :streaming="voiceChatPhase === 'streaming'"
      :live-text="voiceReport"
      :is-live-narrating="voiceAssistantSpeaking"
      :live-user-text="voiceMicPausedByUser ? '' : (voiceTranscript || voiceLivePreview)"
      :mic-paused="voiceMicPausedByUser"
      :recognizing="voiceListening && !voiceMicPausedByUser && Boolean(voiceTranscript || voiceLivePreview)"
      :speculating="voiceSpeculating"
    />
  </div>
  <Teleport to="body">
    <div
      v-if="wbSidebar.activeMode === 'voice'"
      class="wb-voice-bottom wb-voice-bottom--portal"
      :class="{ 'wb-voice-bottom--mobile': wbNav.isMobile }"
    >
      <div class="wb-voice-waveform-wrap" v-if="showVoiceWaveform" ref="waveformWrap">
        <canvas ref="waveformCanvas" class="wb-voice-waveform-canvas" width="720" height="28"></canvas>
      </div>
      <VoiceDock
        :mic-paused="voiceMicPausedByUser"
        :connecting="voiceAsrConnecting"
        :connecting-hint="voiceAsrAdapter.loadingHint.value"
        :recognizing="voiceDockRecognizing"
        :listening="voiceAsrListening"
        :mic-live="voiceMicLevelRaw() >= 0.004"
        :chat-busy="voiceChatBusy"
        :speculating="voiceSpeculating"
        :has-assistant-content="voiceHasAssistantContent"
        :voice-state="voiceState"
        :tts-active="streamingTts.state.value !== 'idle'"
        :work-phase="voiceWorkPhase"
        :asr-backend-label="voiceAsrBackendLabel"
        v-model:draft="voiceDockDraft"
        @toggle-mic="onVoiceMicToggle"
        @send="() => void onVoiceDockSend()"
      />
    </div>
  </Teleport>
  <p v-if="voiceError" class="wb-voice-error" role="alert">{{ voiceError }}</p>
  <p v-else-if="voiceMicFallbackHint" class="wb-voice-soft-hint" role="status">
    {{ voiceMicFallbackHint }}
  </p>
  <p
    v-else-if="voiceAsrAdapter.loadingHint.value && voiceListening && !voiceMicPausedByUser"
    class="wb-voice-loading-hint"
  >
    {{ voiceAsrAdapter.loadingHint.value }}
  </p>
</section>
      </div>
    </main>

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
  </div>
</template>

<script setup lang="ts">
import './workbench-home-v7.css'
import './workbench-home-ux.css'
import {
  ref,
  computed,
  reactive,
  onMounted,
  onActivated,
  onDeactivated,
  onUnmounted,
  onBeforeUnmount,
  nextTick,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { YUANGON_PKG_ROLE_LABELS } from '../domain/yuangonDutyRoster'
import { parseWbGearQuery } from '../domain/clientWorkshops'
import {
  readPlatformChatModePreference,
  writePlatformChatModePreference,
} from '../utils/workbenchPlatformChatMode'
import ConsumptionTierControl from '../components/workbench/ConsumptionTierControl.vue'
import MessageBody from '../components/workbench/MessageBody.vue'
import DirectFlowPanel from '../components/workbench/direct/DirectFlowPanel.vue'
import DirectMediaSettingsRail from '../components/workbench/direct/DirectMediaSettingsRail.vue'
import DirectGeneratedFileStack from '../components/workbench/direct/DirectGeneratedFileStack.vue'
import VoicePhoneModal from '../components/workbench/VoicePhoneModal.vue'
import SiriOrb from '../components/workbench/SiriOrb.vue'
import VoiceTaskPanels from '../components/workbench/voice/VoiceTaskPanels.vue'
import VoiceFlowPanel from '../components/workbench/voice/VoiceFlowPanel.vue'
import VoiceDock from '../components/workbench/voice/VoiceDock.vue'
import EmployeeSixDimModal from '../components/workbench/EmployeeSixDimModal.vue'
import PersonalSettings from '../components/workbench/PersonalSettings.vue'
import AgentMarket from '../components/workbench/AgentMarket.vue'
import MediaGenPanel from '../components/workbench/MediaGenPanel.vue'
import type { AgentBot } from '../utils/agentBots'
import {
  loadAllBots,
  loadMyBots,
  saveMyBots,
  loadFavorites,
  saveFavorites,
  loadActiveBotId,
  saveActiveBotId,
} from '../utils/agentBots'
import type { PersonalSettings as PersonalSettingsValue } from '../utils/personalSettings'
import {
  defaultPersonalSettings,
  loadPersonalSettings,
  savePersonalSettings,
  applyThemeToDocument,
} from '../utils/personalSettings'
import { api } from '../api'
import { clearAuthTokens, getAccessToken } from '../infrastructure/storage/tokenStore'
import type { ChatMessage, Conversation } from '../utils/conversationStore'
import {
  loadConversations,
  saveConversations,
  loadActiveId,
  saveActiveId,
  createConversation,
  makeMessage,
  summarizeForTitle,
  buildConversationTitle,
  exportConversationAsMarkdown,
  shouldReloadConversationFromStorage,
  mergeConversationsForPick,
} from '../utils/conversationStore'
import { detectOutputContract, outputContractSystemRules } from '../utils/detectOutputContract'
import { streamLLMChat } from '../utils/llmStream'
import type { StreamHandle } from '../utils/llmStream'
import { useWorkbenchSidebarStore } from '../stores/workbenchSidebar'
import { useWorkbenchNavStore } from '../stores/workbenchNav'
import { sanitizeMermaidSource, friendlyMermaidRenderError } from '../utils/mermaidSanitize'
import {
  computeOrchProgress,
  mergeOrchStepsMonotonic,
  orchStepColor,
  orchStepEmployee,
} from '../utils/orchestrationSteps'
import { requestMicInUserGesture } from '../composables/asr/micPreflight'
import { useSpeechRecognition } from '../composables/useSpeechRecognition'
import type { ASRBackendId, ASRResult } from '../composables/asr/types'
import { useStreamingTts, ttsConfigFromPersonalSettings } from '../composables/useStreamingTts'
import { useVoiceS2SSession } from '../composables/useVoiceS2SSession'
import { useVoiceUnifiedSession, createUnifiedAsrBridge } from '../composables/useVoiceUnifiedSession'
import { executeVoiceBargeIn, shouldTriggerVoiceBargeIn } from '../composables/voiceBargeIn'
import { isVoiceSpeculativeFiller } from '../composables/voiceSpeculativeFiller'
import { clearVoiceLatencyMarks } from '../composables/voiceLatency'
import { unlockVoiceAudioPlayback } from '../composables/voiceDevice'
import { createVoiceWorkbenchState } from '../composables/useVoiceWorkbench'
import { useVoiceContinuousChat } from '../composables/useVoiceContinuousChat'
import { appendCoalescedVoiceUserTurn } from '../composables/voiceUserTurnCoalesce'
import {
  appendVoiceInject,
  buildOrchestrationStatusSummary,
  hasEmployeePlanContext,
  hasVoiceWorkIntent,
  inferUserGoalFromVoiceMessages,
  isLikelyShortProceedFragment,
  looksLikeEmployeeTaskDescription,
  routeVoiceUtterance,
} from '../composables/voiceUtteranceRouter'
import {
  applyVoiceSessionPatch,
  buildAgentAwarePrompt,
  buildPlanBriefFromSessionState,
  buildPlanBriefFromVoiceMessages,
  classifyVoiceTurn,
  sanitizeVoiceUtteranceText,
  isLikelyAsrEchoNoise,
  isPlaceholderPlanContent,
  pickBestEmployeeBriefFromVoice,
  formatFilteredPlanMessagesForBrief,
  buildDefaultEmployeePlanAssistantReply,
  createDefaultVoiceSessionState,
  isSummaryNeedsClarification,
  resetVoiceSessionState,
  type VoiceSessionState,
  type VoiceTurnClassification,
} from '../composables/voiceSessionAgent'
import { cleanTextForTts } from '../utils/ttsTextClean'
import { stripInternalMarkers } from '../utils/lightMarkdown'
import {
  employeeDownloadsToGeneratedFiles,
  filterUserFacingOfficeDownloads,
  mergeGeneratedFiles,
  softenSandboxDownloadLinks,
  type DirectGeneratedFile,
} from '../utils/directGeneratedFiles'
import {
  planComposerAttachmentStrip,
  planHeaderGeneratedStrip,
} from '../utils/workbenchFileStripPlan'
import { useButlerWorkbenchTrayStore } from '../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../stores/butlerDownloadHistory'
import { useAgentStore } from '../stores/agent'
import { showAppToast } from '../composables/useAppToast'
import {
  inlineVoiceAriaLabel,
  inlineVoiceStatusLabel,
  isMicPermissionError,
  resolveInlineVoicePhase,
} from '../composables/inlineVoiceUi'
import {
  DIRECT_ATTACHMENT_ACCEPT,
  DIRECT_EMPLOYEE_FILE_MAX_BYTES,
  DIRECT_KB_MAX_BYTES,
  DIRECT_KB_SUPPORTED_EXT,
  DIRECT_KB_SUPPORTED_EXTENSIONS,
  directFileExt,
  directFileKind,
  directFileKindLabel,
  formatDirectFileSize,
  isEmployeeExecuteFileExt,
  isEmployeeSpreadsheetExt,
  resolveDirectAttachmentOutcome,
  resolveReadEmployeeForExtension,
} from '../utils/directAttachments'
import {
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  extractEmployeeReadTextForLlm,
  formatEmployeeReadResultSummary,
  isGenerateEmployeeId,
  parseEmployeeOutputDownloads,
  readEmployeeDisplayName,
  TABULAR_READ_EMPLOYEE_IDS,
} from '../utils/tabularReadEmployees'
import {
  assistantGaveManualOfficeStepsOnly,
  assistantImpliesPendingFileGeneration,
  classifyOfficeTask,
  collectOfficeAttachmentNamesFromMessages,
  collectRecentUserIntentText,
  detectOfficeDocumentCreateIntent,
  detectOfficeEnhanceAttachedIntent,
  detectOfficeGenerateIntent,
  detectUserMissingDeliverableComplaint,
  mergeOfficeAttachmentNames,
  officeEmployeeCapabilitySystemHint,
  officeGenerateMissingInputMessage,
  pickPptTemplateFromSources,
  primaryOfficeFormatFromAttachments,
  shouldHandleAsOfficeTask,
  shouldRecoverOfficeGenerate,
  starterRequiresAttachment,
  type OfficeFormat,
} from '../utils/officeEmployeeOrchestration'
import {
  pickGenerateFormat,
  runOfficeGeneratePhase,
  runOfficeReadPhase,
} from '../utils/officeEmployeeRunner'

/** 从需求正文猜一个 Mod ID（与后端 normalize_mod_id 规则对齐，可全中文时回退为 mod-<时间戳>） */
function suggestModIdFromText(raw: string): string {
  const normalize = (x: string) =>
    x
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '')
  let t = normalize(String(raw || ''))
  if (!t || !/^[a-z0-9]/.test(t)) {
    t = `mod-${Date.now().toString(36)}`
  }
  if (t.length > 48) {
    t = normalize(t.slice(0, 48))
  }
  if (!/^[a-z0-9][a-z0-9._-]*$/.test(t)) {
    t = `mod-${Date.now().toString(36)}`
  }
  return t
}

/** 与后端 llm_model_taxonomy.CATEGORY_ORDER 一致 */
const LLM_CATEGORY_ORDER = ['llm', 'vlm', 'image', 'video', 'other']

const router = useRouter()
const route = useRoute()
const wbSidebar = useWorkbenchSidebarStore()
const wbNav = useWorkbenchNavStore()
const draft = ref('')
const displayName = ref('')
const inputRef = ref(null)
const handoffPanelRef = ref(null)
/** 发送后暂存在页顶；补全并创建成功后才跳转画布 */
const pendingHandoff = ref(null)
const makeCompletionResult = ref(null)
const employeeSixDimModalOpen = ref(false)
const employeeSixDimReport = ref(null)
const makeCompletionRef = ref(null)
const finalizeLoading = ref(false)
const finalizeError = ref('')
/** 编排轮询中的会话快照（含 steps） */
const orchestrationSession = ref(null)
const orchestrationSessionId = ref('')
const pollStop = ref(false)
/** 编排：估算耗时阶段 → 正式执行（估算结束后才开始「已用」计时） */
const orchPhase = ref('idle')
const orchestrationEtaSeconds = ref(null)
const orchestrationEtaReason = ref('')
let orchElapsedTimer = null
const orchTimingStartMs = ref(null)
/** 每 500ms 递增，驱动已用时间的 computed 刷新 */
const orchElapsedTick = ref(0)
/** 工作流编排成功后的「关联 Mod」卡片 */
const workflowLinkOffer = ref(null)
const linkMods = ref([])
const linkModId = ref('')
const linkBusy = ref(false)
const linkError = ref('')

/** 需求规划：多轮澄清 → 执行清单 → 再进入制作草稿 */
const planSession = ref(null)
const planReplyDraft = ref('')
/** 「AI 自主全部进行」：从 summary 一路串到 runOrchestration 结束的互斥锁 */
const autoPilotRunning = ref(false)
const autoPilotError = ref('')
/** 用户 pause_checklist 后跳过清单自动开跑 */
const voiceChecklistPaused = ref(false)
/** 快捷选项：题目 id -> 选中的 choice id（含 UI 专用「其他」） */
const planOptionSelections = ref({})
/** 「其他」在提交与 canSend 中使用的保留 choice id（勿与模型返回的 id 重复） */
const PLAN_OPTION_OTHER_ID = '__plan_ui_other__'
/** 题目 id -> 「其他」时的自定义文案 */
const planOptionOtherText = reactive({})

function clearPlanOptionOtherText() {
  for (const k of Object.keys(planOptionOtherText)) {
    delete planOptionOtherText[k]
  }
}
const planPanelRef = ref(null)
/** 每次打开规划会话递增，用于 Transition 内层 :key 触发动画 */
const planSurfaceKey = ref(0)

const MAKE_PROGRESS_CACHE_KEY = 'workbench_home_make_progress_v1'
const MAKE_PROGRESS_CACHE_TTL_MS = 24 * 60 * 60 * 1000

/** 需求规划加载区：分步提示（定时推进当前步，减少「卡住」感） */
const planLoadingStepsSummary = Object.freeze([
  '校验登录与默认模型',
  '读取任务描述与上传材料',
  '请求模型生成摘要（较慢时可能需数十秒）',
  '写入确认卡片',
])
const planLoadingStepsChat = Object.freeze([
  '校验登录与默认模型',
  '整理本轮对话与隐藏上下文',
  '发起模型上游请求',
  '等待模型输出（长任务可能需数十秒）',
  '解析流程图与快捷选项格式',
  '写入本条助手回复',
])
const planLoadingAdvance = ref(0)
let planLoadingIntervalId = null

const planLoadingStepLabelsForUi = computed(() => {
  if (!planSession.value?.loading) return []
  return planSession.value.phase === 'summary' ? planLoadingStepsSummary : planLoadingStepsChat
})

const planLoadingProgressPercent = computed(() => {
  const list = planLoadingStepLabelsForUi.value
  if (!list.length) return 0
  const max = Math.max(1, list.length - 1)
  return Math.round((planLoadingAdvance.value / max) * 100)
})

const llmMobilePickerSummary = computed(() => {
  if (modelMode.value === 'auto') return '模型 · Auto'
  const model = selectedModel.value || '未选'
  return `模型 · ${currentProviderLabel.value} / ${model}`
})

const knowledgeStatus = ref(null)
const knowledgeDocs = ref([])
const knowledgeLoading = ref(false)
const knowledgeUploading = ref(false)
const knowledgeError = ref('')
const knowledgeFileInputRef = ref(null)
const knowledgeDragActive = ref(false)

/** 调 /api/knowledge/search 之前的预检：未配置 Embedding Key 时直接跳过 RAG，
 *  避免一档对话 / 二档制作发送时连带产生 503 与「未配置可用 Embedding Key」横幅，
 *  这条横幅原本只是提示性的，但放在 catch 里会让用户误以为业务流程失败。 */
function isEmbeddingConfigured(): boolean {
  const st = knowledgeStatus.value as any
  return Boolean(st?.embedding?.configured)
}
/** 与下方 starter 同步：仅标记制作类型，不写入输入框（画布 Skill 组 intent 为 `skill`） */
const CANVAS_SKILL_INTENT = 'skill'
function isCanvasSkillIntent(k: string | undefined | null): boolean {
  return k === CANVAS_SKILL_INTENT || k === 'workflow'
}
const composerIntent = ref(CANVAS_SKILL_INTENT)
const modFrontendEnabled = ref(true)
const activeGear = ref('make')

const hasModRepo = computed(() => hasWorkflow.value)
const hasEmployeeIntent = computed(() => hasWorkflow.value)

function isMakeToolbarIntentActive(intent: string): boolean {
  if (intent === 'employee') {
    return hasWorkflow.value && composerIntent.value === 'employee'
  }
  if (intent === CANVAS_SKILL_INTENT) {
    return hasWorkflow.value && composerIntent.value === CANVAS_SKILL_INTENT
  }
  return composerIntent.value === intent
}

/** 侧栏「聊」：纯文字对话 */
const showDirectChatSurface = computed(() => wbSidebar.activeMode === 'direct')

/** 「做」+ 平台模式：内嵌对话区（不复用「聊」空态卡片，标题/引导不同） */
const showMakePlatformCasualChat = computed(
  () => wbSidebar.activeMode === 'make' && platformChatMode.value,
)

/** 任一档位展示 direct 消息流（聊 或 做·平台） */
const showDirectStyleConversation = computed(
  () => showDirectChatSurface.value || showMakePlatformCasualChat.value,
)

const platformChatMode = ref(readPlatformChatModePreference())
/** 「说」里退出做员工/Skill 后：仅常态化闲聊，勿因历史消息再进员工规划 */
const voiceCasualChatMode = ref(false)

const voiceHumanChatMode = computed(
  () =>
    platformChatMode.value ||
    voiceCasualChatMode.value ||
    (
      wbSidebar.activeMode === 'voice' &&
      !planSession.value &&
      !pendingHandoff.value &&
      !finalizeLoading.value &&
      !orchestrationSessionId.value &&
      orchPhase.value === 'idle'
    ),
)

function voiceSessionModeForIntent(intent: string): VoiceSessionState['mode'] {
  if (intent === 'employee') return 'employee'
  if (intent === 'mod') return 'mod'
  return 'skill'
}

function clearMakePanelsForCasualChat() {
  pollStop.value = true
  dismissPendingHandoff()
  dismissPlanSession()
  workflowLinkOffer.value = null
  makeCompletionResult.value = null
  employeeSixDimModalOpen.value = false
  employeeSixDimReport.value = null
  tierPanelOpen.value = false
  empPanelOpen.value = false
  pickEmployeeKey.value = ''
  pickModId.value = ''
  finalizeError.value = ''
  resetVoiceSessionState(voiceSessionState, voiceSessionModeForIntent(composerIntent.value))
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  syncVoiceWorkPhase()
}

function persistPlatformChatMode(on: boolean) {
  platformChatMode.value = on
  writePlatformChatModePreference(on)
}

function resumeVoiceListeningInSayMode() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (voiceMicPausedByUser.value) {
    resumeVoiceMic()
    return
  }
  if (!voiceListening.value) {
    streamingTts.warmUp()
    void startVoiceRecognition({ fresh: true })
  }
}

/** 留在当前档位，进入一档正常聊天（不跳侧栏「聊」、不触发制作/Skill 任务） */
function enablePlatformChatMode() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = true
  persistPlatformChatMode(true)
  composerIntent.value = CANVAS_SKILL_INTENT
  clearMakePanelsForCasualChat()
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}

function disablePlatformChatMode() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = false
  persistPlatformChatMode(false)
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}

/** 平台模式：隐藏做 Mod/做员工等，留在当前档位（说/做），不跳到侧栏「聊」 */
function togglePlatformChatMode() {
  if (platformChatMode.value) disablePlatformChatMode()
  else enablePlatformChatMode()
}

/** 再点已选中的「做 Mod / 做员工 / Skill 组」→ 退出制作态，留在「说/做」常态化聊天 */
function exitMakeToolbarToCasualChat() {
  const stayMode = wbSidebar.activeMode
  voiceCasualChatMode.value = true
  persistPlatformChatMode(false)
  composerIntent.value = CANVAS_SKILL_INTENT
  clearMakePanelsForCasualChat()
  resumeVoiceListeningInSayMode()
  if (wbSidebar.activeMode !== stayMode) {
    wbSidebar.setActiveMode(stayMode)
    activeGear.value = stayMode
  }
}

function switchMakeIntent(intent: string) {
  if (isMakeToolbarIntentActive(intent)) {
    if (
      planSession.value ||
      autoPilotRunning.value ||
      pendingHandoff.value ||
      finalizeLoading.value ||
      orchPhase.value === 'running' ||
      orchPhase.value === 'estimating'
    ) {
      return
    }
    exitMakeToolbarToCasualChat()
    return
  }
  voiceCasualChatMode.value = false
  if (platformChatMode.value) {
    persistPlatformChatMode(false)
  }
  composerIntent.value = intent
  if (wbSidebar.activeMode === 'voice') {
    resetVoiceSessionState(voiceSessionState, voiceSessionModeForIntent(intent))
    voiceSessionState.value.stage = 'exploring'
    voiceSessionState.value.readyToPlan = false
    syncVoiceWorkPhase()
  }
}
const directDraft = ref('')
const directPlaceholder = computed(() => {
  if (wbSidebar.activeMode === 'make') return '描述需求…'
  return '输入问题…'
})
const directFileInputRef = ref(null)
/**
 * 直接聊天待发送的本地附件。每项形如：
 *   { id, name, size, status: 'uploading'|'ready'|'error'|'skipped', docId, error, file }
 * - status='ready' 的文档已上传到当前用户知识库（doc_id），发送时会做向量检索并拼到 system prompt。
 * - status='skipped'/'error' 的文件不上传，只在消息中附带文件名说明。
 */
const directAttachedFiles = ref([])
const directGeneratedFiles = ref<DirectGeneratedFile[]>([])
/** 按会话缓存读取员工 raw 结果，供追问「做动画」时生成员复用（附件发送后已从输入区移除）。 */
const officeReadCacheByConversation = new Map<
  string,
  Array<{ name: string; employeeId: string; result: unknown }>
>()
type DirectGeneratingFileState = { active: true; format: OfficeFormat; label?: string }
const directGeneratingFile = ref<DirectGeneratingFileState | null>(null)

const directGeneratingFormatLabel = computed(() => {
  const fmt = directGeneratingFile.value?.format
  if (!fmt) return 'FILE'
  switch (fmt) {
    case 'excel':
      return 'Excel'
    case 'pdf':
      return 'PDF'
    case 'csv':
      return 'CSV'
    case 'ppt':
      return 'PPT'
    default:
      return 'Word'
  }
})

/** 顶栏仅展示已生成/生成中，与底部「待发送附件」隔离 */
const showDirectHomeFileStrip = computed(
  () =>
    showDirectStyleConversation.value &&
    (directGeneratedFiles.value.length > 0 || Boolean(directGeneratingFile.value?.active)),
)

const directLoading = ref(false)
/** 已 append 气泡、尚未进入 runDirectChatTurn 的短暂窗口 */
const directSendPending = ref(false)
const directError = ref('')
const directVoiceListening = ref(false)
const directVoiceAudioLevel = ref(0)
const directWaveformCanvas = ref<HTMLCanvasElement | null>(null)
const ttsAutoRead = ref(true)
const currentThemeIsLight = ref(false)
const isLightTheme = computed(() => currentThemeIsLight.value)
function toggleTheme() {
  const next: 'dark' | 'light' = currentThemeIsLight.value ? 'dark' : 'light'
  personalSettings.value.theme = next
  applyThemeToDocument(next)
  currentThemeIsLight.value = next === 'light'
  try { savePersonalSettings(personalSettings.value) } catch { /* ignore */ }
}
const makeVoiceListening = ref(false)
const directVoiceRecognizing = ref(false)
const makeVoiceRecognizing = ref(false)
const directVoicePermissionHint = ref('')
const makeVoicePermissionHint = ref('')
let inlineVoicePrefix = ''
let inlineVoiceTarget: 'direct' | 'make' | 'voice' | null = null
let inlineHoldActive = false
let inlineHoldPointerId = -1
let inlineHoldCancelIntent = false
let inlineHoldStartY = 0

/** 一档直接聊天：单选绑定员工 id（优先于人设 id 参与知识检索）；sessionStorage 持久化 */
const WB_DIRECT_CHAT_EMPLOYEE_ID_KEY = 'wb_direct_chat_employee_id'
const WB_DIRECT_WEB_SEARCH_KEY = 'wb_direct_web_search_v1'
const WB_DIRECT_IMAGE_GEN_KEY = 'wb_direct_image_gen_v1'
const WB_DIRECT_VIDEO_GEN_KEY = 'wb_direct_video_gen_v1'
type DirectEmployeeOption = { id: string; name: string; sourceLabel: string }
const directChatEmployeeId = ref('')
const directEmployeeOptions = ref<DirectEmployeeOption[]>([])
const directWebSearchEnabled = ref(false)
const directWebSearching = ref(false)
const directImageGenEnabled = ref(false)
const directVideoGenEnabled = ref(false)
const directMediaGenerating = ref(false)
const directImageSize = ref('1024x1024')
const directImageStyle = ref('default')
const directImageCount = ref(1)
const directVideoAspect = ref('16:9')
const directVideoDurationSec = ref(10)

// === 一档「直接聊天」会话管理 / 流式 / 多模态 / 工具栏 / 个性化 ===
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<string>('')
const activeConversation = computed<Conversation | null>(
  () => conversations.value.find((c) => c.id === activeConversationId.value) || null,
)
const directMessages = computed<ChatMessage[]>(() => activeConversation.value?.messages || [])
const directIsDragging = ref(false)
let currentStreamHandle: StreamHandle | null = null
const editingMessageId = ref<string>('')
const editingDraft = ref<string>('')
const personalSettings = ref<PersonalSettingsValue>(defaultPersonalSettings())
const personalSettingsOpen = ref(false)

const streamingTts = useStreamingTts(() => ttsConfigFromPersonalSettings(personalSettings.value))
const voiceS2s = useVoiceS2SSession()
const voiceUnified = useVoiceUnifiedSession()
const unifiedAsrBridge = createUnifiedAsrBridge(voiceUnified)
let ttsStreamAssistantId = ''

const voiceUseUnified = computed(
  () =>
    personalSettings.value.voiceSpeechMode === 'unified' &&
    personalSettings.value.ttsEngine === 'edge-online' &&
    ttsAutoRead.value,
)

const voiceUseS2S = computed(
  () =>
    !voiceUseUnified.value &&
    personalSettings.value.voiceSpeechMode === 's2s' &&
    personalSettings.value.ttsEngine === 'edge-online' &&
    ttsAutoRead.value,
)

/** unified 或 s2s：流式判停 + provisional 开答（豆包式电话体验） */
const voiceUsePhonePipeline = computed(() => voiceUseUnified.value || voiceUseS2S.value)

let s2sProvisionalTurnId = ''
let s2sProvisionalStarted = false
let s2sProvisionalAssistantIdx = -1

watch(
  () => [wbSidebar.activeMode, voiceUseS2S.value, voiceUseUnified.value] as const,
  ([mode, s2s, unified]) => {
    if (mode === 'voice' && s2s) {
      void voiceS2s.connect().catch(() => {})
    } else {
      voiceS2s.disconnect()
    }
    if (mode === 'voice' && unified) {
      void voiceUnified.connect().catch(() => {})
    } else {
      voiceUnified.disconnect()
    }
  },
  { immediate: true },
)

function onPersonalSettingsUpdate(v: PersonalSettingsValue) {
  personalSettings.value = v
  try {
    savePersonalSettings(v)
    applyThemeToDocument(v.theme)
    currentThemeIsLight.value = v.theme === 'light' || (v.theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: light)').matches)
  } catch {
    /* ignore */
  }
}
const showAgentMarket = ref(false)
const showVoicePhone = ref(false)
const showMediaGen = ref(false)
const mediaGenInitialTab = ref<'image' | 'video' | 'ppt' | 'doc'>('image')
const allBots = ref<AgentBot[]>([])
const activeBotId = ref<string>('')
const activeBot = computed<AgentBot | null>(
  () => allBots.value.find((b) => b.id === activeBotId.value) || null,
)
/** 对话进行中：左上角一行当前主题（会话标题或最近用户提问摘要） */
const directTaskLine = computed(() => {
  const convTitle = String(activeConversation.value?.title || '').trim()
  if (convTitle && convTitle !== '新对话') return convTitle
  const latestUser = [...directMessages.value].reverse().find((m) => m.role === 'user')
  const raw = stripInternalMarkers(latestUser?.content || '').replace(/\s+/g, ' ').trim()
  if (raw) return summarizeForTitle(raw)
  if (activeBot.value?.name) return `${activeBot.value.name} · 对话中`
  return '对话中'
})
const speakingMessageId = ref<string>('')
function stopDirectTtsPlayback() {
  streamingTts.stop()
}

const directCanSend = computed(() => {
  if (String(directDraft.value || '').trim()) return true
  const files = directAttachedFiles.value
  if (!files.length) return false
  if (files.some((f) => f.status === 'uploading')) return false
  return files.some(
    (f) =>
      (f.purpose === 'employee' && f.status === 'ready' && f.file) ||
      (f.purpose !== 'employee' && (f.status === 'ready' || f.status === 'inline')),
  )
})
const directSendDisabled = computed(() => directLoading.value || !directCanSend.value)

const directAttachHint = computed(() => {
  const list = directAttachedFiles.value
  if (!list.length) return ''
  const empReady = list.filter((f) => f.purpose === 'employee' && f.status === 'ready').length
  const ready = list.filter((f) => f.purpose !== 'employee' && f.status === 'ready').length
  const uploading = list.filter((f) => f.status === 'uploading').length
  const inlined = list.filter((f) => f.purpose !== 'employee' && f.status === 'inline').length
  const skipped = list.filter((f) => f.status === 'skipped').length
  const errored = list.filter((f) => f.status === 'error').length
  const parts: string[] = []
  if (uploading) parts.push(`${uploading} 个读取中`)
  if (empReady) parts.push(`${empReady} 个将由读取员工全量解析（发送时直传原文件）`)
  if (ready) parts.push(`${ready} 个已纳入资料库（提问时按相关度自动召回）`)
  if (inlined) parts.push(`${inlined} 个已读取，可直接发送给模型`)
  const embLabels = Array.from(
    new Set(
      list
        .map((f) => formatEmbeddingLabel(f.embedding))
        .filter(Boolean),
    ),
  )
  if (embLabels.length) parts.push(`向量索引：${embLabels.join('、')}`)
  if (skipped) parts.push(`${skipped} 个未受支持，仅附文件名给模型参考`)
  if (errored) parts.push(`${errored} 个上传失败，仅附文件名给模型参考`)
  return parts.join(' · ')
})
const butlerTrayStore = useButlerWorkbenchTrayStore()
const butlerDownloadHistory = useButlerDownloadHistoryStore()
const agentStore = useAgentStore()

const headerGeneratedStripPlan = computed(() =>
  planHeaderGeneratedStrip(directGeneratedFiles.value.length),
)
const composerAttachmentStripPlan = computed(() =>
  planComposerAttachmentStrip(directAttachedFiles.value.length),
)
const headerFileStripPlan = computed(() => ({
  stripGeneratedCount: headerGeneratedStripPlan.value.stripGeneratedCount,
  stripAttachmentCount: 0,
  overflowAttachmentCount: composerAttachmentStripPlan.value.overflowCount,
  overflowGeneratedCount: headerGeneratedStripPlan.value.overflowGeneratedCount,
  overflowCount:
    headerGeneratedStripPlan.value.overflowCount + composerAttachmentStripPlan.value.overflowCount,
}))
/** 二档 / 做 Mod 作曲栏附件卡片 */
const directVisibleAttachedFiles = computed(() => {
  const count = composerAttachmentStripPlan.value.visibleCount
  const list = directAttachedFiles.value
  if (count <= 0) return []
  return list.slice(Math.max(0, list.length - count))
})
/** 一档直接对话：输入区待发送附件（与顶栏下载区隔离） */
const directComposerVisibleFiles = directVisibleAttachedFiles
const butlerFileOverflowCount = computed(() => headerFileStripPlan.value.overflowCount)
const directHiddenAttachmentCount = computed(() => composerAttachmentStripPlan.value.overflowCount)
const directComposerHiddenCount = directHiddenAttachmentCount

function openButlerFileTray() {
  agentStore.openPanel({ focusFiles: true })
}

watch(
  () => [directAttachedFiles.value, directGeneratedFiles.value] as const,
  ([atts, gens]) => {
    butlerTrayStore.setWorkbenchFiles({
      attachments: atts.map((f) => ({
        id: String(f.id || ''),
        name: String(f.name || ''),
        status: String(f.status || ''),
        purpose: f.purpose,
        ingesting: f.ingesting,
      })),
      generated: gens,
    })
  },
  { deep: true, immediate: true },
)
const directAttachmentMentions = computed(() =>
  directAttachedFiles.value
    .map((f) => String(f?.name || '').trim())
    .filter(Boolean),
)
const CONSUMPTION_TIER_STORAGE_KEY = 'workbench_consumption_tier'

function readStoredConsumptionTier(): number {
  try {
    const raw = sessionStorage.getItem(CONSUMPTION_TIER_STORAGE_KEY)
    const n = raw == null ? NaN : parseInt(raw, 10)
    if (Number.isFinite(n) && n >= 1 && n <= 10) return n
  } catch {
    /* ignore */
  }
  return 5
}

/** 直接聊天右上角「消费档位」1–10：占位；与右侧工作台 1/2/3 挡位无关 */
const consumptionTier = ref(readStoredConsumptionTier())
const tierPanelOpen = ref(false)
const empPanelOpen = ref(false)
const empDropdownOpen = ref(false)
const tierTriggerRef = ref<HTMLElement | null>(null)
const empTriggerRef = ref<HTMLElement | null>(null)
const tierPanelAnchorStyle = ref<Record<string, string>>({})
const empPanelAnchorStyle = ref<Record<string, string>>({})

const homeStarterCards = [
  {
    label: '总结文档',
    desc: '上传 Word/PDF 等，由读取员工解析后总结',
    prompt: '请帮我总结这份文档的要点',
    requiresAttachment: true,
  },
  {
    label: '分析 Excel',
    desc: '上传 .xlsx/.csv，由读取员工解析后分析',
    prompt: '请帮我分析表格数据并给出结论',
    requiresAttachment: true,
  },
  {
    label: '生成 Word',
    desc: '直接描述内容，或上传 docx / JSON 模板后生成',
    prompt: '请生成一份可下载的 Word（docx）文档，标题为季度总结，正文包含三个要点',
    requiresAttachment: false,
  },
  { label: '写方案', desc: '从大纲到完整方案，一键生成', prompt: '请帮我写一份可执行的方案' },
  { label: '调员工', desc: '选择 AI 员工，按岗位能力回答', prompt: '帮我选择合适的 AI 员工并说明能做什么' },
] as const

const homeSuggestionChips = computed(() => loadPersonalSettings().suggestions.slice(0, 3))

const recentHomeConversations = computed(() =>
  [...conversations.value]
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, 2),
)

function updateTierPanelAnchor() {
  if (!tierTriggerRef.value) {
    tierPanelAnchorStyle.value = {}
    return
  }
  const r = tierTriggerRef.value.getBoundingClientRect()
  const panelMaxH = wbNav.isMobile ? 360 : 400
  const top = Math.min(r.bottom + 8, window.innerHeight - panelMaxH - 12)
  tierPanelAnchorStyle.value = {
    '--wb-panel-top': `${Math.max(8, top)}px`,
    '--wb-panel-left': `${Math.max(8, Math.min(r.left, window.innerWidth - 280))}px`,
  }
}

function updateEmpPanelAnchor() {
  if (wbNav.isMobile || !empTriggerRef.value) {
    empPanelAnchorStyle.value = {}
    return
  }
  const r = empTriggerRef.value.getBoundingClientRect()
  empPanelAnchorStyle.value = {
    '--wb-panel-top': `${r.bottom + 8}px`,
    '--wb-panel-left': `${Math.max(8, r.left)}px`,
  }
}

function toggleTierPanel() {
  const next = !tierPanelOpen.value
  tierPanelOpen.value = next
  if (next) {
    empPanelOpen.value = false
    nextTick(() => updateTierPanelAnchor())
  }
}

function toggleDirectWebSearch() {
  directWebSearchEnabled.value = !directWebSearchEnabled.value
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

function toggleDirectImageGen() {
  const next = !directImageGenEnabled.value
  directImageGenEnabled.value = next
  if (next) {
    directVideoGenEnabled.value = false
    showMediaGen.value = false
  }
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

function toggleDirectVideoGen() {
  const next = !directVideoGenEnabled.value
  directVideoGenEnabled.value = next
  if (next) {
    directImageGenEnabled.value = false
    showMediaGen.value = false
  }
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

type DirectWebSearchResult = {
  contextPack: string
  citations: Array<{ title: string; url?: string }>
  note: string
}

async function retrieveWebForDirect(userText: string): Promise<DirectWebSearchResult> {
  const query = String(userText || '').trim()
  if (query.length < 2) {
    return { contextPack: '', citations: [], note: '检索词过短，已跳过联网搜索。' }
  }
  try {
    const res = (await withRequestTimeout(
      api.workbenchWebSearch({ query, max_results: 8, max_chars: 8000 }),
      DIRECT_WEB_SEARCH_MS,
    )) as {
      ok?: boolean
      context_pack?: string
      sources?: Array<{ title?: string; url?: string }>
      warnings?: string[]
      via?: string
      web_error?: string
      error?: string
    }
    const pack = String(res?.context_pack || '').trim()
    const citations = (Array.isArray(res?.sources) ? res.sources : [])
      .map((s, i) => ({
        title: String(s?.title || s?.url || `来源 ${i + 1}`),
        url: String(s?.url || '').trim() || undefined,
      }))
      .filter((c) => c.title)
    const warn = Array.isArray(res?.warnings) ? res.warnings.filter(Boolean).join('；') : ''
    if (!res?.ok || !pack) {
      const err = String(res?.web_error || res?.error || '未检索到可用网页').trim()
      return { contextPack: '', citations, note: warn || err || '联网检索无结果' }
    }
    return {
      contextPack: pack,
      citations,
      note: warn || (res.via ? `已通过 ${res.via} 检索网页` : '已注入联网检索摘要'),
    }
  } catch (e: unknown) {
    const msg = formatDirectChatError(e)
    return {
      contextPack: '',
      citations: [],
      note: msg.includes('429') || msg.includes('频繁') ? '联网检索过于频繁，请稍后再试' : msg,
    }
  }
}

function toggleEmpPanel() {
  const next = !empPanelOpen.value
  empPanelOpen.value = next
  if (next) {
    tierPanelOpen.value = false
    nextTick(() => updateEmpPanelAnchor())
  }
}

function applyStarterPrompt(prompt: string, opts?: { requiresAttachment?: boolean; label?: string }) {
  directDraft.value = prompt
  const needsAttach =
    opts?.requiresAttachment === true ||
    (opts?.label ? starterRequiresAttachment(opts.label) : false)
  const hasOfficeAttach = directAttachedFiles.value.some(
    (f) => f.purpose === 'employee' && f.status === 'ready',
  )
  if (needsAttach && !hasOfficeAttach) {
    directError.value = '请先点击「添加附件」上传文档或表格，再发送。平台将用办公读取员工真实解析，不会凭空编造文件内容。'
    nextTick(() => {
      openDirectFilePicker()
      inputRef.value?.focus()
    })
    return
  }
  directError.value = ''
  nextTick(() => inputRef.value?.focus())
}

function pickHomeConversation(id: string) {
  setActiveConversation(id)
  wbSidebar.closeMobile()
  nextTick(() => inputRef.value?.focus())
}

function formatHomeConvTime(t: number | undefined) {
  return convTimeFormat(t)
}

function onScenePanelOutside(e: MouseEvent) {
  const el = e.target as HTMLElement | null
  if (!el?.closest) return
  if (el.closest('.wb-scene-panel') || el.closest('.wb-scene-toolbar-btn')) return
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

function onScenePanelKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

function onScenePanelReposition() {
  if (tierPanelOpen.value) updateTierPanelAnchor()
  if (empPanelOpen.value) updateEmpPanelAnchor()
}
const titleEnterDone = ref(false)
const composerPanelEnter = ref(true)
const contentEnter = ref(true)
const directBoxEnter = ref(true)

function useTypewriter(source: Ref<string> | ComputedRef<string>, speed = 55, resetTrigger?: ComputedRef<unknown>) {
  const displayed = ref('')
  const isTyping = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  function typeChar(text: string, pos: number) {
    if (pos <= text.length) {
      displayed.value = text.slice(0, pos)
      isTyping.value = pos < text.length
      timer = setTimeout(typeChar, speed, text, pos + 1)
    } else {
      isTyping.value = false
    }
  }
  function startTyping(text: string) {
    if (timer) clearTimeout(timer)
    if (!text) { displayed.value = ''; isTyping.value = false; return }
    displayed.value = ''
    timer = setTimeout(typeChar, 120, text, 0)
  }
  watch(source, v => startTyping(v), { immediate: true })
  if (resetTrigger) watch(resetTrigger, () => startTyping(source.value))
  onUnmounted(() => { if (timer) clearTimeout(timer) })
  return { displayed, isTyping }
}
const directAttachExpanded = ref(false)
const convPopoverOpen = ref(false)

watch(consumptionTier, (v) => {
  try {
    sessionStorage.setItem(CONSUMPTION_TIER_STORAGE_KEY, String(v))
  } catch {
    /* ignore */
  }
})
const voiceMessages = ref([])
const voiceSessionState = ref(createDefaultVoiceSessionState('employee'))
const voiceError = ref('')
const voiceMicFallbackHint = ref('')
const voiceState = ref('idle')
const voiceReport = ref('')
const waveformCanvas = ref<HTMLCanvasElement | null>(null)

const voiceWorkbench = createVoiceWorkbenchState()
const {
  voiceChatPhase,
  voiceWorkPhase,
  voiceChatBusy,
  voiceInjectQueue,
  syncWorkPhase,
  pushInject,
  clearInjectQueue,
} = voiceWorkbench
let voiceStreamHandle: StreamHandle | null = null
let voiceUtteranceQueue: string[] = []
let voiceUtteranceDraining = false

const VOICE_TTS_FEED_OPTS = {
  minLen: 8,
  earlyClause: true,
  earlyClauseMinLen: 10,
  browserLeadIn: true,
}
const voiceAutoSend = computed(() => wbSidebar.activeMode === 'voice')

// voiceDraft / voiceListening 等由 useVoiceContinuousChat 在 inlineAsr 之后初始化
let voiceDraft: ReturnType<typeof useVoiceContinuousChat>['voiceDraft']
let voiceTranscript: ReturnType<typeof useVoiceContinuousChat>['voiceTranscript']
let voiceLivePreview: ReturnType<typeof useVoiceContinuousChat>['voiceLivePreview']
let voiceListening: ReturnType<typeof useVoiceContinuousChat>['voiceListening']
let voiceAudioLevel: ReturnType<typeof useVoiceContinuousChat>['voiceAudioLevel']
let voiceMicPausedByUser: ReturnType<typeof useVoiceContinuousChat>['micPausedByUser']
let voiceSpeculating: ReturnType<typeof useVoiceContinuousChat>['isSpeculating']
let voiceChat: ReturnType<typeof useVoiceContinuousChat>

// 声波可视化绘制
const WAVE_BAR_COUNT = 40
const waveBarHeights = new Float32Array(WAVE_BAR_COUNT).fill(2)
let waveRafId = 0

function voiceMicLevelRaw(): number {
  return Math.max(voiceAudioLevel.value, inlineAsr.audioLevel.value)
}

function drawWaveform() {
  const canvas = waveformCanvas.value
  if (!canvas) {
    waveRafId = requestAnimationFrame(drawWaveform)
    return
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    waveRafId = requestAnimationFrame(drawWaveform)
    return
  }
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  const levelRaw = voiceMicLevelRaw()
  const asrLive = voiceListening.value && inlineAsr.sessionReady.value
  const visBoost = Math.min(1, Math.pow(Math.max(levelRaw, 0.0005), 0.5) * 1.65)
  let level: number
  if (asrLive && levelRaw >= 0.004) {
    level = visBoost
  } else if (asrLive) {
    // 已连接但电平弱：可见呼吸动画 + 微量真实电平
    level = Math.max(visBoost, 0.05 + 0.04 * (0.5 + 0.5 * Math.sin(Date.now() / 480)))
  } else if (levelRaw >= 0.004) {
    level = visBoost
  } else {
    level = 0.04 + 0.035 * (0.5 + 0.5 * Math.sin(Date.now() / 900))
  }
  const weakMic = asrLive && levelRaw < 0.004
  const barW = Math.max(2, (w / WAVE_BAR_COUNT) - 2)
  const gap = 2
  const maxH = h - 2

  for (let i = 0; i < WAVE_BAR_COUNT; i++) {
    // 中间高两边低的包络
    const center = WAVE_BAR_COUNT / 2
    const dist = Math.abs(i - center) / center
    const envelope = 1 - dist * dist
    // 目标高度
    const target = 2 + level * envelope * maxH * (0.6 + 0.4 * Math.sin(Date.now() / 150 + i * 0.7))
    // 平滑过渡
    waveBarHeights[i] += (target - waveBarHeights[i]) * 0.3
    const bh = Math.max(2, waveBarHeights[i])
    const x = i * (barW + gap) + gap
    const y = (h - bh) / 2
    const alpha = weakMic ? 0.22 + level * 0.35 * envelope : 0.3 + level * 0.5 * envelope
    ctx.fillStyle = weakMic
      ? `rgba(251,191,36,${alpha})`
      : `rgba(129,140,248,${alpha})`
    ctx.beginPath()
    ctx.roundRect(x, y, barW, bh, 1.5)
    ctx.fill()
  }

  waveRafId = requestAnimationFrame(drawWaveform)
}

let directWaveRafId = 0
const directWaveBarHeights = new Float32Array(WAVE_BAR_COUNT).fill(2)

function drawDirectWaveform() {
  const canvas = directWaveformCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, w, h)
  const level = directVoiceAudioLevel.value < 0.03 ? 0 : directVoiceAudioLevel.value
  const barW = Math.max(2, (w / WAVE_BAR_COUNT) - 2)
  const gap = 2
  const maxH = h - 2
  for (let i = 0; i < WAVE_BAR_COUNT; i++) {
    const center = WAVE_BAR_COUNT / 2
    const dist = Math.abs(i - center) / center
    const envelope = 1 - dist * dist
    const target = 2 + level * envelope * maxH * (0.6 + 0.4 * Math.sin(Date.now() / 150 + i * 0.7))
    directWaveBarHeights[i] += (target - directWaveBarHeights[i]) * 0.3
    const bh = Math.max(2, directWaveBarHeights[i])
    const x = i * (barW + gap) + gap
    const y = (h - bh) / 2
    const alpha = 0.3 + level * 0.5 * envelope
    ctx.fillStyle = `rgba(129,140,248,${alpha})`
    ctx.beginPath()
    ctx.roundRect(x, y, barW, bh, 1.5)
    ctx.fill()
  }
  directWaveRafId = requestAnimationFrame(drawDirectWaveform)
}

watch(directVoiceListening, (v) => {
  if (v && wbNav.isMobile) {
    directWaveBarHeights.fill(2)
    nextTick(() => { directWaveRafId = requestAnimationFrame(drawDirectWaveform) })
  } else {
    cancelAnimationFrame(directWaveRafId)
    directVoiceAudioLevel.value = 0
  }
})
const voiceProgress = computed(() => {
  const steps = Array.isArray(orchestrationSession.value?.steps) ? orchestrationSession.value.steps : []
  if (!steps.length) return 0
  const done = steps.filter((s: { status?: string }) => s.status === 'done').length
  const running = steps.some((s: { status?: string }) => s.status === 'running') ? 0.45 : 0
  return Math.min(100, Math.round(((done + running) / steps.length) * 100))
})

const inlineAsr = useSpeechRecognition()

const directVoicePhase = computed(() =>
  resolveInlineVoicePhase(
    directVoiceListening.value,
    directVoiceRecognizing.value,
    directVoicePermissionHint.value,
  ),
)
const makeVoicePhase = computed(() =>
  resolveInlineVoicePhase(
    makeVoiceListening.value,
    makeVoiceRecognizing.value,
    makeVoicePermissionHint.value,
  ),
)
const directVoiceBtnClass = computed(() => ({
  'wb-direct-voice-btn--recording': directVoicePhase.value === 'recording',
  'wb-direct-voice-btn--recognizing': directVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--permission': directVoicePhase.value === 'permission',
  'wb-direct-voice-btn--on':
    directVoicePhase.value === 'recording' || directVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--ptt': wbNav.isMobile,
}))
const makeVoiceBtnClass = computed(() => ({
  'wb-direct-voice-btn--recording': makeVoicePhase.value === 'recording',
  'wb-direct-voice-btn--recognizing': makeVoicePhase.value === 'recognizing',
  'wb-direct-voice-btn--permission': makeVoicePhase.value === 'permission',
  'wb-direct-voice-btn--on':
    makeVoicePhase.value === 'recording' || makeVoicePhase.value === 'recognizing',
}))
const directVoiceAria = computed(() =>
  inlineVoiceAriaLabel(directVoicePhase.value, wbNav.isMobile, inlineHoldCancelIntent),
)
const makeVoiceAria = computed(() => inlineVoiceAriaLabel(makeVoicePhase.value, false, false))
const directVoiceStatusText = computed(() =>
  inlineVoiceStatusLabel(
    directVoicePhase.value,
    wbNav.isMobile,
    inlineHoldCancelIntent,
    directVoicePermissionHint.value,
    inlineAsr.loadingHint.value,
  ),
)
const makeVoiceStatusText = computed(() =>
  inlineVoiceStatusLabel(
    makeVoicePhase.value,
    false,
    false,
    makeVoicePermissionHint.value,
    inlineAsr.loadingHint.value,
  ),
)
const directVoiceCanCancel = computed(
  () => directVoicePhase.value === 'recording' || directVoicePhase.value === 'recognizing',
)
const makeVoiceCanCancel = computed(
  () => makeVoicePhase.value === 'recording' || makeVoicePhase.value === 'recognizing',
)

/** 统一语音模式下走单 WS，否则走 FunASR 链 */
const voiceAsrAdapter = {
  get error() {
    return voiceUseUnified.value ? voiceUnified.lastError : inlineAsr.error
  },
  get interimText() {
    return voiceUseUnified.value ? voiceLivePreview : inlineAsr.interimText
  },
  get audioLevel() {
    return voiceUseUnified.value ? voiceUnified.audioLevel : inlineAsr.audioLevel
  },
  get loadingHint() {
    return voiceUseUnified.value ? voiceUnified.loadingHint : inlineAsr.loadingHint
  },
  get activeBackendId() {
    return voiceUseUnified.value ? voiceUnified.activeBackendId : inlineAsr.activeBackendId
  },
  get sessionReady() {
    return voiceUseUnified.value ? voiceUnified.sessionReady : inlineAsr.sessionReady
  },
  startListening: (
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onLevel?: (level: number) => void,
    onReady?: () => void,
    onMic?: () => void,
    stream?: MediaStream,
    opts?: { continuous?: boolean },
  ) =>
    voiceUseUnified.value
      ? unifiedAsrBridge.startListening(onResult, onError, onLevel, onReady, onMic, stream, opts)
      : inlineAsr.startListening(onResult, onError, onLevel, onReady, onMic, stream, opts),
  flushListening: () =>
    voiceUseUnified.value ? unifiedAsrBridge.flushListening() : inlineAsr.flushListening(),
  signalEndOfSpeech: () => {
    if (voiceUseUnified.value) unifiedAsrBridge.signalEndOfSpeech()
    else inlineAsr.signalEndOfSpeech()
  },
  stopListening: () =>
    voiceUseUnified.value ? unifiedAsrBridge.stopListening() : inlineAsr.stopListening(),
  abort: (opts?: { keepMic?: boolean }) =>
    voiceUseUnified.value ? unifiedAsrBridge.abort(opts) : inlineAsr.abort(opts),
}
const voiceAsrActiveId = computed(() => voiceAsrAdapter.activeBackendId.value)
const voiceAsrBackendLabel = computed(() => {
  if (!inlineAsr.sessionReady.value) return ''
  const id = voiceAsrActiveId.value
  if (id === 'funasr') return '服务端'
  if (id === 'whisper-web') return '本地模型'
  if (id === 'webspeech') return '浏览器'
  return ''
})

function canSpeculateForPartial(partialText: string): boolean {
  if (voiceUseUnified.value || voiceUseS2S.value) return false
  if (personalSettings.value.voiceSpeechMode !== 'cascade') return false
  const t = partialText.trim()
  if (t.length < 12) return false
  if (isVoiceSpeculativeFiller(t)) return false
  return true
}

function appendVoiceUserTurn(text: string) {
  const trimmed = sanitizeVoiceUtteranceText(text)
  if (!trimmed) return
  voiceMessages.value = appendCoalescedVoiceUserTurn(voiceMessages.value, trimmed)
}

function phoneTurnTextDelta(assistantIdx: number) {
  return (_d: string, soFar: string) => {
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
    voiceMessages.value = msgs
    voiceReport.value = soFar
  }
}

async function handlePhonePartialStable(text: string, turnId: string) {
  if (!voiceUsePhonePipeline.value || voiceChatBusy.value) return
  clearVoiceLatencyMarks()
  s2sProvisionalTurnId = turnId
  s2sProvisionalStarted = true
  voiceChatBusy.value = true
  voiceChatPhase.value = 'streaming'
  voiceState.value = 'processing'
  appendVoiceUserTurn(text)
  s2sProvisionalAssistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt()
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  const turnOpts = {
    text,
    turnId,
    system: sys,
    messages: history,
    provider,
    model,
    voice: ttsCfg.edgeVoice,
    rate: ttsCfg.rate,
    ttsEnabled: ttsAutoRead.value,
    maxTokens: 1024,
    onTextDelta: phoneTurnTextDelta(s2sProvisionalAssistantIdx),
  }
  try {
    if (voiceUseUnified.value) {
      await voiceUnified.runTurnStart(turnOpts)
    } else {
      await voiceS2s.runTurnStart({ ...turnOpts, provisional: true })
    }
  } catch (e: unknown) {
    s2sProvisionalStarted = false
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceError.value = e instanceof Error ? e.message : String(e)
  }
}

function handlePhoneUtteranceFinalize(text: string, turnId: string) {
  if (!voiceUsePhonePipeline.value) return
  if (voiceUseUnified.value) {
    voiceUnified.sendUtteranceFinalize(text, turnId)
  } else {
    voiceS2s.sendUtteranceFinalize(text, turnId)
  }
  if (s2sProvisionalStarted && !textsSimilarForFinalize(text, voiceMessages.value.filter((m) => m.role === 'user').pop()?.content || '')) {
    if (voiceUseUnified.value) voiceUnified.cancelTurn()
    else voiceS2s.cancelTurn()
    s2sProvisionalStarted = false
    if (voiceUseUnified.value) void runVoiceUnifiedTurn(text, undefined, { skipUserAppend: true, turnId })
    else void runVoiceS2STurn(text, undefined, { skipUserAppend: true, turnId })
  }
}

async function handleVoiceUtteranceReady(
  text: string,
  ctx: { speculativePartial: string | null },
) {
  if (voiceUsePhonePipeline.value && s2sProvisionalStarted && s2sProvisionalTurnId) {
    const msgs = [...voiceMessages.value]
    const lastUser = msgs.filter((m) => m.role === 'user').pop()
    if (lastUser && lastUser.content !== text) {
      lastUser.content = text
      voiceMessages.value = msgs
    }
    handlePhoneUtteranceFinalize(text, s2sProvisionalTurnId)
    return
  }
  if (ctx.speculativePartial && voiceChatBusy.value && voiceStreamHandle) {
    const msgs = [...voiceMessages.value]
    const lastUser = msgs.filter((m) => m.role === 'user').pop()
    if (!lastUser || lastUser.content !== text) {
      appendVoiceUserTurn(text)
    }
    voiceChat.noteSubmitted(text)
    try {
      await voiceStreamHandle.done
    } catch {
      /* aborted */
    }
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceStreamHandle = null
    if (composerIntent.value === 'employee') {
      if (await tryOpenEmployeePlanFromExplicitCommand(text, { userAlreadyInThread: true })) {
        return
      }
      const classification = await resolveEmployeeClassification(text)
      applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
      if (classification.action !== 'chat' && classification.action !== 'clarify') {
        await dispatchEmployeeVoiceUtterance(text, {
          userAlreadyInThread: true,
          skipReclassify: true,
          prefetchedClassification: classification,
        })
      }
      return
    }
    void applyEmployeeSessionClassify(text)
    return
  }
  await dispatchVoiceUtterance(text, { alreadySubmitted: true })
}

function cancelSpeculativeVoiceTurn() {
  voiceStreamHandle?.abort()
  voiceStreamHandle = null
  if (voiceChatBusy.value) {
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceState.value = 'idle'
    const msgs = [...voiceMessages.value]
    const last = msgs[msgs.length - 1]
    if (last?.role === 'assistant' && !last.content) {
      msgs.pop()
      voiceMessages.value = msgs
    }
    voiceReport.value = ''
    streamingTts.stop()
  }
}

function startSpeculativeVoiceTurn(partialText: string) {
  if (voiceChatBusy.value) return
  streamingTts.warmUp()
  void runVoiceChatTurn(partialText, undefined, { skipUserAppend: true, speculative: true })
}

function triggerVoiceBargeIn() {
  if (!voiceAutoSend.value) return
  executeVoiceBargeIn({
    stopS2s: () => {
      voiceS2s.cancelTurn()
      voiceUnified.cancelTurn()
      s2sProvisionalStarted = false
    },
    stopCascadeTts: () => streamingTts.stop(),
    abortLlmStream: () => {
      voiceStreamHandle?.abort()
      voiceStreamHandle = null
    },
    setIdle: () => {
      voiceChatBusy.value = false
      voiceChatPhase.value = 'idle'
      voiceState.value = 'idle'
    },
  })
}

voiceChat = useVoiceContinuousChat({
  asr: voiceAsrAdapter as ReturnType<typeof useSpeechRecognition>,
  isAsrReady: () => voiceAsrAdapter.sessionReady.value,
  getAsrBackendId: () =>
    voiceUseUnified.value ? 'funasr' : voiceAsrAdapter.activeBackendId.value,
  signalAsrEndOfSpeech: () => voiceAsrAdapter.signalEndOfSpeech(),
  voiceUsePhonePipeline: () => voiceUsePhonePipeline.value,
  voiceUseS2S: () => voiceUseS2S.value,
  usePhoneLatency: () => voiceUsePhonePipeline.value,
  onS2SPartialStable: handlePhonePartialStable,
  onS2SUtteranceFinalize: handlePhoneUtteranceFinalize,
  autoSend: voiceAutoSend,
  voiceState,
  voiceChatPhase,
  isVoiceTargetActive: () => inlineVoiceTarget === 'voice',
  setVoiceTarget: () => { inlineVoiceTarget = 'voice' },
  clearVoiceTarget: () => { inlineVoiceTarget = null },
  beforeStartListening: () => {
    if (directVoiceListening.value) void stopInlineVoice('direct')
    if (makeVoiceListening.value) void stopInlineVoice('make')
    if (inlineVoiceTarget && inlineVoiceTarget !== 'voice') {
      inlineAsr.abort()
      stopInlineVoiceCapture()
    }
  },
  onUtteranceReady: handleVoiceUtteranceReady,
  onSpeculativeStart: startSpeculativeVoiceTurn,
  onSpeculativeCancel: cancelSpeculativeVoiceTurn,
  onBargeIn: () => triggerVoiceBargeIn(),
  onAsrDuringTts: (level: number) => {
    if (!voiceAutoSend.value) return false
    const ep = voiceUseUnified.value ? { speechLevel: 0.012 } : { speechLevel: 0.012 }
    const ttsOn = voiceUseUnified.value
      ? voiceUnified.isPlaying()
      : voiceUseS2S.value
        ? voiceS2s.isPlaying()
        : streamingTts.state.value !== 'idle'
    if (!ttsOn) return false
    if (shouldTriggerVoiceBargeIn(level, ep.speechLevel, true)) {
      triggerVoiceBargeIn()
      return true
    }
    return false
  },
  isTtsPlaying: () =>
    voiceUseUnified.value
      ? voiceUnified.isPlaying()
      : voiceUseS2S.value
        ? voiceS2s.isPlaying()
        : streamingTts.state.value !== 'idle',
  canSpeculate: canSpeculateForPartial,
  isChatBusy: () => voiceChatBusy.value,
})

voiceDraft = voiceChat.voiceDraft
voiceTranscript = voiceChat.voiceTranscript
voiceLivePreview = voiceChat.voiceLivePreview
voiceListening = voiceChat.voiceListening
voiceAudioLevel = voiceChat.voiceAudioLevel
voiceMicPausedByUser = voiceChat.micPausedByUser
voiceSpeculating = voiceChat.isSpeculating

/** let 赋值的 ref 在模板中不会自动解包，需 computed 桥接 VoiceDock v-model */
const voiceDockDraft = computed({
  get: () => voiceDraft.value,
  set: (v: string) => { voiceDraft.value = v },
})

/** 波形区：聆听中或 ASR 重连/切换方案时保持可见，避免 v-if 闪灭 */
const voiceAssistantSpeaking = computed(
  () =>
    voiceUseUnified.value
      ? voiceUnified.isPlaying() || voiceUnified.state.value === 'speaking' || voiceUnified.state.value === 'streaming'
      : voiceUseS2S.value
        ? voiceS2s.isPlaying() || voiceS2s.state.value === 'streaming' || voiceS2s.state.value === 'speaking'
        : streamingTts.state.value !== 'idle',
)

const showVoiceWaveform = computed(() => {
  if (voiceMicPausedByUser.value) return false
  if (wbSidebar.activeMode !== 'voice') return false
  return (
    (voiceListening.value && voiceAsrAdapter.sessionReady.value)
    || Boolean(voiceAsrAdapter.loadingHint.value)
    || voiceState.value === 'listening'
    || voiceAssistantSpeaking.value
  )
})

const voiceAsrConnecting = computed(
  () =>
    Boolean(voiceAsrAdapter.loadingHint.value) &&
    !voiceAsrAdapter.sessionReady.value &&
    !voiceMicPausedByUser.value,
)
const voiceAsrListening = computed(
  () => voiceListening.value && voiceAsrAdapter.sessionReady.value && !voiceMicPausedByUser.value,
)
/** 说模式：用户停顿后 ASR 收尾或 LLM 处理前 */
const voiceDockRecognizing = computed(
  () =>
    !voiceMicPausedByUser.value &&
    voiceListening.value &&
    (voiceState.value === 'processing' ||
      Boolean(
        (voiceTranscript.value || voiceLivePreview.value || voiceAsrAdapter.interimText.value) &&
          !voiceAsrConnecting.value,
      )),
)

watch(showVoiceWaveform, (v) => {
  if (v) {
    waveBarHeights.fill(2)
    nextTick(() => {
      cancelAnimationFrame(waveRafId)
      waveRafId = requestAnimationFrame(drawWaveform)
    })
  } else {
    cancelAnimationFrame(waveRafId)
    waveRafId = 0
  }
})

watch(waveformCanvas, (el) => {
  if (el && showVoiceWaveform.value) {
    cancelAnimationFrame(waveRafId)
    waveBarHeights.fill(2)
    waveRafId = requestAnimationFrame(drawWaveform)
  }
})

const voiceHasAssistantContent = computed(() =>
  voiceMessages.value.some((m) => m.role === 'assistant' && String(m.content || '').trim()),
)

async function onVoiceDockSend() {
  const text = String(voiceDraft.value || voiceDockDraft.value || '').trim()
  if (!text) return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (
    voiceChatBusy.value ||
    streamingTts.state.value !== 'idle' ||
    voiceStreamHandle
  ) {
    cancelSpeculativeVoiceTurn()
    streamingTts.stop()
    voiceStreamHandle?.abort()
    voiceStreamHandle = null
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceState.value = 'idle'
  }
  voiceDraft.value = ''
  voiceDockDraft.value = ''
  await dispatchVoiceUtterance(text, { fromTypedComposer: true })
}

function onVoiceMicToggle() {
  if (voiceMicPausedByUser.value) {
    requestMicInUserGesture()
    void unlockVoiceAudioPlayback()
    voiceError.value = ''
    voiceMicFallbackHint.value = ''
    resumeVoiceMic()
    return
  }
  void forcePauseVoiceSession()
}

function resumeVoiceMic() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceMicPausedByUser.value = false
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  void startVoiceRecognition({ fresh: true })
}

async function forcePauseVoiceSession() {
  voiceChat.clearContinuousSilenceTimer()
  voiceChat.stopSilenceWatchdog()
  cancelSpeculativeVoiceTurn()
  voiceStreamHandle?.abort()
  voiceStreamHandle = null
  streamingTts.stop()
  voiceChatBusy.value = false
  voiceChatPhase.value = 'idle'

  let text = voiceTranscript.value.trim() || voiceDraft.value.trim()
  if (voiceListening.value || inlineVoiceTarget === 'voice') {
    try {
      const stopped = (await stopVoiceAsr()).trim()
      if (stopped) text = stopped
    } catch {
      /* ignore */
    }
  }

  voiceListening.value = false
  voiceAudioLevel.value = 0
  voiceState.value = 'idle'
  voiceReport.value = ''
  voiceTranscript.value = ''
  voiceMicPausedByUser.value = true

  if (text && voiceChat.hasFreshCapture(text) && voiceAutoSend.value) {
    try {
      await dispatchVoiceUtterance(text)
    } catch {
      voiceDraft.value = text
    }
  } else if (text) {
    voiceDraft.value = text
  }
}

function noteVoiceSubmitted(text: string) {
  voiceChat.noteSubmitted(text)
}

function resetVoiceListenSession() {
  voiceChat.resetListenSession()
}

function resetVoiceCaptureUi() {
  voiceChat.resetCaptureUi()
}

async function finishContinuousUtterance() {
  await voiceChat.finishUtterance()
}

async function activateVoiceContinuous(opts?: { submitPending?: boolean }) {
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  if (voiceMicPausedByUser.value) return
  const pending = voiceTranscript.value.trim() || voiceDraft.value.trim()
  if (opts?.submitPending !== false && pending) {
    await finishContinuousUtterance()
    return
  }
  if (!voiceListening.value) {
    void startVoiceRecognition({ fresh: true })
  } else if (pending && voiceChat.hasFreshCapture(pending)) {
    voiceChat.clearContinuousSilenceTimer()
  }
}

/** 语音球模式：听/说/播报期间保持可见动画，勿误降级为 idle */
const voiceOrbMode = computed(() => {
  if (voiceError.value) return 'idle'
  if (voiceListening.value || voiceState.value === 'listening') return 'listening'
  if (voiceAssistantSpeaking.value && wbSidebar.activeMode === 'voice') return 'reporting'
  if (voiceState.value === 'processing' || voiceState.value === 'reporting') return voiceState.value
  return voiceState.value
})

const voiceOrbHint = computed(() => {
  if (voiceAssistantSpeaking.value && wbSidebar.activeMode === 'voice') return '点击打断播报'
  if (voiceListening.value || voiceState.value === 'listening') return '正在听，可直接说话'
  if (voiceWorkPhase.value === 'orchestrating') return '制作中，可直接说话补充'
  if (voiceChatPhase.value === 'streaming') return '思考中，可直接说话打断'
  return ''
})

const voiceOrbActive = computed(
  () =>
    voiceListening.value ||
    voiceState.value === 'listening' ||
    voiceState.value === 'processing' ||
    voiceState.value === 'reporting' ||
    voiceAssistantSpeaking.value ||
    voiceWorkPhase.value === 'orchestrating',
)

const voiceTitle = computed(() => {
  if (composerIntent.value === 'employee') {
    const ps = planSession.value
    if (ps) {
      if (ps.phase === 'summary') {
        return ps.summaryNeedsClarification ? '还需补充信息' : '摘要确认'
      }
      if (ps.phase === 'chat') return '需求澄清'
      if (ps.phase === 'checklist') return '执行清单'
      if (ps.phase === 'done') return '规划完成'
    }
    const stage = voiceSessionState.value.stage
    if (stage === 'clarifying') return '正在理解需求'
    if (stage === 'ready_to_plan') return '可以开始规划'
    if (stage === 'executing') return '制作中'
  }
  if (voiceState.value === 'listening') return '我在听'
  if (voiceState.value === 'processing') return '正在处理'
  if (voiceState.value === 'reporting') return '汇报中'
  return '说出你想制作的东西'
})

const voiceStatusText = computed(() => {
  if (voiceWorkPhase.value === 'orchestrating') return '正在制作，你可以随时说话补充或问进度。'
  if (voiceWorkPhase.value === 'planning') return '需求规划中，直接说话参与澄清。'
  if (voiceWorkPhase.value === 'handoff') return '草稿已就绪，说「开始生成」或点下方按钮。'
  if (voiceState.value === 'listening') return '直接说需求，停顿后自动发送。'
  if (voiceChatPhase.value === 'streaming') return '正在思考，你可以随时说话打断。'
  if (voiceState.value === 'reporting' || streamingTts.state.value !== 'idle') return 'AI 回复中，说完后会继续聆听…'
  if (
    wbNav.isMobile &&
    wbSidebar.activeMode === 'voice' &&
    !voiceListening.value &&
    !voiceMicPausedByUser.value
  ) {
    return '点右下角 ▶ 开始说，也可以直接打字。'
  }
  if (wbNav.isMobile && voiceMicPausedByUser.value) {
    return '麦克风暂停着，想继续说就点 ▶；也可以先打字。'
  }
  return '点一下语音球或直接打字，我们先把话聊顺。'
})

function isGearAxisLocked() {
  const hasInput =
    Boolean(String(draft.value || '').trim()) ||
    Boolean(String(directDraft.value || '').trim()) ||
    Boolean(String(voiceDraft.value || '').trim()) ||
    Boolean(String(planReplyDraft.value || '').trim()) ||
    directAttachedFiles.value.length > 0
  const hasTask =
    Boolean(planSession.value) ||
    Boolean(pendingHandoff.value) ||
    Boolean(finalizeLoading.value) ||
    Boolean(linkBusy.value) ||
    Boolean(orchestrationSession.value?.steps?.length)
  return hasInput || hasTask
}

function directFileChipTitle(f) {
  if (!f) return ''
  const emb = formatEmbeddingLabel(f.embedding)
  if (f.status === 'uploading') return `${f.name}：正在读取文件内容…`
  if (f.status === 'ready') return `${f.name}：已纳入资料库，提问时会按相关度自动召回片段${emb ? `；向量模型：${emb}` : ''}`
  if (f.status === 'inline') {
    return f.ingestError
      ? `${f.name}：已读取文本，可直接发送；${f.ingestError}`
      : `${f.name}：已读取文本，将直接注入模型上下文${f.ingesting ? '，资料库入库中' : ''}${emb ? `；向量模型：${emb}` : ''}`
  }
  if (f.status === 'skipped') return `${f.name}：${f.error || '该格式暂不解析；将仅附文件名供模型参考'}`
  if (f.status === 'error') return `${f.name}：${f.error || '上传失败'}（仅附文件名给模型参考）`
  return f.name
}

function formatEmbeddingLabel(embedding) {
  if (!embedding || typeof embedding !== 'object') return ''
  const provider = String(embedding.provider || '').trim()
  const model = String(embedding.model || '').trim()
  const dim = Number(embedding.dim || 0) || 0
  if (!provider && !model) return ''
  return `${provider || '默认'} / ${model || '默认模型'}${dim ? ` · ${dim}维` : ''}`
}

function directAttachmentKind(f) {
  return directFileKind(f?.name || '', f?.file?.type || '')
}

function directAttachmentKindLabel(f) {
  return directFileKindLabel(directAttachmentKind(f))
}

function directAttachmentStatusText(f) {
  if (!f) return ''
  if (f.status === 'uploading') return '读取中'
  if (f.status === 'ready') return f.embedding ? '已入库 · 向量' : '已入库'
  if (f.status === 'inline') {
    if (f.ingesting) return '可发送 · 入库中'
    if (f.ingestError) return '可发送 · 入库失败'
    return '可发送'
  }
  if (f.status === 'skipped') return '未支持'
  return '读取失败'
}

function directAttachmentNote(files) {
  const list = Array.isArray(files) ? files : []
  if (!list.length) return ''
  const parts = list.map((f, idx) => {
    let tag =
      f.status === 'ready'
        ? '已入库'
        : f.status === 'uploading'
          ? '读取中'
          : f.status === 'inline'
            ? '已读取'
            : f.status === 'error'
              ? '上传失败'
              : '未解析'
    if (f.purpose === 'employee' && f.status === 'ready') {
      const emp = String(f.readEmployeeId || resolveReadEmployeeForExtension(directFileExt(f.name)) || '').trim()
      tag = emp ? `读取员工·${readEmployeeDisplayName(emp)}` : '读取员工'
    }
    return `@附件${idx + 1} ${f.name}（${formatDirectFileSize(f.size)}，${tag}）`
  })
  return `[附件顺序：${parts.join('，')}]`
}

function resolveDirectFileEmployeeId(f: { readEmployeeId?: string; name?: string }): string {
  const ext = directFileExt(String(f.name || ''))
  const fromExt = resolveReadEmployeeForExtension(ext)
  if (fromExt) return fromExt
  const fromItem = String(f.readEmployeeId || '').trim()
  if (fromItem && !isGenerateEmployeeId(fromItem) && employeeAcceptsFileExtension(fromItem, ext)) {
    return fromItem
  }
  const picked = String(directChatEmployeeId.value || '').trim()
  if (picked && !isGenerateEmployeeId(picked) && employeeAcceptsFileExtension(picked, ext)) {
    return picked
  }
  return ''
}

function applyDirectReadEmployeePick(readEmployeeId: string) {
  const id = String(readEmployeeId || '').trim()
  if (!id) return
  directChatEmployeeId.value = id
  try {
    sessionStorage.setItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, id)
  } catch {
    /* ignore */
  }
}

function buildDirectAttachItem(file: File) {
  const ext = directFileExt(file.name)
  const readEmp = resolveReadEmployeeForExtension(ext)
  if (readEmp) {
    const tooBig = Number(file.size || 0) > DIRECT_EMPLOYEE_FILE_MAX_BYTES
    if (tooBig) {
      return {
        id: makeDirectAttachId(),
        name: file.name,
        size: file.size || 0,
        status: 'skipped',
        purpose: 'employee',
        readEmployeeId: readEmp,
        docId: '',
        error: `超过员工通道 ${formatDirectFileSize(DIRECT_EMPLOYEE_FILE_MAX_BYTES)} 上限`,
        ingesting: false,
        ingestError: '',
        file,
      }
    }
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'ready',
      purpose: 'employee',
      readEmployeeId: readEmp,
      docId: '',
      error: '',
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  const supported = DIRECT_KB_SUPPORTED_EXT.has(ext)
  const tooBig = Number(file.size || 0) > DIRECT_KB_MAX_BYTES
  if (!supported) {
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'skipped',
      docId: '',
      error: `不支持的格式（知识库：${DIRECT_KB_SUPPORTED_EXTENSIONS.join('/')}；读取员工：Excel/CSV/PDF/Word/PPT）`,
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  if (tooBig) {
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'skipped',
      docId: '',
      error: `超过 ${formatDirectFileSize(DIRECT_KB_MAX_BYTES)} 上限`,
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  return {
    id: makeDirectAttachId(),
    name: file.name,
    size: file.size || 0,
    status: 'uploading',
    purpose: 'knowledge',
    docId: '',
    error: '',
    ingesting: false,
    ingestError: '',
    file,
  }
}

function openDirectFilePicker() {
  if (directLoading.value) return
  directFileInputRef.value?.click?.()
}

function makeDirectAttachId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      /* fallthrough */
    }
  }
  return `att_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function appendAttachmentMentions(files: File[], target: 'direct' | 'make') {
  const names = (Array.isArray(files) ? files : [])
    .map((file) => String(file?.name || '').trim())
    .filter(Boolean)
  if (!names.length) return
  const startIndex = Math.max(0, directAttachedFiles.value.length - names.length)
  const mentions = names.map((name, idx) => `@附件${startIndex + idx + 1} ${name}`).join(' ')
  const r = target === 'make' ? draft : directDraft
  const current = String(r.value || '')
  const joiner = current.trim() ? (/\s$/.test(current) ? '' : ' ') : ''
  r.value = `${current}${joiner}${mentions} `
}

async function uploadDirectAttachedFile(item) {
  let extractedText = ''
  try {
    const extractRes = await api.knowledgeExtractText(item.file)
    const outcome = resolveDirectAttachmentOutcome({ extractedText: extractRes?.text })
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    if (!outcome.canSend) throw new Error(outcome.error)
    extractedText = outcome.extractedText
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'inline',
      extractedText,
      docId: '',
      error: '',
      ingesting: true,
      ingestError: '',
    }
  } catch (e) {
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    const outcome = resolveDirectAttachmentOutcome({ extractError: e })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'error',
      extractedText: '',
      docId: '',
      error: outcome.error,
      ingesting: false,
      ingestError: '',
    }
    return
  }

  try {
    const embeddingChoice = await resolveChatProviderModel()
    const res = await api.knowledgeUploadDocument(item.file, {
      embeddingProvider: embeddingChoice.provider,
      embeddingModel: embeddingChoice.model,
    })
    const docId = res?.document?.doc_id || res?.document?.docId || ''
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) {
      // 已被移除：尝试回收资料库中的副本，避免脏数据
      if (docId) {
        try {
          await api.knowledgeDeleteDocument(docId)
        } catch {
          /* ignore cleanup error */
        }
      }
      return
    }
    const outcome = resolveDirectAttachmentOutcome({ extractedText, docId, uploadError: docId ? undefined : '上传未返回文档 ID' })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: outcome.status,
      docId: outcome.docId,
      extractedText: outcome.extractedText,
      error: outcome.error,
      ingesting: false,
      ingestError: outcome.ingestError,
      embedding: res?.embedding || null,
    }
  } catch (e) {
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    const outcome = resolveDirectAttachmentOutcome({ extractedText, uploadError: e })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: outcome.status,
      docId: '',
      extractedText: outcome.extractedText,
      error: outcome.error,
      ingesting: false,
      ingestError: outcome.ingestError,
    }
  }
}

function onDirectFilesChange(e) {
  const input = e?.target as HTMLInputElement | null
  if (!input || typeof input.files === 'undefined') return
  const picked: File[] = Array.from(input.files || [])
  input.value = ''
  if (!picked.length) return
  const maxFiles = 12
  const remaining = Math.max(0, maxFiles - directAttachedFiles.value.length)
  const accepted = picked.slice(0, remaining)
  const items = accepted.map((file: File) => buildDirectAttachItem(file))
  const firstRead = items.find((it) => it.readEmployeeId)
  if (firstRead?.readEmployeeId) applyDirectReadEmployeePick(firstRead.readEmployeeId)
  directAttachedFiles.value = [...directAttachedFiles.value, ...items]
  appendAttachmentMentions(accepted, 'direct')
  for (const it of items) {
    if (it.status === 'uploading') void uploadDirectAttachedFile(it)
  }
}

function userFacingOutputDownloads(
  downloads: Array<{ jobId: string; filename: string; label?: string }>,
) {
  return filterUserFacingOfficeDownloads(downloads)
}

function pushDirectGeneratedDownloads(
  downloads: Array<{ jobId: string; filename: string; label?: string }> | unknown,
) {
  const parsed = Array.isArray(downloads)
    ? parseEmployeeOutputDownloads({ output_downloads: downloads })
    : parseEmployeeOutputDownloads(downloads)
  if (!parsed.length) return
  const facing = filterUserFacingOfficeDownloads(parsed)
  const incoming = employeeDownloadsToGeneratedFiles(facing)
  if (!incoming.length) return
  directGeneratedFiles.value = mergeGeneratedFiles(directGeneratedFiles.value, incoming)
  butlerDownloadHistory.recordDownloads(facing, {
    employeeId: directChatEmployeeId.value || undefined,
  })
}

function cacheOfficeReadResults(
  conversationId: string,
  rawResults: Array<{ name: string; employeeId: string; result: unknown }>,
) {
  const id = String(conversationId || '').trim()
  if (!id || !rawResults?.length) return
  officeReadCacheByConversation.set(id, rawResults)
}

function getCachedOfficeReadResults(conversationId: string) {
  return officeReadCacheByConversation.get(String(conversationId || '').trim()) || []
}

function beginDirectGenerating(format: OfficeFormat, label = '生成中…') {
  directGeneratingFile.value = { active: true, format, label }
}

function clearDirectGenerating() {
  directGeneratingFile.value = null
}

async function runDirectOfficeGeneratePhase(
  opts: Parameters<typeof runOfficeGeneratePhase>[0],
) {
  beginDirectGenerating(opts.format)
  try {
    return await runOfficeGeneratePhase(opts)
  } finally {
    clearDirectGenerating()
  }
}

function removeDirectGeneratedFile(id: string) {
  directGeneratedFiles.value = directGeneratedFiles.value.filter((f) => f.id !== id)
}

async function downloadGeneratedOutput(f: DirectGeneratedFile) {
  await downloadOutput(f.jobId, f.filename, f.name)
}

async function removeDirectAttachedFile(id) {
  const item = directAttachedFiles.value.find((f) => f.id === id)
  if (!item) return
  if (item.status === 'uploading') return
  directAttachedFiles.value = directAttachedFiles.value.filter((f) => f.id !== id)
  if (item.docId) {
    try {
      await api.knowledgeDeleteDocument(item.docId)
    } catch {
      /* 移除知识库中的副本失败不影响 UI */
    }
  }
}

let syncingConvToSidebar = false

function persistConversations() {
  const list = conversations.value.slice()
  saveConversations(list)
  syncingConvToSidebar = true
  wbSidebar.setConversations(list)
  syncingConvToSidebar = false
}

function ensureActiveConversation(opts?: { forceNew?: boolean; bot?: AgentBot | null }): Conversation {
  if (!opts?.forceNew && activeConversation.value) return activeConversation.value
  const bot = opts?.bot ?? activeBot.value
  const conv = createConversation({
    title: '新对话',
    agentId: bot?.id,
    agentLabel: bot?.name,
  })
  if (bot?.opener) {
    conv.messages.push(makeMessage('assistant', bot.opener))
  }
  conversations.value = [conv, ...conversations.value]
  activeConversationId.value = conv.id
  saveActiveId(conv.id)
  wbSidebar.setActiveConversationId(conv.id)
  persistConversations()
  return conv
}

function patchActiveConversation(mutator: (c: Conversation) => void, conversationId?: string) {
  const id = conversationId || activeConversationId.value
  if (!id) return
  conversations.value = conversations.value.map((c) => {
    if (c.id !== id) return c
    const next: Conversation = { ...c, messages: c.messages.slice() }
    mutator(next)
    next.updatedAt = Date.now()
    return next
  })
  persistConversations()
}

function appendUserAndAssistant(userMsg: ChatMessage, assistantPlaceholder: ChatMessage) {
  const convId = activeConversationId.value
  if (!convId) return
  patchActiveConversation((c) => {
    c.messages.push(userMsg)
    c.messages.push(assistantPlaceholder)
    if (!c.title || c.title === '新对话') {
      c.title = buildConversationTitle(userMsg.content)
    }
  }, convId)
}

function updateAssistantMessage(id: string, mutator: (m: ChatMessage) => void) {
  patchActiveConversation((c) => {
    const idx = c.messages.findIndex((m) => m.id === id)
    if (idx < 0) return
    const next = { ...c.messages[idx] }
    mutator(next)
    c.messages[idx] = next
  })
}

function buildHumanChatStylePrompt(channel: 'text' | 'voice'): string {
  const parts = [
    '【自然对话风格】像一个有分寸、会接话的中文同事在聊天，而不是客服脚本或说明书。',
    '- 先回应用户这句话真正想要什么；有情绪时先接住情绪，再给信息。',
    '- 不要说「作为 AI/模型/系统」；不要用「很高兴为您服务」「请提供更多信息」这类空泛套话。',
    '- 短问题短答；复杂任务先给可执行建议，再问最多 1 个关键问题。',
    '- 沿用上下文称呼和口吻，不要每轮复述用户原话凑字数。',
    '- 信息不足时，说清楚缺哪一点，并顺手给一个可选方向。',
    '- 用户只是闲聊、吐槽、试探或一句很短的话时，先自然接住，不要立刻升级成任务、流程或表单。',
    '- 回答要有“上一轮听进去了”的感觉：必要时引用上下文里的具体点，但不要机械总结。',
    '- 若用户明确要求极简（如「只答 ok」「一句话」「不要解释」），严格遵守字数与格式，不要追加背景或延伸。',
  ]
  if (channel === 'voice') {
    parts.push(
      '语音回复优先 1-3 句，像真实对话一样自然停顿；用短句，少铺垫，不要使用 Markdown 标题、表格或长列表。',
    )
  } else {
    parts.push(
      '文字回复可以用 Markdown，但只有答案较长时才加标题；不要为了格式显得生硬。',
    )
  }
  return parts.join('\n')
}

function buildSystemPrompt(
  activeBotPersona: string,
  knowledgePack: string,
  inlineFiles?: Array<{ name: string; text: string }>,
  directEmployeeHint?: string,
  readPhaseNote?: string,
  userText?: string,
  webContextPack?: string,
): string {
  const parts: string[] = []
  const outputContract = detectOutputContract(userText || '')
  if (activeBotPersona) {
    parts.push(activeBotPersona)
  } else {
    parts.push('你是一个简洁直接的中文 AI 助手。优先给出可执行答案；如果信息不足，先给合理假设，再列出需要确认的问题。')
  }
  parts.push(buildHumanChatStylePrompt('text'))
  const contractRules = outputContractSystemRules(outputContract)
  if (contractRules) parts.push(contractRules)
  if (directEmployeeHint && directEmployeeHint.trim()) {
    parts.push(directEmployeeHint.trim())
  }
  if (readPhaseNote && readPhaseNote.trim()) {
    parts.push(readPhaseNote.trim())
  }
  if (personalSettings.value.memory && personalSettings.value.memory.trim()) {
    parts.push(`关于用户的长期记忆（请在回答中合理利用，但不要每次都重复念出）：\n${personalSettings.value.memory.trim()}`)
  }
  const hasEmployeeRead = (inlineFiles || []).some((f) => String(f.name || '').includes('读取员工解析'))
  if (inlineFiles && inlineFiles.length > 0) {
    const blocks = inlineFiles
      .map((f, idx) => `### @附件${idx + 1}：${f.name}\n\n${f.text}`)
      .join('\n\n---\n\n')
    const lead = hasEmployeeRead
      ? '以下包含「读取员工」用 direct_python 从用户原文件解析出的结构化/全文内容（非模型臆造）。你必须以这些解析结果为准回答；禁止编造表格单元格、CSV 行、PDF/Word 段落。若某段解析为空或报错，请如实说明并建议用户检查文件格式。'
      : '以下是用户按顺序直接上传的附件全文；用户消息里的 @附件1、@附件2 会对应这里的同序号文件。请按编号理解文件之间的先后逻辑，并优先据此回答。'
    parts.push(`${lead}\n\n${blocks}`)
  }
  if (knowledgePack) {
    parts.push(
      `以下是用户当前提问相关的资料库片段（来自其本人上传的文档），优先据此回答；若与提问无关请忽略：\n${knowledgePack}`,
    )
  }
  if (webContextPack && webContextPack.trim()) {
    parts.push(
      `【联网检索摘要 · 本轮注入】\n以下内容由系统在发送前从公开网页检索并抓取（Bing/Tavily/DDG 等），请优先参考并回答；必须在文末列出「参考链接」小节（标题 + URL）。若与附件或资料库冲突，以附件/资料库为准。\n\n${webContextPack.trim()}`,
    )
  }
  if (!outputContract) {
    parts.push('回答时使用 Markdown：标题用 ## / ###，列表用「-」或「1.」，代码用 ``` 包裹并标注语言；公式用 $$ 包裹；如需画图请用 ```mermaid 代码块。')
  }
  return parts.join('\n\n')
}

function rebuildContextMessages(forSendUpToIndex?: number): Array<{ role: string; content: string }> {
  const msgs = directMessages.value
  const sliceEnd = typeof forSendUpToIndex === 'number' ? forSendUpToIndex + 1 : msgs.length
  return msgs.slice(0, sliceEnd).map((m) => ({ role: m.role, content: m.content }))
}

function directEmployeeSystemHint(): string {
  const office = officeEmployeeCapabilitySystemHint()
  const id = String(directChatEmployeeId.value || '').trim()
  if (!id) return office
  const picked = directEmployeeOptions.value.find((e) => e.id === id)
  const label = picked ? `${picked.name}（${picked.sourceLabel}）` : id
  return [
    office,
    `【一档测试绑定员工（单选）】当前绑定 id：${id}；显示：${label}。回答时请尽量贴合该员工职责与知识边界；若问题明显超出该角色，可简要说明后给出通用建议。`,
  ].join('\n\n')
}

function withRequestTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('request_timeout')), ms)
    promise.then(
      (v) => {
        window.clearTimeout(timer)
        resolve(v)
      },
      (e) => {
        window.clearTimeout(timer)
        reject(e)
      },
    )
  })
}

function formatDirectChatError(e: unknown): string {
  let msg = e instanceof Error ? e.message : String(e ?? '生成失败')
  try {
    if (msg.trim().startsWith('{')) {
      const parsed = JSON.parse(msg)
      if (typeof parsed?.detail === 'string') msg = parsed.detail
    }
  } catch {
    /* keep msg */
  }
  if (msg.includes('未登录') || msg.includes('登录已过期')) return '登录已过期，请重新登录'
  return msg
}

function handleDirectChatAuthFailure() {
  clearAuthTokens()
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath || '/' } })
}

const DIRECT_KB_RETRIEVE_MS = 2500
const DIRECT_WEB_SEARCH_MS = 18_000

type DirectKbResult = {
  knowledgePack: string
  citations: Array<{ title: string; snippet?: string; url?: string }>
}

async function retrieveKnowledgeForDirect(
  userText: string,
  provider: string,
  model: string,
): Promise<DirectKbResult> {
  let knowledgePack = ''
  let citations: DirectKbResult['citations'] = []
  if (!userText.trim()) return { knowledgePack, citations }
  try {
    const pickedEmp = String(directChatEmployeeId.value || '').trim()
    const botEmp = String(activeBot.value?.id || '').trim()
    const employeeId = pickedEmp || botEmp
    const res: any = await withRequestTimeout(
      api.knowledgeV2Retrieve({
        query: userText,
        top_k: 6,
        employee_id: employeeId || undefined,
        embedding_provider: provider,
        embedding_model: model,
      }),
      DIRECT_KB_RETRIEVE_MS,
    )
    const items = Array.isArray(res?.items) ? res.items : []
    if (items.length > 0) {
      knowledgePack = formatKnowledgeContext(items)
      citations = items.slice(0, 6).map((it: any, i: number) => {
        const filename = String(it?.filename || '资料')
        const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
        const snippet = String(it?.content || '').trim().slice(0, 200)
        return { title: `${i + 1}. ${filename}${pageNo ? ` · 第 ${pageNo} 页` : ''}`, snippet }
      })
    }
  } catch {
    try {
      const ready = directAttachedFiles.value.some((f) => f.status === 'ready')
      const hasUserUploads = activeConversation.value?.messages?.some(
        (m) => Array.isArray(m.attachments) && m.attachments.some((a) => a.status === 'ready'),
      )
      if ((ready || hasUserUploads) && isEmbeddingConfigured()) {
        const res: any = await withRequestTimeout(
          api.knowledgeSearch(userText, 6, {
            embeddingProvider: provider,
            embeddingModel: model,
          }),
          DIRECT_KB_RETRIEVE_MS,
        )
        const items = Array.isArray(res?.items) ? res.items : []
        knowledgePack = formatKnowledgeContext(items)
        citations = items.slice(0, 6).map((it: any, i: number) => {
          const filename = String(it?.filename || '资料')
          const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
          const snippet = String(it?.content || '').trim().slice(0, 200)
          return { title: `${i + 1}. ${filename}${pageNo ? ` · 第 ${pageNo} 页` : ''}`, snippet }
        })
      }
    } catch {
      /* 检索失败不阻塞聊天 */
    }
  }
  return { knowledgePack, citations }
}

function markDirectFirstToken() {
  try {
    performance.mark('wb-direct-first-token')
    performance.measure('wb-direct-send-to-first-token', 'wb-direct-send', 'wb-direct-first-token')
  } catch {
    /* ignore */
  }
}

async function runDirectChatTurn(opts: {
  userMsg?: ChatMessage
  assistantId: string
  userText: string
  inlineFiles?: Array<{ name: string; text: string }>
  readPhaseNote?: string
  outputDownloads?: Array<{ jobId: string; filename: string; label?: string }>
}) {
  directError.value = ''
  directSendPending.value = false
  directLoading.value = true
  let firstTokenMarked = false
  let kbResult: DirectKbResult | null = null
  let webResult: DirectWebSearchResult | null = null
  const hasOutputDownloads = userFacingOutputDownloads(opts.outputDownloads || []).length > 0
  const polishAssistantContent = (raw: string) => {
    let s = String(raw || '')
    if (/sandbox:|file:\/\//i.test(s)) s = softenSandboxDownloadLinks(s)
    if (hasOutputDownloads && !/见下方文件卡片/.test(s)) {
      s = s ? `${s}\n\n_可下载文件见下方按钮或输入框上方「已生成」卡片。_` : '_可下载文件见下方按钮或输入框上方「已生成」卡片。_'
    }
    return s
  }
  try {
    const resolvePromise = resolveChatProviderModel()
    const kbPromise = opts.userText
      ? resolvePromise.then(({ provider, model }) =>
          retrieveKnowledgeForDirect(opts.userText, provider, model).then((r) => {
            kbResult = r
          }),
        )
      : Promise.resolve()
    const webPromise =
      directWebSearchEnabled.value && opts.userText.trim()
        ? (async () => {
            directWebSearching.value = true
            try {
              webResult = await retrieveWebForDirect(opts.userText)
            } finally {
              directWebSearching.value = false
            }
          })()
        : Promise.resolve()

    const { provider, model } = await resolvePromise
    await Promise.all([kbPromise, webPromise])

    const readNoteParts = [opts.readPhaseNote, webResult?.note].filter(Boolean)
    const sys = buildSystemPrompt(
      activeBot.value?.persona || '',
      kbResult?.knowledgePack || '',
      opts.inlineFiles,
      directEmployeeSystemHint(),
      readNoteParts.length ? readNoteParts.join('；') : undefined,
      opts.userText,
      webResult?.contextPack,
    )
    const ctx = directMessages.value
      .filter((m) => m.id !== opts.assistantId)
      .map((m) => ({ role: m.role, content: m.content }))
    const msgs = [{ role: 'system', content: sys }, ...ctx]
    if (ttsAutoRead.value) {
      streamingTts.stop()
      streamingTts.resetStream()
      ttsStreamAssistantId = opts.assistantId
      speakingMessageId.value = opts.assistantId
    }
    const handle = streamLLMChat({
      provider,
      model,
      messages: msgs,
      maxTokens: 2048,
      onToken: (_delta, soFar) => {
        if (soFar.trim() && !firstTokenMarked) {
          firstTokenMarked = true
          markDirectFirstToken()
        }
        updateAssistantMessage(opts.assistantId, (m) => {
          m.content = polishAssistantContent(soFar)
          m.pending = true
        })
        if (ttsAutoRead.value && ttsStreamAssistantId === opts.assistantId) {
          streamingTts.feed(polishAssistantContent(soFar))
        }
      },
      onError: (e) => {
        const msg = formatDirectChatError(e)
        if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
        directError.value = msg
        updateAssistantMessage(opts.assistantId, (m) => {
          m.pending = false
          m.error = msg
          if (!m.content) m.content = msg
        })
      },
      onDone: (full, aborted) => {
        const cits = kbResult?.citations ?? []
        updateAssistantMessage(opts.assistantId, (m) => {
          m.pending = false
          if (aborted) {
            m.content = m.content ? `${m.content}\n\n_（已中断）_` : '_（已中断）_'
          } else if (full) {
            m.content = polishAssistantContent(full)
          }
          if (cits.length) m.citations = cits
          if (opts.outputDownloads?.length) {
            const facing = userFacingOutputDownloads(opts.outputDownloads)
            if (facing.length) {
              m.outputDownloads = facing
              pushDirectGeneratedDownloads(facing)
            }
          }
        })
        if (ttsAutoRead.value && ttsStreamAssistantId === opts.assistantId) {
          if (aborted) {
            streamingTts.stop()
          } else {
            streamingTts.finish(polishAssistantContent(full))
          }
          speakingMessageId.value = ''
          ttsStreamAssistantId = ''
        }
      },
    })
    currentStreamHandle = handle
    await handle.done
    await kbPromise
    const lateCits = kbResult?.citations ?? []
    if (lateCits.length) {
      updateAssistantMessage(opts.assistantId, (m) => {
        if (!m.citations?.length) m.citations = lateCits
      })
    }
  } catch (e: any) {
    const msg = formatDirectChatError(e)
    if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
    directError.value = msg
    updateAssistantMessage(opts.assistantId, (m) => {
      m.pending = false
      m.error = msg
      if (!m.content) m.content = msg
    })
  } finally {
    currentStreamHandle = null
    directLoading.value = false
    directSendPending.value = false
  }
}

async function runDirectEmployeeReadForLlm(opts: {
  files: Array<{ file: File; name: string; readEmployeeId?: string }>
  userText?: string
  onProgress?: (line: string) => void
}): Promise<{
  inlineFiles: Array<{ name: string; text: string }>
  downloads: Array<{ jobId: string; filename: string; label?: string }>
  readErrors: string[]
  readSummary: string
}> {
  const inlineFiles: Array<{ name: string; text: string }> = []
  const downloads: Array<{ jobId: string; filename: string; label?: string }> = []
  const readErrors: string[] = []
  const summaryLines: string[] = []
  for (const item of opts.files) {
    const employeeId = resolveDirectFileEmployeeId(item)
    if (!employeeId) {
      readErrors.push(`${item.name}：未匹配读取员工`)
      continue
    }
    opts.onProgress?.(`正在用 **${readEmployeeDisplayName(employeeId)}** 解析 \`${item.name}\`…`)
    try {
      const res = await api.employeeExecuteFile(employeeId, item.file, {
        task: opts.userText ? '全量读取并供后续问答' : '全量读取',
        inputData: opts.userText ? { user_query: opts.userText } : {},
      })
      const llmText = extractEmployeeReadTextForLlm(res)
      if (!llmText.trim()) {
        readErrors.push(`${item.name}：读取员工未返回可用正文（可能执行失败或 outputs 为空）`)
        const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
        summaryLines.push(text)
        continue
      }
      inlineFiles.push({
        name: `${item.name}（读取员工解析·${readEmployeeDisplayName(employeeId)}）`,
        text: llmText,
      })
      const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
      summaryLines.push(text)
      downloads.push(...parseEmployeeOutputDownloads(res))
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      readErrors.push(`${item.name}：${msg}`)
    }
  }
  return {
    inlineFiles,
    downloads,
    readErrors,
    readSummary: summaryLines.join('\n\n---\n\n'),
  }
}

async function sendDirectChat(text = '') {
  if (directAttachedFiles.value.some((f) => f.status === 'uploading')) {
    directError.value = '附件仍在上传中，请稍候'
    return
  }
  const userText = String(text || directDraft.value || '').trim()
  const filesSnapshot = [...directAttachedFiles.value]
  const employeeFiles = filesSnapshot.filter(
    (f) => f.purpose === 'employee' && f.status === 'ready' && f.file instanceof File,
  )
  const knowledgeFiles = filesSnapshot.filter((f) => f.purpose !== 'employee')
  const note = directAttachmentNote(filesSnapshot)
  let userContent = userText
  if (note) userContent = userContent ? `${userContent}\n\n${note}` : note
  if (!userContent && employeeFiles.length) {
    userContent = note || '请全量读取以上附件'
  }
  if (!userContent || directLoading.value) return
  if (!requireLoginForWorkbenchUse()) return
  if ((directImageGenEnabled.value || directVideoGenEnabled.value) && !userText) {
    directError.value = '生图/生视频需要文字描述，请在输入框填写后发送'
    return
  }

  for (const f of employeeFiles) {
    const eid = resolveDirectFileEmployeeId(f)
    const ext = directFileExt(f.name)
    if (!eid || !employeeAcceptsFileExtension(eid, ext)) {
      const hint = eid ? employeeFileMismatchHint(eid, ext) : employeeFileMismatchHint(directChatEmployeeId.value, ext)
      directError.value = `${f.name}：${hint}`
      return
    }
  }

  const conv = ensureActiveConversation()
  if (activeConversationId.value !== conv.id) {
    activeConversationId.value = conv.id
    saveActiveId(conv.id)
    wbSidebar.setActiveConversationId(conv.id)
  }
  directDraft.value = ''
  directError.value = ''

  const userMsg = makeMessage('user', userContent, {
    skills: [],
    attachments: filesSnapshot.map((f) => ({ name: f.name, size: f.size, status: f.status, docId: f.docId })),
  })
  const inlineFiles = knowledgeFiles
    .filter((f: any) => (f.status === 'inline' || f.status === 'ready') && f.extractedText)
    .map((f: any) => ({ name: f.name, text: f.extractedText as string }))

  const placeholder = makeMessage('assistant', '', { pending: true })
  appendUserAndAssistant(userMsg, placeholder)
  directAttachedFiles.value = []
  directSendPending.value = true
  try {
    performance.mark('wb-direct-send')
  } catch {
    /* ignore */
  }

  if (directImageGenEnabled.value) {
    directSendPending.value = false
    directLoading.value = true
    directMediaGenerating.value = true
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '正在生成图片…'
    })
    try {
      const urls = await mediaGenRunner.generateImages(userText, {
        size: directImageSize.value,
        style: directImageStyle.value,
        count: directImageCount.value,
      })
      const list = Array.isArray(urls) ? urls.filter(Boolean) : []
      const md = list.map((u, i) => `![生成图${i + 1}](${u})`).join('\n')
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.agentLabel = 'AI 创作'
        m.content = list.length
          ? `（AI 生图）${userText}\n\n${md}`
          : `（AI 生图）${userText}\n\n未返回图片，请检查模型配置后重试。`
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directMediaGenerating.value = false
    }
    return
  }

  if (directVideoGenEnabled.value) {
    directSendPending.value = false
    directLoading.value = true
    directMediaGenerating.value = true
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '正在提交生视频任务…'
    })
    try {
      const res = await mediaGenRunner.generateVideo(userText, {
        aspect: directVideoAspect.value,
        durationSec: directVideoDurationSec.value,
      })
      const body = [res.message]
      if (res.previewUrl) body.push(`预览：${res.previewUrl}`)
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.agentLabel = 'AI 创作'
        m.content = `（AI 生视频）${userText}\n\n${body.filter(Boolean).join('\n\n')}`
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directMediaGenerating.value = false
    }
    return
  }

  const allAttachNames = filesSnapshot.map((f) => f.name)
  const conversationAttachNames = collectOfficeAttachmentNamesFromMessages(directMessages.value)
  const officeAttachNames = mergeOfficeAttachmentNames(allAttachNames, conversationAttachNames)
  const conversationUserText = collectRecentUserIntentText(directMessages.value)
  const officeTask = classifyOfficeTask(userText, officeAttachNames, { conversationUserText })
  const cachedReadResults = getCachedOfficeReadResults(conv.id)
  const missingDeliverable = detectUserMissingDeliverableComplaint(userText)

  if (missingDeliverable && cachedReadResults.length && !employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    const fmt = pickGenerateFormat(`${userText}\n${conversationUserText}`, officeAttachNames)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '**补跑生成**：正在根据已读取的附件调用 PPT/Office 生成员产出可下载文件…'
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText: userText || conversationUserText,
        readResults: cachedReadResults,
        extraAttachmentFiles: [],
        templateFile: pickPptTemplateFromSources(
          filesSnapshot
            .filter((f) => f.file instanceof File)
            .map((f) => ({ name: f.name, file: f.file as File })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = msg
        })
      } else {
        pushDirectGeneratedDownloads(genPhase.downloads)
        const facing = userFacingOutputDownloads(genPhase.downloads)
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.content = [
            genPhase.summary,
            facing.length
              ? '请在输入框上方「已生成」卡片或下方按钮下载 **output.pptx**（含模板增强与动画），勿使用对话里的占位下载链接。'
              : '',
          ]
            .filter(Boolean)
            .join('\n\n')
          if (facing.length) m.outputDownloads = facing
        })
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directSendPending.value = false
    }
    return
  }

  if (officeTask === 'generate' && !employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    const fmt = pickGenerateFormat(userText, officeAttachNames)
    const stepTotal = 2
    const extraFiles = filesSnapshot
      .filter((f) => f.file instanceof File)
      .map((f) => f.file as File)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = cachedReadResults.length
        ? `**步骤 1/${stepTotal}**：正在根据已读取的附件调用生成员工产出可下载文件…`
        : `**步骤 1/${stepTotal}**：正在用生成员工根据您的描述产出可下载文件（支持纯文本 / JSON 模板）…`
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText,
        readResults: cachedReadResults,
        extraAttachmentFiles: extraFiles,
        templateFile: pickPptTemplateFromSources(
          extraFiles.map((f) => ({ name: f.name, file: f })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = genPhase.summary || msg
        })
        directLoading.value = false
        return
      }
      pushDirectGeneratedDownloads(genPhase.downloads)
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = true
        m.content = `${genPhase.summary}\n\n**步骤 2/${stepTotal}**：正在根据生成结果由 AI 解读…`
        const facingGen = userFacingOutputDownloads(genPhase.downloads)
        if (facingGen.length) m.outputDownloads = facingGen
      })
      await runDirectChatTurn({
        userMsg,
        assistantId: placeholder.id,
        userText:
          userText ||
          '请根据上方生成结果简要说明产出文件用途；用户可在输入框上方「已生成」文件卡片中下载。',
        inlineFiles,
        readPhaseNote:
          '生成阶段已完成：用户已在输入框上方看到「已生成」文件卡片，请引导其点击卡片下载；勿输出 sandbox: 链接，勿声称无法提供 Office 文件。',
        outputDownloads: userFacingOutputDownloads(genPhase.downloads),
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directSendPending.value = false
    }
    return
  }

  if (employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    let wantGenerate = officeTask === 'generate'
    if (
      !wantGenerate &&
      primaryOfficeFormatFromAttachments(officeAttachNames) === 'ppt' &&
      detectOfficeEnhanceAttachedIntent(`${userText}\n${conversationUserText}`, officeAttachNames)
    ) {
      wantGenerate = true
    }
    const stepTotal = wantGenerate ? 3 : 2
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = `**步骤 1/${stepTotal}**：正在用读取员工全量解析附件（direct_python，非编造）…`
    })
    let readPhase: Awaited<ReturnType<typeof runOfficeReadPhase>> | null = null
    try {
      readPhase = await runOfficeReadPhase({
        files: employeeFiles.map((f) => ({
          file: f.file as File,
          name: f.name,
          readEmployeeId: f.readEmployeeId,
        })),
        userText,
        resolveReadEmployeeId: resolveDirectFileEmployeeId,
        onProgress: (line) => {
          updateAssistantMessage(placeholder.id, (m) => {
            m.pending = true
            m.content = `**步骤 1/${stepTotal}**：${line}`
          })
        },
      })
      if (readPhase?.rawResults?.length) {
        cacheOfficeReadResults(conv.id, readPhase.rawResults)
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
      directLoading.value = false
      directSendPending.value = false
      return
    }
    const empInline = readPhase?.inlineFiles || []
    const readErrors = readPhase?.readErrors || []
    let allDownloads = userFacingOutputDownloads(readPhase?.downloads || [])
    let genSummary = ''
    if (wantGenerate && readPhase?.rawResults?.length) {
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = true
        m.content = `**步骤 2/${stepTotal}**：正在调用生成员工产出可下载文件…`
        if (allDownloads.length) m.outputDownloads = allDownloads
      })
      const genFmt = pickGenerateFormat(userText, officeAttachNames)
      const genPhase = await runDirectOfficeGeneratePhase({
        format: genFmt,
        userText,
        readResults: readPhase.rawResults,
        templateFile: pickPptTemplateFromSources(
          employeeFiles.map((f) => ({ name: f.name, file: f.file as File })),
        ),
      })
      genSummary = genPhase.summary
      allDownloads = userFacingOutputDownloads([...allDownloads, ...genPhase.downloads])
      pushDirectGeneratedDownloads(genPhase.downloads)
      if (genPhase.errors.length && !genPhase.downloads.length) {
        readErrors.push(...genPhase.errors)
      }
    }
    if (!empInline.length && !allDownloads.length) {
      const msg =
        readErrors.join('；') || '读取员工未能解析出可用内容，请确认已部署对应员工包且服务器依赖（openpyxl/pypdf/python-docx）已安装'
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = readPhase?.readSummary || msg
        if (allDownloads.length) m.outputDownloads = allDownloads
      })
      directLoading.value = false
      directSendPending.value = false
      return
    }
    const readNote =
      readErrors.length > 0
        ? `读取/生成阶段部分失败：${readErrors.join('；')}`
        : wantGenerate && allDownloads.length
          ? '读取与生成已完成：用户可在输入框上方「已生成」文件卡片中下载 Office 文件；对话回答仅作解读，勿输出 sandbox: 链接，勿声称无法提供文件。'
          : '读取阶段已完成：以下附件正文来自读取员工真实解析。'
    const summaryBlock = [readPhase?.readSummary, genSummary].filter(Boolean).join('\n\n---\n\n')
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = `${summaryBlock}\n\n**步骤 ${stepTotal}/${stepTotal}**：正在根据解析结果由 AI 分析回答…`
      if (allDownloads.length) m.outputDownloads = allDownloads
    })
    const combinedInline = [...empInline, ...inlineFiles]
    const llmUserText =
      userText ||
      (wantGenerate
        ? '请根据上方读取/生成结果简要说明产出文件用途与结构要点；用户可点击下载。'
        : '请根据上方「读取员工解析」的附件内容回答：先简要概括文件结构/要点，再按用户后续意图给出可执行建议。禁止编造未出现在解析中的数据。')
    await runDirectChatTurn({
      userMsg,
      assistantId: placeholder.id,
      userText: llmUserText,
      inlineFiles: combinedInline,
      readPhaseNote: readNote,
      outputDownloads: allDownloads,
    })
    return
  }

  await runDirectChatTurn({ userMsg, assistantId: placeholder.id, userText, inlineFiles })
  const assistantAfterChat = directMessages.value.find((m) => m.id === placeholder.id)
  const promisedFile = Boolean(
    assistantAfterChat &&
      !userFacingOutputDownloads(assistantAfterChat.outputDownloads || []).length &&
      assistantImpliesPendingFileGeneration(assistantAfterChat.content),
  )
  const manualStepsOnly = Boolean(
    assistantAfterChat && assistantGaveManualOfficeStepsOnly(assistantAfterChat.content),
  )
  const canRecoverGenerate = shouldRecoverOfficeGenerate(
    userText,
    allAttachNames,
    conversationAttachNames,
    promisedFile || manualStepsOnly,
    conversationUserText,
  )
  if (promisedFile && canRecoverGenerate) {
    directLoading.value = true
    const fmt = pickGenerateFormat(userText, officeAttachNames)
    const extraFiles = filesSnapshot
      .filter((f) => f.file instanceof File)
      .map((f) => f.file as File)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '**补跑生成**：正在调用生成员工产出可下载文件…'
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText,
        readResults: cachedReadResults,
        extraAttachmentFiles: extraFiles,
        templateFile: pickPptTemplateFromSources(
          extraFiles.map((f) => ({ name: f.name, file: f })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = `${assistantAfterChat?.content || ''}\n\n---\n\n**生成失败**：${msg}`
        })
      } else {
        pushDirectGeneratedDownloads(genPhase.downloads)
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.content = [assistantAfterChat?.content, genPhase.summary].filter(Boolean).join('\n\n---\n\n')
          const facingRecover = userFacingOutputDownloads(genPhase.downloads)
          if (facingRecover.length) m.outputDownloads = facingRecover
        })
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = `${assistantAfterChat?.content || ''}\n\n---\n\n**生成失败**：${msg}`
      })
    } finally {
      directLoading.value = false
    }
  } else if (promisedFile) {
    const warn = officeGenerateMissingInputMessage(pickGenerateFormat(userText, officeAttachNames))
    directError.value =
      '助手提到正在生成文件，但本次未调用生成员工；请重新附上 Office 文件，或在消息中加入「生成/导出/动画」等描述后重试。'
    updateAssistantMessage(placeholder.id, (m) => {
      m.content = `${m.content}\n\n---\n\n⚠️ ${warn}`
    })
  }
}

function stopGeneration() {
  if (currentStreamHandle) {
    currentStreamHandle.abort()
  }
  directLoading.value = false
  directSendPending.value = false
  if (speakingMessageId.value) {
    stopDirectTtsPlayback()
    speakingMessageId.value = ''
    ttsStreamAssistantId = ''
  }
}

async function downloadOutput(jobId: string, filename: string, label?: string) {
  try {
    const res = await api.employeeOutputDownload(jobId, filename)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    butlerDownloadHistory.recordSingle(
      jobId,
      filename,
      label || filename.split(/[/\\]/).pop() || filename,
      directChatEmployeeId.value || undefined,
    )
  } catch (e: any) {
    console.error('下载失败', e)
    const msg = e instanceof Error ? e.message : String(e)
    directError.value = `下载失败：${msg}。若对话中只有文字「下载」链接而无上方「已生成」卡片，请先发送「生成带动画的 pptx」或重新附上 PPT 后点发送。`
  }
}

async function regenerateAssistant(messageId: string) {
  if (directLoading.value) return
  const msgs = directMessages.value
  const idx = msgs.findIndex((m) => m.id === messageId)
  if (idx <= 0) return
  let userIdx = -1
  for (let i = idx - 1; i >= 0; i -= 1) {
    if (msgs[i].role === 'user') {
      userIdx = i
      break
    }
  }
  if (userIdx < 0) return
  const userText = msgs[userIdx].content
  patchActiveConversation((c) => {
    c.messages.splice(idx, 1)
  })
  const placeholder = makeMessage('assistant', '', { pending: true })
  patchActiveConversation((c) => {
    c.messages.push(placeholder)
  })
  await runDirectChatTurn({ assistantId: placeholder.id, userText })
}

function startEditUserMessage(messageId: string) {
  const m = directMessages.value.find((x) => x.id === messageId)
  if (!m || m.role !== 'user') return
  editingMessageId.value = messageId
  editingDraft.value = m.content
}

async function commitEditedUserMessage() {
  const id = editingMessageId.value
  const draft = String(editingDraft.value || '').trim()
  if (!id || !draft) {
    editingMessageId.value = ''
    editingDraft.value = ''
    return
  }
  const idx = directMessages.value.findIndex((m) => m.id === id)
  if (idx < 0) {
    editingMessageId.value = ''
    return
  }
  patchActiveConversation((c) => {
    c.messages[idx] = { ...c.messages[idx], content: draft }
    c.messages.splice(idx + 1)
  })
  editingMessageId.value = ''
  editingDraft.value = ''
  const placeholder = makeMessage('assistant', '', { pending: true })
  patchActiveConversation((c) => {
    c.messages.push(placeholder)
  })
  await runDirectChatTurn({ assistantId: placeholder.id, userText: draft })
}

function cancelEditUserMessage() {
  editingMessageId.value = ''
  editingDraft.value = ''
}

function setMessageFeedback(messageId: string, fb: 'up' | 'down' | null) {
  patchActiveConversation((c) => {
    const idx = c.messages.findIndex((m) => m.id === messageId)
    if (idx < 0) return
    c.messages[idx] = { ...c.messages[idx], feedback: fb }
  })
}

async function speakMessage(messageId: string) {
  if (speakingMessageId.value === messageId) {
    stopDirectTtsPlayback()
    speakingMessageId.value = ''
    return
  }
  const m = directMessages.value.find((x) => x.id === messageId)
  if (!m?.content) return

  stopDirectTtsPlayback()
  const text = cleanTextForTts(m.content)
  if (!text) return

  speakingMessageId.value = messageId
  ttsStreamAssistantId = ''
  try {
    await streamingTts.speak(text)
  } catch {
    directError.value = '朗读失败。'
  } finally {
    if (speakingMessageId.value === messageId) speakingMessageId.value = ''
  }
}

function copyConversationLink(c: Conversation) {
  const md = exportConversationAsMarkdown(c)
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${c.title || '对话'}-${c.id.slice(0, 8)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function newConversationHandler() {
  if (currentStreamHandle) {
    currentStreamHandle.abort()
    currentStreamHandle = null
  }
  directLoading.value = false
  stopDirectTtsPlayback()
  speakingMessageId.value = ''
  editingMessageId.value = ''
  editingDraft.value = ''
  directDraft.value = ''
  directError.value = ''
  directIsDragging.value = false
  directDragDepth.value = 0
  llmDdOpen.value = null
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  orchPhase.value = 'idle'
  orchTimingStartMs.value = null
  orchestrationEtaSeconds.value = null
  finalizeLoading.value = false
  finalizeError.value = ''
  const files = directAttachedFiles.value.slice()
  directAttachedFiles.value = []
  for (const item of files as Array<{ docId?: string }>) {
    if (item.docId) {
      void api.knowledgeDeleteDocument(item.docId).catch(() => {
      })
    }
  }
  resetVoiceSession({ resumeListening: true })
  ensureActiveConversation({ forceNew: true })
}

/** 清空语音会话（新对话 / 重置） */
function resetVoiceSession(opts?: { resumeListening?: boolean }) {
  interruptVoice()
  voiceStreamHandle?.abort()
  voiceStreamHandle = null
  voiceMessages.value = []
  voiceDraft.value = ''
  voiceTranscript.value = ''
  voiceLivePreview.value = ''
  voiceUtteranceQueue = []
  voiceReport.value = ''
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  voiceMicPausedByUser.value = false
  resetVoiceListenSession()
  voiceChatBusy.value = false
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  streamingTts.stop()
  streamingTts.resetStream()
  clearInjectQueue()
  dismissPlanSession()
  dismissPendingHandoff()
  resetVoiceSessionState(
    voiceSessionState,
    composerIntent.value === 'employee' ? 'employee' : composerIntent.value === 'mod' ? 'mod' : 'skill',
  )
  clearMakeProgressCache()
  syncVoiceWorkPhase()
  if (opts?.resumeListening) {
    nextTick(() => void startVoiceRecognition({ fresh: true }))
  }
}

function setActiveConversation(id: string) {
  if (!id) return
  if (currentStreamHandle) currentStreamHandle.abort()
  const loaded = loadConversations()
  const switching = id !== activeConversationId.value
  const stale = shouldReloadConversationFromStorage(
    directMessages.value.length,
    loaded.find((c) => c.id === id)?.messages,
  )
  if (switching || stale) {
    conversations.value = mergeConversationsForPick(
      conversations.value,
      loaded,
      id,
      directMessages.value.length,
    )
  }
  if (switching) {
    directGeneratedFiles.value = []
    clearDirectGenerating()
  }
  activeConversationId.value = id
  saveActiveId(id)
  wbSidebar.setActiveConversationId(id)
}

function pickConversation(id: string) {
  setActiveConversation(id)
}

function convTimeFormat(t) {
  if (!t) return ''
  const d = new Date(t)
  const diff = Date.now() - d.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function isFileEmployeePurposeToggle(f) {
  return isEmployeeSpreadsheetExt(directFileExt(String(f.name || '')))
}

function isFileAutoReadEmployee(f) {
  const ext = directFileExt(String(f.name || ''))
  return isEmployeeExecuteFileExt(ext) && !isEmployeeSpreadsheetExt(ext)
}

function setFilePurpose(fileId: string, purpose: string) {
  const f = directAttachedFiles.value.find((a) => String(a.id) === fileId)
  if (!f) return
  f.purpose = purpose
  if (purpose === 'employee') {
    const readId = resolveReadEmployeeForExtension(directFileExt(String(f.name || '')))
    if (readId) {
      f.readEmployeeId = readId
      applyDirectReadEmployeePick(readId)
    }
    if (f.status === 'uploading') {
      f.status = 'ready'
      f.docId = ''
      f.ingesting = false
      f.ingestError = ''
    }
  } else if (purpose === 'knowledge' && f.status === 'ready' && f.file && !f.extractedText && !f.docId) {
    f.status = 'uploading'
    void uploadDirectAttachedFile(f)
  }
}

function pinConversation(id: string) {
  conversations.value = conversations.value.map((c) =>
    c.id === id ? { ...c, pinned: !c.pinned, updatedAt: Date.now() } : c,
  )
  persistConversations()
}

function renameConversation(id: string, title: string) {
  conversations.value = conversations.value.map((c) =>
    c.id === id ? { ...c, title: title.slice(0, 60), updatedAt: Date.now() } : c,
  )
  persistConversations()
}

function exportConversation(id: string) {
  const c = conversations.value.find((x) => x.id === id)
  if (!c) return
  copyConversationLink(c)
}

function removeConversation(id: string) {
  if (!window.confirm('确定删除这个对话？删除后无法恢复。')) return
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (activeConversationId.value === id) {
    activeConversationId.value = conversations.value[0]?.id || ''
    saveActiveId(activeConversationId.value)
    wbSidebar.setActiveConversationId(activeConversationId.value)
  }
  persistConversations()
}

function clearAllConversations() {
  if (!window.confirm('清空全部对话？此操作不可恢复。')) return
  conversations.value = []
  activeConversationId.value = ''
  saveActiveId('')
  persistConversations()
}

function onComposerPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items?.length) return
  const images: File[] = []
  for (const it of Array.from(items)) {
    if (it.kind === 'file') {
      const f = it.getAsFile()
      if (f && f.type.startsWith('image/')) images.push(f)
    }
  }
  if (!images.length) return
  e.preventDefault()
  void ingestComposerFiles(images)
}

/** 拖入计数：dragenter/leave 在子元素切换时会成对触发，单纯靠 dragleave 关闭遮罩会闪烁，
 *  改用计数器在所有子元素都 leave 完成后再清零。 */
const directDragDepth = ref(0)

function dragHasFiles(e: DragEvent): boolean {
  const types = e.dataTransfer?.types
  if (!types) return false
  for (let i = 0; i < types.length; i += 1) {
    if (types[i] === 'Files') return true
  }
  return false
}

function onSurfaceDragEnter(e: DragEvent) {
  if (!dragHasFiles(e)) return
  e.preventDefault()
  directDragDepth.value += 1
  directIsDragging.value = true
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

function onSurfaceDragOver(e: DragEvent) {
  if (!dragHasFiles(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

function onSurfaceDragLeave(e: DragEvent) {
  if (!dragHasFiles(e)) return
  directDragDepth.value = Math.max(0, directDragDepth.value - 1)
  if (directDragDepth.value === 0) directIsDragging.value = false
}

function onSurfaceDrop(e: DragEvent) {
  directDragDepth.value = 0
  directIsDragging.value = false
  const list = e.dataTransfer?.files
  if (!list?.length) return
  e.preventDefault()
  void ingestComposerFiles(Array.from(list))
}

async function ingestComposerFiles(files: File[], target: 'direct' | 'make' = 'direct') {
  const remaining = Math.max(0, 12 - directAttachedFiles.value.length)
  const accepted = files.slice(0, remaining)
  const items = accepted.map((file) => {
    if (file.type.startsWith('image/')) {
      return {
        id: makeDirectAttachId(),
        name: file.name,
        size: file.size || 0,
        status: 'skipped',
        docId: '',
        error: '图片暂以「文件名 + 简短描述」形式给模型；接入视觉模型后会改为 base64 上送。',
        ingesting: false,
        ingestError: '',
        file,
      }
    }
    return buildDirectAttachItem(file)
  })
  const firstRead = items.find((it) => it.readEmployeeId)
  if (firstRead?.readEmployeeId) applyDirectReadEmployeePick(firstRead.readEmployeeId)
  directAttachedFiles.value = [...directAttachedFiles.value, ...items]
  appendAttachmentMentions(accepted, target)
  for (const it of items) {
    if (it.status === 'uploading') void uploadDirectAttachedFile(it)
  }
}

function refreshAllBots() {
  allBots.value = loadAllBots()
}

function onCreateAgent(bot: AgentBot) {
  const my = loadMyBots()
  const next = [{ ...bot, mine: true }, ...my.filter((b) => b.id !== bot.id)]
  saveMyBots(next)
  const fav = loadFavorites()
  fav.add(bot.id)
  saveFavorites(fav)
  refreshAllBots()
}

function onRemoveAgent(bot: AgentBot) {
  if (!bot.mine) return
  if (!window.confirm(`删除我的 Bot「${bot.name}」？`)) return
  const my = loadMyBots().filter((b) => b.id !== bot.id)
  saveMyBots(my)
  const fav = loadFavorites()
  fav.delete(bot.id)
  saveFavorites(fav)
  if (activeBotId.value === bot.id) {
    activeBotId.value = ''
    saveActiveBotId('')
  }
  refreshAllBots()
}

function onFavoriteAgent(bot: AgentBot) {
  const fav = loadFavorites()
  if (fav.has(bot.id)) fav.delete(bot.id)
  else fav.add(bot.id)
  saveFavorites(fav)
  refreshAllBots()
}

function onStartWithAgent(bot: AgentBot) {
  activeBotId.value = bot.id
  saveActiveBotId(bot.id)
  showAgentMarket.value = false
  ensureActiveConversation({ forceNew: true, bot })
}

function clearActiveBot() {
  activeBotId.value = ''
  saveActiveBotId('')
}

function customerServiceQueryContext(): string {
  const q = route.query || {}
  if (String(q.assistant || '') !== 'customer-service') return ''
  const scene = String(q.scene || 'general')
  const parts = [
    '我从市场或导航进入 AI 客服，需要处理以下问题：',
    `场景：${scene}`,
  ]
  const catalogId = String(q.catalog_id || '').trim()
  const pkgId = String(q.pkg_id || '').trim()
  const itemName = String(q.item_name || '').trim()
  const materialCategory = String(q.material_category || '').trim()
  const orderNo = String(q.order_no || '').trim()
  const complaintType = String(q.complaint_type || '').trim()
  if (catalogId) parts.push(`商品 ID：${catalogId}`)
  if (pkgId) parts.push(`包名：${pkgId}`)
  if (itemName) parts.push(`商品名称：${itemName}`)
  if (materialCategory) parts.push(`市场类目：${materialCategory}`)
  if (orderNo) parts.push(`订单号：${orderNo}`)
  if (complaintType) parts.push(`问题类型：${complaintType}`)
  parts.push('请先告诉我还需要补充哪些证据材料，并给出下一步处理路径。')
  return parts.join('\n')
}

function stripCustomerServiceEntryQueryFromUrl() {
  const q = { ...(route.query as Record<string, string | string[] | undefined>) }
  const keys = [
    'assistant',
    'scene',
    'catalog_id',
    'pkg_id',
    'item_name',
    'material_category',
    'order_no',
    'complaint_type',
  ]
  let changed = false
  for (const k of keys) {
    if (Object.prototype.hasOwnProperty.call(q, k)) {
      delete q[k]
      changed = true
    }
  }
  if (!changed) return
  void router.replace({ path: route.path, query: q })
}

/** 避免 keep-alive 下 onMounted 与 onActivated 同一帧各跑一次，重复 forceNew 会话 */
let lastAppliedCustomerServiceQueryKey = ''

function applyCustomerServiceRouteContext() {
  if (String(route.query?.assistant || '') !== 'customer-service') return
  const bot = allBots.value.find((b) => b.id === 'customer-service')
  if (!bot) return
  const dedupeKey = JSON.stringify(route.query)
  if (dedupeKey === lastAppliedCustomerServiceQueryKey) return
  lastAppliedCustomerServiceQueryKey = dedupeKey
  activeBotId.value = bot.id
  saveActiveBotId(bot.id)
  const ctx = customerServiceQueryContext()
  const conv = ensureActiveConversation({ forceNew: true, bot })
  if (ctx) {
    conv.messages.push(makeMessage('user', ctx, { agentLabel: bot.name }))
    conv.messages.push(makeMessage('assistant', '我已收到这些上下文。请继续补充证据截图、链接、订单号或你希望平台采取的处理结果；如果信息已完整，我会帮你整理成可提交给管理员的工单摘要。', { agentLabel: bot.name }))
    persistConversations()
  }
  stripCustomerServiceEntryQueryFromUrl()
}

const directFontPxStyle = computed(() => ({
  '--wb-direct-font-px': `${personalSettings.value.fontPx}px`,
}))

const mediaGenRunner = {
  async generateImages(prompt: string, opts: { size: string; style: string; count: number }) {
    const safePrompt = prompt.slice(0, 240)
    const styled = opts.style && opts.style !== 'default' ? `${opts.style} 风格，` : ''
    try {
      if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
        await loadLlmCatalogForWorkbench()
      }
      const { resolveMediaProviderModel } = await import('../llmMedia')
      const { provider, model } = resolveMediaProviderModel('image', llmCatalog.value)
      if (!model) {
        throw new Error('未找到可用的生图模型，请在「资金与记录 → 大模型 API」中选择含生图模型的厂商并刷新目录')
      }
      const res = await api.llmGenerateImage(provider, model, `${styled}${safePrompt}`, {
        size: opts.size,
        count: opts.count,
      })
      const urls = Array.isArray(res?.images) ? res.images.filter(Boolean) : []
      if (urls.length) return urls
    } catch {
      // 未配置真实生图模型时保留占位图回退，避免打断创作流程。
    }
    const items: string[] = []
    for (let i = 0; i < Math.max(1, Math.min(4, opts.count)); i += 1) {
      const seed = `${safePrompt}-${opts.size}-${i}`
      const url = `https://picsum.photos/seed/${encodeURIComponent(seed)}/${opts.size.replace('x', '/')}`
      items.push(url)
    }
    return items
  },
  async generatePptOutline(topic: string, audience: string, pages: number) {
    const { provider, model } = await resolveChatProviderModel()
    const sys = '你是高级 PPT 大纲编写者。为给定主题生成精炼的 markdown 大纲：每页用 ## 标题，下方 3-5 个要点（- 开头），并附 1 行口播说明。控制在指定页数内。'
    const usr = `主题：${topic}\n受众/风格：${audience || '通用商务'}\n页数：${pages}\n请直接输出 markdown 大纲。`
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: sys },
      { role: 'user', content: usr },
    ], 1800)
    return String(res?.content || '').trim() || '（无输出）'
  },
  async generatePptx(topic: string, markdown: string) {
    return await api.llmGeneratePptxBlob(topic, markdown, `${topic.slice(0, 32) || 'ai-presentation'}.pptx`)
  },
  async generateDocument(kind: string, inputs: string) {
    const { provider, model } = await resolveChatProviderModel()
    const kindMap: Record<string, string> = {
      weekly: '周报',
      proposal: '商业方案/提案',
      article: '公众号文章',
      redbook: '小红书种草文案',
      email: '商务邮件',
    }
    const sys = `你是擅长写「${kindMap[kind] || kind}」的中文写手。结构清晰、节奏流畅、有重点；输出 markdown，必要时用列表与小标题。不要套话，先抓重点。`
    const usr = `信息素材：${inputs}\n请直接输出成稿。`
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: sys },
      { role: 'user', content: usr },
    ], 2200)
    return String(res?.content || '').trim() || '（无输出）'
  },
  async generateVideo(prompt: string, opts: { aspect: string; durationSec: number }) {
    const safePrompt = prompt.slice(0, 240)
    try {
      if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
        await loadLlmCatalogForWorkbench()
      }
      const { resolveMediaProviderModel } = await import('../llmMedia')
      const { provider, model } = resolveMediaProviderModel('video', llmCatalog.value)
      if (provider && model) {
        const res = await api.llmChat(provider, model, [
          {
            role: 'system',
            content:
              '你是视频生成助手。根据用户描述输出 JSON：{"status":"pending","message":"…","jobId":"…"}。若上游为异步任务，说明预计等待时间。',
          },
          { role: 'user', content: `画幅 ${opts.aspect}，时长约 ${opts.durationSec} 秒。描述：${safePrompt}` },
        ], 1200)
        const raw = String(res?.content || '').trim()
        if (raw) {
          return { status: 'pending' as const, message: raw, previewUrl: '' }
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      return {
        status: 'pending' as const,
        message: `${msg}\n\n请在「资金与记录 → 大模型 API」筛选「支持生视频」并配置对应厂商密钥。`,
        previewUrl: '',
      }
    }
    return {
      status: 'pending' as const,
      message: `已记录视频需求（${opts.aspect}，约 ${opts.durationSec}s）：${safePrompt}\n\n未找到可用视频模型，请在「资金与记录 → 大模型 API」中刷新目录并选择含生视频模型的厂商。`,
      previewUrl: '',
    }
  },
}

function insertGeneratedToChat(text: string) {
  if (!text) return
  ensureActiveConversation()
  const m = makeMessage('assistant', text, {
    agentLabel: 'AI 创作',
  })
  patchActiveConversation((c) => c.messages.push(m))
  showMediaGen.value = false
}

async function handleVoicePhoneTurn(userText: string): Promise<string> {
  ensureActiveConversation()
  const userMsg = makeMessage('user', userText, { agentLabel: '语音电话' })
  const placeholder = makeMessage('assistant', '', { pending: true })
  appendUserAndAssistant(userMsg, placeholder)
  await runDirectChatTurn({ assistantId: placeholder.id, userText })
  const m = directMessages.value.find((x) => x.id === placeholder.id)
  return stripInternalMarkers(m?.content || '')
}

function onDirectKeydown(e) {
  if (e.key !== 'Enter' || e.shiftKey) return
  e.preventDefault()
  void sendDirectChat()
}

function onComposerFocus(e: FocusEvent) {
  if (!wbNav.isMobile) return
  const el = e.target as HTMLElement | null
  if (!el) return
  window.setTimeout(() => {
    try {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } catch {
      el.scrollIntoView(true)
    }
  }, 320)
}

function onOrbClick() {
  void unlockVoiceAudioPlayback()
  if (voiceError.value) {
    voiceError.value = ''
  }
  voiceMicFallbackHint.value = ''
  if (wbNav.isMobile && (voiceMicPausedByUser.value || !voiceListening.value)) {
    requestMicInUserGesture()
  }
  if (
    voiceState.value === 'processing' ||
    voiceState.value === 'reporting' ||
    streamingTts.state.value !== 'idle'
  ) {
    interruptVoice()
    setTimeout(() => activateVoiceContinuous({ submitPending: false }), 400)
  } else if (voiceListening.value || voiceState.value === 'listening') {
    void finishContinuousUtterance()
  } else {
    voiceMicPausedByUser.value = false
    void activateVoiceContinuous({ submitPending: false })
  }
}

/** AI 说完话后自动开始听 */
async function speakTextAndListen(text: string) {
  voiceState.value = 'reporting'
  try {
    await streamingTts.speak(text)
  } finally {
    voiceReport.value = ''
    void activateVoiceContinuous({ submitPending: false })
  }
}

function toggleVoiceListening() {
  if (voiceListening.value) {
    void stopVoiceRecognition()
    return
  }
  voiceError.value = ''
  void startVoiceRecognition()
}

async function stopVoiceAsr(): Promise<string> {
  return voiceChat.stopAsr()
}

function onVoiceAsrError(msg: string) {
  const result = voiceChat.onAsrError(msg)
  if (!result) return
  if (result.msg && !result.retry) {
    voiceError.value = result.msg
  } else if (result.msg) {
    voiceError.value = result.msg
  }
  voiceReport.value = ''
  if (result.retry) {
    const fresh = result.fresh !== false
    setTimeout(() => startVoiceRecognition({ fresh }), result.delayMs ?? 400)
  }
}

async function startVoiceRecognition(opts?: { fresh?: boolean }) {
  if (voiceChat.getSubmitLock()) return
  if (voiceMicPausedByUser.value && opts?.fresh !== false) return
  voiceError.value = ''
  voiceMicFallbackHint.value = ''
  const res = await voiceChat.startListening(opts)
  if (res?.error) {
    const soft = /权限|Permission|NotAllowed|NotReadable|NotFound|denied|启动失败|麦克风|不支持|语音识别/i.test(res.error)
    if (soft) {
      voiceMicPausedByUser.value = true
      voiceState.value = 'idle'
      voiceReport.value = ''
      voiceChatPhase.value = 'idle'
      voiceMicFallbackHint.value = '语音没接上，先打字也能继续聊；点右下角 ▶ 再试麦克风。'
      return
    }
    voiceError.value = res.error
  }
}

async function stopVoiceRecognition() {
  return voiceChat.stopListening()
}

function ensureVoiceListening() {
  if (wbSidebar.activeMode !== 'voice') return
  voiceChat.ensureListening()
}

function interruptVoice() {
  cancelSpeculativeVoiceTurn()
  voiceChat.interruptCapture()
  voiceStreamHandle?.abort()
  voiceStreamHandle = null
  streamingTts.stop()
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  voiceReport.value = ''
}

function resumeVoiceListeningAfterTurn() {
  if (wbSidebar.activeMode !== 'voice') return
  if (voiceMicPausedByUser.value) return
  setTimeout(() => {
    voiceChat.ensureListening()
    void drainVoiceUtteranceQueue()
  }, 300)
}

async function drainVoiceUtteranceQueue() {
  if (voiceUtteranceDraining || voiceChatBusy.value || !voiceUtteranceQueue.length) return
  const next = voiceUtteranceQueue.shift()
  if (!next) return
  voiceUtteranceDraining = true
  try {
    await dispatchVoiceUtteranceCore(next, { userAlreadyInThread: true })
  } finally {
    voiceUtteranceDraining = false
    if (voiceUtteranceQueue.length) void drainVoiceUtteranceQueue()
  }
}

async function dispatchVoiceUtterance(
  text: string,
  opts?: { alreadySubmitted?: boolean; fromTypedComposer?: boolean },
) {
  const content = sanitizeVoiceUtteranceText(text)
  if (!content) return
  if (
    !voiceHumanChatMode.value &&
    !opts?.fromTypedComposer &&
    !isLikelyShortProceedFragment(content) &&
    isLikelyAsrEchoNoise(content, buildVoiceTopicHint(content))
  ) {
    return
  }
  if (!requireLoginForWorkbenchUse()) return
  voiceChat.clearContinuousSilenceTimer()
  if (opts?.fromTypedComposer) {
    appendVoiceUserTurn(content)
    noteVoiceSubmitted(content)
  } else if (!opts?.alreadySubmitted) {
    noteVoiceSubmitted(content)
  }

  if (voiceChatBusy.value) {
    voiceUtteranceQueue.push(content)
    const last = voiceMessages.value[voiceMessages.value.length - 1]
    if (!last || last.role !== 'user' || last.content !== content) {
      appendVoiceUserTurn(content)
    }
    return
  }
  await dispatchVoiceUtteranceCore(content)
}

function buildVoiceTopicHint(extra?: string): string {
  return [
    voiceSessionState.value.userGoal,
    ...voiceMessages.value.map((m) => String(m.content || '')),
    extra || '',
  ].join(' ')
}

function ensureVoiceEmployeeIntent(content?: string) {
  if (wbSidebar.activeMode !== 'voice') return
  if (voiceHumanChatMode.value) return
  if (planSession.value?.intentKey === 'employee') {
    composerIntent.value = 'employee'
    return
  }
  if (pendingHandoff.value?.intentKey === 'employee') {
    composerIntent.value = 'employee'
    return
  }
  if (hasEmployeePlanContext(voiceSessionState.value, voiceMessages.value, content)) {
    composerIntent.value = 'employee'
    return
  }
  if (content && looksLikeEmployeeTaskDescription(content)) {
    composerIntent.value = 'employee'
  }
}

function shouldRouteVoiceAsEmployee(content?: string): boolean {
  if (voiceHumanChatMode.value) return false
  if (composerIntent.value === 'employee') return true
  if (wbSidebar.activeMode !== 'voice') return false
  if (planSession.value?.intentKey === 'employee') return true
  if (pendingHandoff.value?.intentKey === 'employee') return true
  if (hasEmployeePlanContext(voiceSessionState.value, voiceMessages.value, content)) return true
  return Boolean(content && looksLikeEmployeeTaskDescription(content))
}

function buildVoiceRouteContext() {
  const ps = planSession.value
  const lastAssistant = [...voiceMessages.value].reverse().find((m) => m.role === 'assistant')
  return {
    orchPhase: orchPhase.value,
    hasPlanSession: Boolean(ps),
    hasPendingHandoff: Boolean(pendingHandoff.value),
    canRunOrch: canRunOrchestration.value,
    planSessionPhase: ps?.phase,
    planIntentKey: ps?.intentKey,
    orchestrating:
      orchPhase.value === 'running' ||
      orchPhase.value === 'estimating' ||
      finalizeLoading.value,
    composerIntent: composerIntent.value,
    pendingHandoff: Boolean(pendingHandoff.value),
    finalizeLoading: finalizeLoading.value,
    voiceTitle: ps?.summaryTitle || ps?.intentTitle || '',
    checklistLineCount: ps?.checklistLines?.length ?? 0,
    lastAssistantSnippet: String(lastAssistant?.content || '').slice(0, 280),
  }
}

async function executeLegacyVoiceRoute(
  action: ReturnType<typeof routeVoiceUtterance>,
  content: string,
  opts?: { userAlreadyInThread?: boolean },
) {
  switch (action.type) {
    case 'cancel_work':
      pollStop.value = true
      await speakVoiceShort('好的，已停止当前制作。')
      return
    case 'status_query':
      await speakVoiceShort(
        buildOrchestrationStatusSummary(orchestrationSession.value?.steps) ||
          (pendingHandoff.value ? '草稿已准备好，可以说开始生成。' : '当前没有进行中的制作。'),
      )
      return
    case 'confirm_generate':
      await runOrchestration()
      await speakVoiceShort('已开始生成，你可以在上方查看进度。')
      resumeVoiceListeningAfterTurn()
      return
    case 'inject':
      await injectVoiceDuringWork(content)
      return
    case 'plan_reply':
      await handleVoicePlanReply(content)
      return
    case 'new_task':
      await openPlanSessionFromVoice(content)
      resumeVoiceListeningAfterTurn()
      return
    case 'chat':
    default:
      await runVoiceChatTurn(content, undefined, { skipUserAppend: opts?.userAlreadyInThread })
      return
  }
}

async function dismissPlanSessionFromVoice() {
  dismissPlanSession()
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  voiceSessionState.value.planDismissedAt = Date.now()
  syncVoiceWorkPhase()
}

/** 员工模式：未进入正式规划前的 summary 面板视为过期，对话时自动收起 */
function shouldAutoDismissStaleVoicePlan(): boolean {
  const ps = planSession.value
  if (!ps || composerIntent.value !== 'employee') return false
  if (ps.phase !== 'summary') return false
  if (voiceSessionState.value.readyToPlan && voiceSessionState.value.stage === 'planning') return false
  return true
}

function dismissStaleVoicePlanSilently() {
  if (!shouldAutoDismissStaleVoicePlan()) return
  dismissPlanSession()
  voiceSessionState.value.stage = 'exploring'
  voiceSessionState.value.readyToPlan = false
  syncVoiceWorkPhase()
}

async function onVoiceDismissPlanPanel() {
  await dismissPlanSessionFromVoice()
  if (wbSidebar.activeMode === 'voice' && !voiceMicPausedByUser.value) {
    resumeVoiceListeningAfterTurn()
  }
}

async function applyEmployeeSessionClassify(text: string) {
  if (composerIntent.value !== 'employee') return
  try {
    const routeCtx = buildVoiceRouteContext()
    const { provider, model } = await resolveChatProviderModel()
    const classification = await classifyVoiceTurn({
      text,
      state: voiceSessionState.value,
      recentMessages: voiceMessages.value.slice(-6),
      routeCtx,
      composerIntent: composerIntent.value,
      provider,
      model,
    })
    applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
  } catch {
    /* 预响应路径不阻塞 TTS */
  }
}

async function resolveEmployeeClassification(content: string) {
  streamingTts.warmUp()
  const routeCtx = buildVoiceRouteContext()
  const { provider, model } = await resolveChatProviderModel()
  const classification = await classifyVoiceTurn({
    text: content,
    state: voiceSessionState.value,
    recentMessages: voiceMessages.value.slice(-6),
    routeCtx,
    composerIntent: composerIntent.value,
    provider,
    model,
  })
  return classification
}

async function resumeVoiceAfterChatTurn(useTts: boolean) {
  if (useTts && voiceUseUnified.value) {
    voiceState.value = 'reporting'
    await voiceUnified.whenAudioIdle()
  } else if (useTts && voiceUseS2S.value) {
    voiceState.value = 'reporting'
    await voiceS2s.whenAudioIdle()
  } else if (useTts && streamingTts.state.value !== 'idle') {
    voiceState.value = 'reporting'
    await streamingTts.whenIdle()
  }
  voiceState.value = 'idle'
  resumeVoiceListeningAfterTurn()
}

function ensureEmployeePlanContextFromVoice(content: string) {
  const inferred = inferUserGoalFromVoiceMessages(voiceMessages.value, content)
  if (inferred) voiceSessionState.value.userGoal = inferred
}

async function dispatchEmployeeVoiceUtterance(
  content: string,
  opts?: {
    userAlreadyInThread?: boolean
    skipReclassify?: boolean
    prefetchedClassification?: VoiceTurnClassification
  },
) {
  const routeCtx = buildVoiceRouteContext()
  const fast = routeVoiceUtterance({ text: content, ...routeCtx })
  if (['cancel_work', 'status_query', 'confirm_generate', 'inject'].includes(fast.type)) {
    return executeLegacyVoiceRoute(fast, content, opts)
  }

  const classification =
    opts?.prefetchedClassification ?? (await resolveEmployeeClassification(content))
  applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)

  const skipUserAppend = opts?.userAlreadyInThread
  const chatHint =
    classification.replyHint ||
    (classification.action === 'clarify'
      ? '先复述你对用户意思的理解，并追问 1-2 个关键点；不要开规划或画流程图。'
      : undefined)

  switch (classification.action) {
    case 'cancel_work':
      pollStop.value = true
      voiceSessionState.value.stage = 'exploring'
      await speakVoiceShort('好的，已停止当前制作。')
      return
    case 'status':
      await speakVoiceShort(
        buildOrchestrationStatusSummary(orchestrationSession.value?.steps) ||
          (pendingHandoff.value ? '草稿已准备好，可以说开始生成。' : '当前没有进行中的制作。'),
      )
      return
    case 'dismiss_plan':
      await dismissPlanSessionFromVoice()
      await runVoiceChatTurn(
        content,
        chatHint || '用户质疑过早开规划。说明当前并未执行制作，问是否现在要进入需求规划。',
        { skipUserAppend },
      )
      return
    case 'open_plan':
      if (!voiceSessionState.value.readyToPlan && classification.confidence < 0.65) {
        dismissStaleVoicePlanSilently()
        voiceSessionState.value.stage = 'clarifying'
        await runVoiceChatTurn(
          content,
          chatHint || '目标尚未明确。先复述理解并追问职责、场景或产出，不要开规划面板。',
          { skipUserAppend },
        )
        return
      }
      ensureEmployeePlanContextFromVoice(content)
      voiceSessionState.value.readyToPlan = true
      dismissStaleVoicePlanSilently()
      await openPlanSessionFromVoice(content, { skipUserAppend })
      voiceSessionState.value.stage = 'planning'
      resumeVoiceListeningAfterTurn()
      return
    case 'pause_checklist':
      voiceChecklistPaused.value = true
      await speakVoiceShort('好的，先不自动制作；需要时说开始或确认生成。')
      resumeVoiceListeningAfterTurn()
      return
    case 'update_plan':
    case 'confirm_plan':
      await handleVoicePlanReplySmart(content, classification, { skipUserAppend })
      return
    case 'clarify':
    case 'chat':
    default:
      dismissStaleVoicePlanSilently()
      if (voiceSessionState.value.lastUserTone === 'complaint' && planSession.value) {
        dismissPlanSession()
        voiceSessionState.value.stage = 'exploring'
        voiceSessionState.value.readyToPlan = false
        syncVoiceWorkPhase()
      }
      await runVoiceChatTurn(content, chatHint, { skipUserAppend })
      return
  }
}

async function dispatchVoiceUtteranceCore(
  content: string,
  opts?: { userAlreadyInThread?: boolean; fromTypedComposer?: boolean },
) {
  voiceError.value = ''
  if (voiceHumanChatMode.value) {
    dismissStaleVoicePlanSilently()
    await runVoiceChatTurn(content, undefined, {
      skipUserAppend: opts?.userAlreadyInThread || opts?.fromTypedComposer,
      fromTypedComposer: opts?.fromTypedComposer,
    })
    return
  }
  ensureVoiceEmployeeIntent(content)
  if (shouldRouteVoiceAsEmployee(content)) {
    await dispatchEmployeeVoiceUtterance(content, opts)
    return
  }
  const action = routeVoiceUtterance({
    text: content,
    ...buildVoiceRouteContext(),
  })
  await executeLegacyVoiceRoute(action, content, opts)
}

async function resummarizeVoiceEmployeePlan(forceConcrete: boolean) {
  const ps = planSession.value
  if (!ps || ps.intentKey !== 'employee') return
  const briefBase = ps.fullBrief || ps.displayBrief || ps.initialBrief || ''
  const briefForSummary =
    briefBase +
    (forceConcrete
      ? '\n\n【系统指令】以上语音对话已充分描述员工目标与产出。请直接输出具体 TITLE 与 SUMMARY，禁止 TITLE:待澄清；尚未拍板的细节写在 SUMMARY 末尾「待确认：…」。'
      : '')
  const { provider, model } = await resolveChatProviderModel()
  ps.loading = true
  ps.streamingText = ''
  try {
    const handle = streamLLMChat({
      provider,
      model,
      messages: [
        { role: 'system', content: buildPlanSummarySystemPrompt(ps.intentTitle, 'employee-voice') },
        { role: 'user', content: briefForSummary },
      ],
      maxTokens: 700,
      onToken: (_delta, soFar) => {
        if (planSession.value) planSession.value.streamingText = soFar
      },
    })
    const { content } = await handle.done
    if (planSession.value) planSession.value.streamingText = ''
    const parsed = parsePlanSummary(content, ps.displayBrief || ps.fullBrief)
    ps.summaryTitle = parsed.title
    ps.summaryText = parsed.summary
    ps.summaryNeedsClarification = isSummaryNeedsClarification(parsed.title, parsed.summary)
    ps.initialBrief = `${parsed.title}\n${parsed.summary}`
  } finally {
    ps.loading = false
  }
}

/** 执行清单阶段：口头「开始/确认生成」→ 确认清单并启动 14 步编排 */
async function confirmEmployeeChecklistAndRunFromVoice() {
  if (autoPilotRunning.value || finalizeLoading.value) {
    await speakVoiceShort('制作已在进行，请稍候并向上查看进度。')
    return
  }
  const ps = planSession.value
  if (pendingHandoff.value && canRunOrchestration.value) {
    await speakVoiceShort('好的，正在根据清单开始制作，请稍候。')
    try {
      await runOrchestration()
      if (finalizeError.value) {
        await speakVoiceShort(`制作启动失败：${finalizeError.value}`)
      } else if (!orchestrationSessionId.value) {
        await speakVoiceShort('制作未能启动，请点「确认清单并进入制作」重试。')
      }
    } catch (e) {
      await speakVoiceShort(friendlyPlanPanelApiError(e))
    }
    return
  }
  if (!ps || ps.phase !== 'checklist') {
    await speakVoiceShort('当前没有待确认的执行清单，请先说需求或点「确认清单并进入制作」。')
    return
  }
  if (ps.loading) {
    await speakVoiceShort('清单还在生成，请稍候。')
    return
  }
  await speakVoiceShort('好的，正在根据清单开始制作，请稍候。')
  confirmPlanAndOpenHandoff()
  voiceSessionState.value.stage = 'executing'
  syncVoiceWorkPhase()
  await nextTick()
  if (!pendingHandoff.value) {
    await speakVoiceShort('未能生成制作草稿，请点击「确认清单并进入制作」。')
    return
  }
  if (!canRunOrchestration.value) {
    await speakVoiceShort('制作草稿不完整，请补充描述后重试。')
    return
  }
  try {
    await runOrchestration()
    if (finalizeError.value) {
      await speakVoiceShort(`制作启动失败：${finalizeError.value}`)
    } else if (!orchestrationSessionId.value) {
      await speakVoiceShort('制作未能启动，请点「确认清单并进入制作」重试。')
    }
  } catch (e) {
    await speakVoiceShort(friendlyPlanPanelApiError(e))
  }
}

async function voiceEmployeePlanPostOpen(triggerText: string) {
  const ps = planSession.value
  if (!ps || ps.intentKey !== 'employee') return
  const hasContext = hasEmployeePlanContext(
    voiceSessionState.value,
    voiceMessages.value,
    triggerText,
  )

  if (ps.summaryNeedsClarification && hasContext) {
    await resummarizeVoiceEmployeePlan(true)
  }
  if (!ps.summaryNeedsClarification) {
    await confirmSummaryAndStartPlanning()
    await speakVoiceShort('已根据你的描述进入详细规划，你可以继续补充或直接回答我的问题。')
    return
  }
  await speakVoiceShort('摘要里还有几点待确认，请继续用语音或文字补充。')
}

async function openPlanSessionFromVoice(
  text: string,
  opts?: { skipUserAppend?: boolean },
) {
  const utterance = sanitizeVoiceUtteranceText(text)
  ensureVoiceEmployeeIntent(utterance)
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const wantsModFrontend = intent === 'mod' && modFrontendEnabled.value
  ensureEmployeePlanContextFromVoice(utterance)
  const briefCore =
    intent === 'employee'
      ? buildPlanBriefFromVoiceMessages(
          voiceSessionState.value,
          voiceMessages.value,
          utterance,
        )
      : utterance
  const payloadParts = [briefCore]
  if (intent === 'mod') {
    payloadParts.push(
      wantsModFrontend
        ? '【制作选项】本次需要为 Mod 生成可路由的定制 Vue 前端页面。'
        : '【制作选项】本次暂不生成定制前端。',
    )
  }
  payloadParts.push(`【语音输入 · ${intentMeta.value.title}】`)
  await openPlanSession({
    fullBrief: payloadParts.join('\n\n'),
    displayBrief: utterance,
    files: [],
    generateFrontend: wantsModFrontend,
  })
  if (!opts?.skipUserAppend) {
    appendVoiceUserTurn(utterance)
  }
  if (intent === 'employee') {
    await voiceEmployeePlanPostOpen(utterance)
    return
  }
  await speakVoiceShort('已开始规划，请继续补充需求或直接回答澄清问题。')
}

async function handleVoicePlanReplySmart(
  text: string,
  classification: VoiceTurnClassification,
  opts?: { skipUserAppend?: boolean },
) {
  const ps = planSession.value
  if (!ps) {
    await runVoiceChatTurn(text, classification.replyHint, { skipUserAppend: opts?.skipUserAppend })
    return
  }

  if (classification.action === 'dismiss_plan') {
    await dismissPlanSessionFromVoice()
    await runVoiceChatTurn(
      text,
      classification.replyHint || '用户不想继续当前规划。确认理解并询问下一步。',
      { skipUserAppend: opts?.skipUserAppend },
    )
    return
  }

  appendVoiceUserTurn(text)

  if (ps.phase === 'summary') {
    if (classification.action === 'confirm_plan' && !ps.summaryNeedsClarification) {
      await confirmSummaryAndStartPlanning()
      await speakVoiceShort('好的，已进入详细规划，你可以继续补充或直接回答我的问题。')
      resumeVoiceListeningAfterTurn()
      return
    }
    if (classification.action === 'update_plan' || classification.action === 'confirm_plan') {
      applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
      ps.displayBrief = text
      ps.fullBrief = buildPlanBriefFromVoiceMessages(
        voiceSessionState.value,
        voiceMessages.value,
        text,
      )
      ps.loading = true
      try {
        await summarizePlanSession()
      } finally {
        if (planSession.value) planSession.value.loading = false
      }
      await speakVoiceShort(
        ps.summaryNeedsClarification
          ? '还需要再补充一些信息，请继续说明。'
          : '已更新摘要，你可以说「开始规划」或点击确认。',
      )
      resumeVoiceListeningAfterTurn()
      return
    }
    await runVoiceChatTurn(text, classification.replyHint, { skipUserAppend: true })
    resumeVoiceListeningAfterTurn()
    return
  }

  if (ps.phase === 'chat') {
    if (classification.action === 'confirm_plan') {
      planReplyDraft.value = text
      await sendPlanReply()
      resumeVoiceListeningAfterTurn()
      return
    }
    planReplyDraft.value = text
    await sendPlanReply()
    resumeVoiceListeningAfterTurn()
    return
  }

  if (ps.phase === 'checklist') {
    if (classification.action === 'confirm_plan') {
      voiceChecklistPaused.value = false
      await confirmEmployeeChecklistAndRunFromVoice()
      resumeVoiceListeningAfterTurn()
      return
    }
    if (classification.action === 'update_plan') {
      planReplyDraft.value = text
      await sendPlanReply()
      resumeVoiceListeningAfterTurn()
      return
    }
    await speakVoiceShort(
      classification.replyHint || '清单已展示；说开始可进入制作，或说明要改哪一条。',
    )
    resumeVoiceListeningAfterTurn()
    return
  }
}

async function handleVoicePlanReply(text: string) {
  const ps = planSession.value
  if (!ps) {
    await runVoiceChatTurn(text)
    return
  }
  appendVoiceUserTurn(text)
  if (ps.phase === 'summary') {
    ps.displayBrief = text
    ps.fullBrief = `${ps.fullBrief || ''}\n${text}`.trim()
    await speakVoiceShort('已更新摘要，你可以说「开始规划」或点击确认。')
    resumeVoiceListeningAfterTurn()
    return
  }
  if (ps.phase === 'chat') {
    planReplyDraft.value = text
    await sendPlanReply()
    resumeVoiceListeningAfterTurn()
    return
  }
  if (ps.phase === 'checklist') {
    await confirmEmployeeChecklistAndRunFromVoice()
    resumeVoiceListeningAfterTurn()
    return
  }
}

async function injectVoiceDuringWork(text: string) {
  const t = sanitizeVoiceUtteranceText(text)
  if (!t || isPlaceholderPlanContent(t) || isLikelyShortProceedFragment(t)) return
  const topicHint = [voiceSessionState.value.userGoal, text].join(' ')
  if (isLikelyAsrEchoNoise(t, topicHint)) return
  if (pendingHandoff.value) {
    pendingHandoff.value.description = appendVoiceInject(pendingHandoff.value.description, t)
  } else if (planSession.value) {
    planSession.value.fullBrief = appendVoiceInject(planSession.value.fullBrief, t)
    if (planSession.value.displayBrief) {
      planSession.value.displayBrief = appendVoiceInject(planSession.value.displayBrief, t)
    }
  } else if (orchestrationSessionId.value || finalizeLoading.value) {
    pushInject(t)
  }
  appendVoiceUserTurn(t)
  await runVoiceChatTurn(t, '用户正在任务执行中补充需求。用一句话确认已记录，不要展开。', {
    skipUserAppend: true,
  })
}

function buildVoiceWorkbenchPrompt(extraHint?: string) {
  if (voiceHumanChatMode.value) {
    const parts = [
      `当前消费档位：${consumptionTier.value}。`,
      '【常态化聊天】当前是移动端聊天页/普通聊天模式：直接回答问题即可，不要引导做 Mod、做员工、Skill 组，不要打开规划或制作流程。',
      buildHumanChatStylePrompt('voice'),
      directEmployeeSystemHint(),
    ]
    if (platformChatMode.value) {
      parts.push(
        '【平台模式 · 工作台语音入口】这是嵌在工作台里的语音入口，不是独立电话式语音 App。用户未关闭平台模式前：只闲聊、接上下文，禁止引导或主动提起制作、规划、Skill 组；用户明确要做 Mod/员工时需提示其先关闭顶部平台模式。',
      )
    }
    const persona = String(activeBot.value?.persona || '').trim()
    if (persona) parts.push(persona)
    if (extraHint) parts.push(extraHint)
    return parts.filter(Boolean).join('\n')
  }
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const meta = INTENT_META[intent] || INTENT_META.skill
  const parts = [
    `当前消费档位：${consumptionTier.value}。`,
    `语音工作台模式：用户通过第三档「说」与你对话；左上角已选「${meta.title}」。`,
    '回复要短、口语化，适合朗读；可追问 1-2 个关键问题。',
    '禁止无实质内容的「嗯」「你说」「我在听」式空承接；先理解用户完整表述再回应。',
    buildHumanChatStylePrompt('voice'),
  ]
  if (intent === 'employee') {
    parts.push(
      '【做员工 · 对话优先】你是有自主意识的协作伙伴，不是收到一句话就立刻开工的规划器。',
      '先判断用户是在闲聊、抱怨、澄清、质疑进度，还是已明确下达「要生成/规划员工包」类任务。未明确任务前：只复述理解、追问关键点，不要说「已开始规划」或「会自动打开规划面板」。',
      '若用户质疑「怎么就开始做了」：说明当前并未在执行制作（可能是系统误判），问是否现在要进入需求规划。',
      '仅当用户已确认开始（如「开始规划」「开始写吧」）且系统话语分类将触发 open_plan 时：你可简短说正在整理摘要；禁止在未确认前承诺「会打开规划面板」。',
      buildAgentAwarePrompt(voiceSessionState.value, extraHint),
    )
  } else if (intent === 'mod') {
    parts.push(
      '【做 Mod】先理解用户在描述想法、补充细节还是下达制作任务；未明确前以澄清为主，不要催促进入规划。',
      '规划与清单格式约定（供用户稍后进入规划面板时参考）：',
      buildPlanSystemPrompt(intent, meta.title),
    )
  } else {
    parts.push(buildPlanSystemPrompt(intent, meta.title))
  }
  if (voiceWorkPhase.value === 'orchestrating') {
    parts.push('后台正在制作，用户可能在补充需求或问进度。')
  }
  if (extraHint && intent !== 'employee') parts.push(extraHint)
  return parts.join('\n')
}

function textsSimilarForFinalize(a: string, b: string): boolean {
  const x = a.trim()
  const y = b.trim()
  if (!x || !y) return false
  if (x === y) return true
  return Math.abs(x.length - y.length) <= 3 && (x.includes(y) || y.includes(x))
}

async function runVoiceUnifiedTurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; turnId?: string },
) {
  if (!opts?.skipUserAppend) appendVoiceUserTurn(userText)
  const assistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt(systemHint)
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  try {
    const content = await voiceUnified.endUtterance({
      text: userText,
      turnId: opts?.turnId || `t${Date.now()}`,
      system: sys,
      messages: history,
      provider,
      model,
      voice: ttsCfg.edgeVoice,
      rate: ttsCfg.rate,
      ttsEnabled: ttsAutoRead.value,
      maxTokens: 1024,
      onTextDelta: (_d, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
      },
    })
    const reply = content.trim() || '（无回复）'
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
    voiceMessages.value = msgs
    voiceReport.value = reply
  } catch (e: unknown) {
    voiceError.value = e instanceof Error ? e.message : String(e)
  } finally {
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    void resumeVoiceAfterChatTurn(ttsAutoRead.value)
  }
}

async function runVoiceS2STurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; turnId?: string },
) {
  if (s2sProvisionalStarted && textsSimilarForFinalize(userText, voiceMessages.value.filter((m) => m.role === 'user').pop()?.content || '')) {
    return
  }
  s2sProvisionalStarted = false
  if (!opts?.skipUserAppend) {
    appendVoiceUserTurn(userText)
  }
  const assistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt(systemHint)
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  try {
    const { content } = await voiceS2s.runTurn({
      text: userText,
      turnId: opts?.turnId,
      system: sys,
      messages: history,
      provider,
      model,
      voice: ttsCfg.edgeVoice,
      rate: ttsCfg.rate,
      ttsEnabled: ttsAutoRead.value,
      maxTokens: 1024,
      onTextDelta: (_delta, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
      },
    })
    const reply = content.trim() || '（无回复）'
    const msgs = [...voiceMessages.value]
    if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
    voiceMessages.value = msgs
    voiceReport.value = reply
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    voiceError.value = msg || voiceS2s.lastError.value
  } finally {
    s2sProvisionalStarted = false
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    void resumeVoiceAfterChatTurn(ttsAutoRead.value)
  }
}

async function runVoiceChatTurn(
  userText: string,
  systemHint?: string,
  opts?: { skipUserAppend?: boolean; speculative?: boolean; fromTypedComposer?: boolean },
) {
  if (voiceChatBusy.value && !opts?.speculative && !opts?.fromTypedComposer) return
  voiceChatBusy.value = true
  voiceChatPhase.value = 'streaming'
  voiceState.value = 'processing'
  const useTts = ttsAutoRead.value
  const useS2S = voiceUseS2S.value && !opts?.speculative
  const useUnified = voiceUseUnified.value && !opts?.speculative
  try {
    if (useUnified) {
      await runVoiceUnifiedTurn(userText, systemHint, { skipUserAppend: opts?.skipUserAppend })
      return
    }
    if (useS2S) {
      await runVoiceS2STurn(userText, systemHint, { skipUserAppend: opts?.skipUserAppend })
      return
    }
    if (!opts?.skipUserAppend) {
      appendVoiceUserTurn(userText)
    }
    const assistantIdx = voiceMessages.value.length
    voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
    const providerModelPromise = resolveChatProviderModel()
    const sys = buildVoiceWorkbenchPrompt(systemHint)
    const history = voiceMessages.value.slice(0, -1).map((m) => ({ role: m.role, content: m.content }))
    const ctx = opts?.speculative
      ? [...history, { role: 'user', content: userText }]
      : history
    if (useTts) {
      if (!opts?.speculative) streamingTts.stop()
      streamingTts.resetStream(VOICE_TTS_FEED_OPTS)
      streamingTts.warmUp()
    }
    const { provider, model } = await providerModelPromise
    voiceStreamHandle = streamLLMChat({
      provider,
      model,
      messages: [{ role: 'system', content: sys }, ...ctx],
      maxTokens: 1024,
      onToken: (_delta, soFar) => {
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: soFar }
        voiceMessages.value = msgs
        voiceReport.value = soFar
        if (useTts) streamingTts.feed(soFar)
      },
      onError: (e) => {
        voiceError.value = e?.message || String(e)
      },
      onDone: (full, aborted) => {
        const reply = (aborted ? voiceMessages.value[assistantIdx]?.content : full) || '（无回复）'
        const msgs = [...voiceMessages.value]
        if (msgs[assistantIdx]) msgs[assistantIdx] = { role: 'assistant', content: reply }
        voiceMessages.value = msgs
        voiceReport.value = reply
        if (useTts && !aborted) streamingTts.finish(reply)
        else if (useTts && aborted) streamingTts.stop()
      },
    })
    await voiceStreamHandle.done
  } catch (e) {
    voiceError.value = e?.message || String(e)
  } finally {
    voiceStreamHandle = null
    const s2sStillActive =
      voiceUseS2S.value && (s2sProvisionalStarted || voiceS2s.isPlaying() || voiceS2s.state.value === 'streaming')
    if (!s2sStillActive) {
      voiceChatBusy.value = false
      voiceChatPhase.value = 'idle'
      s2sProvisionalStarted = false
      void resumeVoiceAfterChatTurn(ttsAutoRead.value)
    }
  }
}

async function speakVoiceShort(text: string) {
  if (!text.trim()) {
    resumeVoiceListeningAfterTurn()
    return
  }
  voiceState.value = 'reporting'
  voiceChatPhase.value = 'speaking'
  voiceReport.value = text
  if (ttsAutoRead.value) {
    if (voiceUseS2S.value) {
      const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
      const { provider, model } = await resolveChatProviderModel()
      try {
        await voiceS2s.runTurn({
          text,
          system: '请用一句话朗读以下内容，不要展开。',
          messages: [],
          provider,
          model,
          voice: ttsCfg.edgeVoice,
          rate: ttsCfg.rate,
          ttsEnabled: true,
          maxTokens: 256,
          onTextDelta: () => {},
        })
        await voiceS2s.whenAudioIdle()
      } catch {
        await streamingTts.speak(text)
      }
    } else {
      await streamingTts.speak(text)
    }
  }
  voiceChatPhase.value = 'idle'
  voiceState.value = 'idle'
  resumeVoiceListeningAfterTurn()
}

/** @deprecated use dispatchVoiceUtterance */
async function submitVoiceTurn() {
  const content = voiceDraft.value.trim()
  if (!content) return
  await dispatchVoiceUtterance(content)
}

function speakText(text: string) {
  voiceState.value = 'reporting'
  void streamingTts.speak(text).finally(() => {
    if (voiceState.value === 'reporting') voiceState.value = 'idle'
  })
}

function speakTextAndContinue(text: string) {
  voiceState.value = 'reporting'
  void streamingTts.speak(text).finally(() => {
    voiceState.value = 'idle'
    if (voiceAutoSend.value && !voiceMicPausedByUser.value) {
      setTimeout(() => startVoiceRecognition({ fresh: true }), 400)
    }
  })
}

function syncVoiceWorkPhase() {
  syncWorkPhase({
    planSession: planSession.value,
    pendingHandoff: pendingHandoff.value,
    orchPhase: orchPhase.value,
  })
}

function confirmVoiceAndOpenHandoff() {
  if (!voiceMessages.value.length) return
  const text = formatPlanMessagesForBrief(voiceMessages.value)
  const intentKey = composerIntent.value
  const isEmployee = intentKey === 'employee'
  const routingBrief = isEmployee
    ? (pickBestEmployeeBriefFromVoice(voiceSessionState.value, voiceMessages.value) || text.split('\n')[0] || text).slice(0, 200)
    : ''
  pendingHandoff.value = {
    description: isEmployee
      ? `【初始想法】\n${routingBrief || text}`
      : `【语音规划记录】\n${text}`,
    employeeRoutingBrief: isEmployee ? routingBrief : undefined,
    intentTitle: intentMeta.value.title,
    intentKey,
    workflowName: suggestModIdFromText(text) || '',
    planNotes: isCanvasSkillIntent(intentKey) ? text : '',
    suggestedModId: intentKey === 'mod' ? suggestModIdFromText(text) : '',
    generateFrontend: intentKey === 'mod' ? modFrontendEnabled.value : false,
    employeeTarget: intentKey === 'employee' ? 'pack_only' : 'pack_only',
    employeeWorkflowName: '',
    fhdBaseUrl: '',
    planningMessages: voiceMessages.value.map((m) => ({ role: m.role, content: m.content })),
  }
  syncVoiceWorkPhase()
}

function requireLoginForWorkbenchUse() {
  if (getAccessToken()) return true
  const text = draft.value.trim()
  try {
    if (text) sessionStorage.setItem('workbench_home_pending_draft', text)
    sessionStorage.setItem('workbench_home_pending_intent', composerIntent.value)
  } catch {
    /* ignore */
  }
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath || '/' } })
  return false
}

const llmCatalog = ref(null)
const llmCatalogLoading = ref(false)
const llmCatalogError = ref('')
const selectedProvider = ref('openai')
const selectedModel = ref('')
/** auto：发送时用账户 preferences；manual：用下方自选并写回 preferences */
const modelMode = ref('auto')
/** 自选时厂商/模型自定义下拉：'provider' | 'model' | null（避免原生 select 白底弹层） */
const llmDdOpen = ref(null)
const llmMobileSheetOpen = ref(false)
let planSummaryStreamHandle: StreamHandle | null = null

const _canvasSkillMeta = {
  title: '生成 Skill 组',
  sub: '按描述生成可复用 Skill，并在画布上编排成 Skill 组（调度图）。要「可运行程序本体」请走脚本工作流。',
}
const INTENT_META = {
  mod: {
    title: '做 Mod',
    sub: '可先生成仓库与名片骨架，也可以继续补齐员工包登记、工作流绑定和真实执行验证。只有名片不等于可工作的员工。',
  },
  employee: {
    title: '做员工',
    sub: '提示词与工具 · 在下方用自然语言描述岗位与流程',
  },
  skill: _canvasSkillMeta,
  /** @deprecated 会话缓存旧键，等同于 skill */
  workflow: _canvasSkillMeta,
}

const intentMeta = computed(() => INTENT_META[composerIntent.value] || INTENT_META.skill)

const intentRepoPickShow = computed(() => {
  if (!hasWorkflow.value || planSession.value) return false
  return composerIntent.value === 'employee' || composerIntent.value === 'mod'
})

/** Mod/employee：可收起侧栏说明，仅保留仓库跳转区 */
const intentGuideCollapsed = ref(true)

const showIntentGuide = computed(() => !intentRepoPickShow.value || !intentGuideCollapsed.value)

const catalogEmployeeRows = ref([])
const catalogModRows = ref([])
const pickEmployeeKey = ref('')
const pickModId = ref('')

const catalogEmployeesForPick = computed(() => catalogEmployeeRows.value)

const catalogModsForPick = computed(() =>
  (catalogModRows.value || []).map((r) => ({
    id: r.id,
    label: `${r.id}${r.manifest?.name ? ` · ${r.manifest.name}` : ''}`,
  })),
)

const pickedEmployeeRow = computed(() => {
  const k = (pickEmployeeKey.value || '').trim()
  if (!k) return null
  return catalogEmployeeRows.value.find((r) => r.k === k) || null
})

const pickedModRow = computed(() => {
  const id = (pickModId.value || '').trim()
  if (!id) return null
  return (catalogModRows.value || []).find((r) => String(r.id) === id) || null
})

const pickedModManifestVersion = computed(() => {
  const v = pickedModRow.value?.manifest?.version
  return typeof v === 'string' && v.trim() ? v.trim() : '?'
})

const pickedModManifestName = computed(() => {
  const n = pickedModRow.value?.manifest?.name
  return typeof n === 'string' && n.trim() ? n.trim() : ''
})

const pickedModManifestDescription = computed(() => {
  const d = pickedModRow.value?.manifest?.description
  return typeof d === 'string' ? d : ''
})

function truncateWorkbenchText(text, max = 280) {
  const s = typeof text === 'string' ? text.replace(/\s+/g, ' ').trim() : ''
  if (!s) return ''
  return s.length <= max ? s : `${s.slice(0, max)}…`
}

function releaseChannelLabel(ch) {
  const x = String(ch || 'stable').toLowerCase()
  return x === 'draft' ? '测试通道' : '正式通道'
}

async function loadDirectEmployeeOptions() {
  directEmployeeOptions.value = []
  if (!localStorage.getItem('modstore_token')) return
  const merged = new Map<string, DirectEmployeeOption>()
  try {
    const sqlRows = await api.listEmployees()
    for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
      const id = String((e as { id?: unknown })?.id ?? '').trim()
      if (!id) continue
      const name = String((e as { name?: unknown })?.name ?? id).trim() || id
      merged.set(id, { id, name, sourceLabel: '执行器' })
    }
  } catch {
    /* ignore */
  }
  try {
    const r = await api.listV1Packages('employee_pack', '', 120, 0)
    for (const p of r?.packages || []) {
      const id = String((p as { id?: unknown })?.id ?? '').trim()
      if (!id) continue
      const pkgName = String((p as { name?: unknown })?.name ?? id).trim() || id
      const existing = merged.get(id)
      if (existing) {
        const sl = existing.sourceLabel
        existing.sourceLabel = sl.includes('目录') ? sl : `${sl}·目录`
        if (pkgName && pkgName !== existing.name) existing.name = `${existing.name}（${pkgName}）`
        continue
      }
      merged.set(id, { id, name: pkgName, sourceLabel: '本地包' })
    }
  } catch {
    /* ignore */
  }
  try {
    const cat = await api.catalog('', 'employee_pack', 80, 0)
    for (const it of (cat as { items?: unknown[] })?.items || []) {
      const row = it as { pkg_id?: string; id?: string | number; name?: string }
      const id = String(row.pkg_id || row.id || '').trim()
      if (!id || !TABULAR_READ_EMPLOYEE_IDS.includes(id as (typeof TABULAR_READ_EMPLOYEE_IDS)[number])) continue
      const name = String(row.name || '').trim() || readEmployeeDisplayName(id)
      const existing = merged.get(id)
      if (existing) {
        existing.sourceLabel = existing.sourceLabel.includes('市场') ? existing.sourceLabel : `${existing.sourceLabel}·市场`
        if (name && name !== existing.name) existing.name = name
        continue
      }
      merged.set(id, { id, name, sourceLabel: 'AI 市场' })
    }
  } catch {
    /* ignore */
  }
  directEmployeeOptions.value = [...merged.values()].sort((a, b) =>
    String(a.name).localeCompare(String(b.name), 'zh-CN'),
  )
  const cur = String(directChatEmployeeId.value || '').trim()
  if (cur && !merged.has(cur)) {
    directChatEmployeeId.value = ''
    try {
      sessionStorage.removeItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
    } catch {
      /* ignore */
    }
  }
}

async function loadWorkbenchRepoPicks() {
  catalogEmployeeRows.value = []
  catalogModRows.value = []
  if (!localStorage.getItem('modstore_token')) return
  try {
    const r = await api.listV1Packages('employee_pack', '', 80, 0)
    const rows = []
    for (const p of r.packages || []) {
      const id = String(p.id || '').trim()
      const ver = String(p.version || '').trim()
      if (!id || !ver) continue
      const ch = String(p.release_channel || 'stable').toLowerCase()
      const displayName = String(p.name || id).trim() || id
      const description = typeof p.description === 'string' ? p.description : ''
      const industry = typeof p.industry === 'string' && p.industry.trim() ? p.industry.trim() : ''
      const artifact = String(p.artifact || 'employee_pack').toLowerCase()
      const probe = typeof p.probe_mod_id === 'string' && p.probe_mod_id.trim() ? p.probe_mod_id.trim() : ''
      rows.push({
        k: `${id}@${ver}`,
        id,
        ver,
        displayName,
        label: `${p.name || id} · ${ver}${ch === 'draft' ? '（测试）' : ''}`,
        description,
        industry,
        artifact,
        release_channel: ch,
        probe_mod_id: probe,
      })
    }
    catalogEmployeeRows.value = rows
  } catch {
    catalogEmployeeRows.value = []
  }
  try {
    const m = await api.listMods()
    catalogModRows.value = Array.isArray(m?.data) ? m.data : []
  } catch {
    catalogModRows.value = []
  }
  await loadDirectEmployeeOptions()
}

function goEditEmployeeFromPick() {
  if (!requireLoginForWorkbenchUse()) return
  const v = pickEmployeeKey.value
  if (!v) return
  const at = v.lastIndexOf('@')
  if (at <= 0) return
  const id = v.slice(0, at)
  const ver = v.slice(at + 1)
  router.push({ name: 'workbench-employee', query: { edit_pkg: id, edit_ver: ver } })
}

function goEditModFromPick() {
  if (!requireLoginForWorkbenchUse()) return
  const id = (pickModId.value || '').trim()
  if (!id) return
  router.push({ name: 'mod-authoring', params: { modId: id }, query: { mode: 'edit' } })
}

watch(composerIntent, (intent) => {
  pickEmployeeKey.value = ''
  pickModId.value = ''
  voiceSessionState.value.mode =
    intent === 'employee' ? 'employee' : intent === 'mod' ? 'mod' : 'skill'
})

/** 侧栏与输入脚「当前」主标题：{name} Skill 组 / Mod / AI 员工 */
const composerMainTitle = computed(() => {
  if (workflowLinkOffer.value?.workflowName) {
    return `${workflowLinkOffer.value.workflowName} Skill 组`
  }
  const ph = pendingHandoff.value
  if (isCanvasSkillIntent(ph?.intentKey)) {
    const n = (ph.workflowName || '').trim()
    if (n) return `${n} Skill 组`
  }
  if (ph?.intentKey === 'mod') {
    const n = (ph.suggestedModId || '').trim()
    if (n) return `${n} Mod`
  }
  if (ph?.intentKey === 'employee') {
    const d = (ph.description || '').trim().split('\n')[0].trim().slice(0, 36)
    if (d) return `${d} AI 员工`
  }
  const k = composerIntent.value
  if (k === 'mod') return '做 Mod'
  if (k === 'employee') return '做员工'
  return '生成 Skill 组'
})

const handoffDescLabel = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') return 'Mod 需求描述'
  if (k === 'employee') return '员工能力描述'
  return 'Skill 组描述'
})

const orchestrationButtonLabel = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') return '开始生成 Mod'
  if (k === 'employee') return '开始生成员工包'
  const files = pendingHandoff.value?.files
  if (isCanvasSkillIntent(k) && Array.isArray(files) && files.length > 0) {
    return '开始处理附件（AI 生成 Python 脚本）'
  }
  if (isCanvasSkillIntent(k)) return '开始生成 Skill 组并校验'
  return '开始创建并校验'
})

const orchestrationButtonPendingLabel = computed(() => {
  if (!finalizeLoading.value) return orchestrationButtonLabel.value
  if (orchPhase.value === 'estimating') return '估算用时…'
  return '执行中…'
})

const makeHasActiveTask = computed(() =>
  Boolean(
    planSession.value ||
      pendingHandoff.value ||
      workflowLinkOffer.value ||
      finalizeLoading.value ||
      makeCompletionResult.value ||
      orchestrationSession.value?.steps?.length,
  ),
)

const makeComposerRows = computed(() => {
  if (planSession.value?.phase === 'chat') return 2
  return makeHasActiveTask.value ? 1 : 4
})

const orchestrationProgress = computed(() =>
  computeOrchProgress(orchestrationSession.value?.steps),
)

const orchQualityReport = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return []
  const qr = (art as Record<string, unknown>).quality_report as Record<string, unknown> | unknown[] | undefined
  if (Array.isArray(qr)) return qr
  if (qr && typeof qr === 'object' && Array.isArray((qr as Record<string, unknown>).items)) {
    return (qr as Record<string, unknown>).items as Array<{ check?: string; ok?: boolean | null; note?: string; critical?: boolean }>
  }
  return []
})

const orchQualityMeta = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  const qr = (art as Record<string, unknown>).quality_report as Record<string, unknown> | undefined
  if (!qr || typeof qr !== 'object' || Array.isArray(qr)) return null
  return {
    score: qr.score as number | undefined,
    runnable: qr.runnable as boolean | undefined,
    criticalFailed: qr.critical_failed as boolean | undefined,
    pipelineLabel: String(qr.pipeline_label || ''),
  }
})

/** Phase A：vibecoding 轮次 / 黄金 parity / 领域冒烟（编排 artifact） */
const orchVibecodingMeta = computed(() => {
  const art = orchestrationSession.value?.artifact
  if (!art || typeof art !== 'object') return null
  const a = art as Record<string, unknown>
  const rt = a.runtime_generation as Record<string, unknown> | undefined
  const gc = a.golden_comparison as Record<string, unknown> | undefined
  const ds = a.domain_smoke as Record<string, unknown> | undefined
  if (!rt && !gc && !ds) return null
  return {
    source: rt ? String(rt.source || '') : '',
    round: rt?.round as number | undefined,
    generated: rt?.generated === true,
    parity: gc?.parity_score as number | undefined,
    goldenPassed: gc?.passed === true,
    smokeOk: ds?.ok as boolean | undefined,
    diffCount: Array.isArray(gc?.diff_items) ? (gc.diff_items as unknown[]).length : 0,
  }
})

/** 制作草稿执行中：紧邻按钮的可读状态，避免只看到「执行中…」误以为卡住 */
const handoffRunStatusLine = computed(() => {
  if (!finalizeLoading.value) return ''
  const s = orchestrationSession.value
  const steps = Array.isArray(s?.steps) ? s.steps : []
  const running = steps.find((x: { status?: string }) => x.status === 'running')
  if (running) {
    const lab = String(running.label || '编排').trim() || '编排'
    const msg = typeof running.message === 'string' && running.message.trim() ? ` — ${running.message.trim()}` : ''
    const sec = orchStepRunningSec(running)
    const elapsed = sec !== null && sec >= 5 ? `（已运行 ${formatWallClockSec(sec)}）` : ''
    return `进行中：${lab}${msg}${elapsed}`
  }
  if (steps.length) {
    const done = steps.filter((x: { status?: string }) => x.status === 'done').length
    const next = steps.find((x: { status?: string }) => x.status === 'pending')
    if (next && done < steps.length) {
      const nl = String(next.label || '下一步').trim() || '下一步'
      return `排队中：${nl}（已完成 ${done}/${steps.length}）`
    }
    return `编排进度：${done}/${steps.length} 步`
  }
  const st = typeof s?.status === 'string' ? s.status.trim() : ''
  if (st && st !== 'done' && st !== 'error') return `编排状态：${st}`
  return '已提交，正在连接编排服务并拉取步骤…'
})

function formatWallClockSec(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m >= 60) {
    const h = Math.floor(m / 60)
    const mm = m % 60
    return `${h}:${String(mm).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  }
  if (m === 0) return `${r}秒`
  return `${m}分${String(r).padStart(2, '0')}秒`
}

function stopOrchestrationElapsedTicker() {
  if (orchElapsedTimer != null) {
    clearInterval(orchElapsedTimer)
    orchElapsedTimer = null
  }
}

function startOrchestrationElapsedTicker() {
  stopOrchestrationElapsedTicker()
  orchElapsedTick.value = 0
  orchElapsedTimer = setInterval(() => {
    orchElapsedTick.value += 1
  }, 500)
}

const ORCH_ESTIMATE_SYSTEM = [
  '你是「工作台异步编排」的 wall-clock 耗时估算助手。用户即将启动一次服务端多步任务（可能含多次 LLM、写盘、工作流/沙箱等）。',
  '请只根据 intent、需求摘要与清单规模，推断从「开始执行」到「全部完成」的总秒数；不得照抄示例数字，须结合复杂度自行推理。',
  '只输出一个 JSON 对象，不要用 markdown 代码围栏，不要其它文字。',
  '字段：estimated_seconds（整数，通常 120～3600，极端不超过 7200），confidence（"low"|"medium"|"high"），one_line_reason（一句中文，≤80 字）。',
].join('')

function parseOrchestrationEtaFromLlmText(text) {
  let s = String(text || '').trim()
  if (!s) return { seconds: null, reason: '' }
  if (s.startsWith('```')) {
    s = s.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim()
  }
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start < 0 || end <= start) return { seconds: null, reason: '' }
  try {
    const o = JSON.parse(s.slice(start, end + 1))
    const n = Number(o.estimated_seconds)
    if (!Number.isFinite(n)) return { seconds: null, reason: String(o.one_line_reason || '').trim().slice(0, 120) }
    const sec = Math.round(Math.max(30, Math.min(n, 7200)))
    return {
      seconds: sec,
      reason: String(o.one_line_reason || '').trim().slice(0, 120),
    }
  } catch {
    return { seconds: null, reason: '' }
  }
}

/** 模型未返回 estimated_seconds 时，用清单规模与意图粗估总秒数，避免「预计 —」不可读 */
function fallbackOrchestrationSecondsEstimate(ctx: {
  intent: string
  checklistLen: number
  generateFrontend?: boolean
  employeeTarget?: string
  scriptFileCount?: number
}): number {
  let n = 150
  const cl = Math.max(0, Math.floor(Number(ctx.checklistLen) || 0))
  n += cl * 95
  const intent = String(ctx.intent || CANVAS_SKILL_INTENT)
  if (intent === 'mod') {
    n += 260
    if (ctx.generateFrontend) n += 480
  } else if (intent === 'employee') {
    n += 320
    if (String(ctx.employeeTarget || '').includes('pack_plus')) n += 260
  } else {
    n += 200
  }
  const sf = Math.max(0, Math.floor(Number(ctx.scriptFileCount) || 0))
  n += sf * 160
  return Math.round(Math.min(7200, Math.max(120, n)))
}

async function estimateOrchestrationSeconds(ctx) {
  try {
    const { provider, model } = await resolveChatProviderModel()
    const lines = [
      `intent=${ctx.intent}`,
      `execution_checklist 条数=${ctx.checklistLen}`,
      ctx.intent === 'mod' ? `generate_frontend=${ctx.generateFrontend}` : '',
      ctx.intent === 'employee' ? `employee_target=${ctx.employeeTarget || ''}` : '',
      typeof ctx.scriptFileCount === 'number' && ctx.scriptFileCount > 0
        ? `script_workflow 附件数=${ctx.scriptFileCount}`
        : '',
      '--- 需求摘要（截断） ---',
      ctx.brief.slice(0, 3500),
    ].filter(Boolean)
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: ORCH_ESTIMATE_SYSTEM },
      { role: 'user', content: lines.join('\n') },
    ], 256)
    return parseOrchestrationEtaFromLlmText(res?.content)
  } catch {
    return { seconds: null, reason: '' }
  }
}

const orchestrationEtaDisplay = computed(() => {
  if (!finalizeLoading.value) return '—'
  if (orchPhase.value === 'estimating') return '模型推算中…'
  orchElapsedTick.value
  let sec = orchestrationEtaSeconds.value
  const h = pendingHandoff.value
  if ((sec == null || !Number.isFinite(sec)) && orchPhase.value === 'running' && h) {
    const scriptFiles = isCanvasSkillIntent(h.intentKey) && Array.isArray(h.files) ? h.files : []
    sec = fallbackOrchestrationSecondsEstimate({
      intent: String(h.intentKey || CANVAS_SKILL_INTENT),
      checklistLen: Array.isArray(h.executionChecklist) ? h.executionChecklist.length : 0,
      generateFrontend: h.intentKey === 'mod' ? modFrontendEnabled.value : false,
      employeeTarget: h.intentKey === 'employee' ? String(h.employeeTarget || '').trim() : '',
      scriptFileCount: scriptFiles.length,
    })
  }
  if (sec == null || !Number.isFinite(sec)) {
    return orchestrationEtaReason.value
      ? `未算出数值（${orchestrationEtaReason.value}）`
      : '未算出数值'
  }
  const totalLabel = `总估约 ${formatWallClockSec(sec)}`
  const t0 = orchTimingStartMs.value
  if (t0 == null) return `${totalLabel}（即将计时）`
  const elapsed = (Date.now() - t0) / 1000
  const rem = sec - elapsed
  if (rem >= 20) return `${totalLabel} · 剩余约 ${formatWallClockSec(rem)}`
  if (rem >= 0) return `${totalLabel} · 收尾中`
  return `${totalLabel} · 已超过估算，仍在执行`
})

const orchestrationTimingTooltip = computed(() => {
  if (!finalizeLoading.value) return ''
  const r = String(orchestrationEtaReason.value || '').trim()
  return r || '总时长为模型推算或按步骤量粗估；剩余时间按总估与已用时间相减。'
})

const orchestrationElapsedDisplay = computed(() => {
  orchElapsedTick.value
  if (!finalizeLoading.value) return '—'
  if (orchPhase.value === 'estimating') return '—'
  const t0 = orchTimingStartMs.value
  if (t0 == null) return '—'
  return formatWallClockSec((Date.now() - t0) / 1000)
})

const canRunOrchestration = computed(() => {
  const h = pendingHandoff.value
  if (!h?.description?.trim()) return false
  if (isCanvasSkillIntent(h.intentKey)) return Boolean(h.workflowName?.trim())
  return true
})

const handoffFootNote = computed(() => {
  const k = pendingHandoff.value?.intentKey
  if (k === 'mod') {
    return '生成成功后进入 Mod 制作页。页面会区分“名片已生成”和“员工可工作”：未登记员工包、未绑定工作流或未真实执行都会列为缺口。'
  }
  if (k === 'employee') {
    const isRealSkill = pendingHandoff.value?.employeeTarget === 'pack_plus_workflow'
    if (isRealSkill) {
      return '员工包已生成真实 Python 脚本并注册为可执行 Skill，画布每个节点都对应已沙箱校验的代码；上架请到「员工制作」。'
    }
    return '员工包写入你的本地库；上架请到「员工制作」上传。商店执行器以已上架包为准。'
  }
  if (Array.isArray(pendingHandoff.value?.files) && pendingHandoff.value.files.length > 0) {
    return '已选择附件：将生成可复用的「脚本工作流」，成功后自动进入沙箱调试页；你可以继续上传同类 Excel 文件验证脚本输出。若要生成节点与连线的流程图，请先移除附件再提交。'
  }
  return '创建并校验成功后进入画布编辑 Skill 组；尚无节点时跳过拓扑沙盒。'
})

const handoffAssetNote = computed(() => {
  const files = pendingHandoff.value?.files
  if (!Array.isArray(files) || !files.length) return ''
  return `已附带 ${files.length} 个资产`
})

const hasRepo = computed(() => router.hasRoute('workbench-repository'))
const hasWorkflow = computed(() => router.hasRoute('workbench-workflow'))
/** Teleport 到 body；keep-alive 下切到统一工作台等路由时首页仍缓存，需按当前路由隐藏 FAB */
const showDirectTierFab = computed(() => {
  if (!hasWorkflow.value) return false
  const n = String(route.name || '')
  return n === 'home' || n === 'workbench-home'
})
const hasScriptWorkflowRoute = computed(() => router.hasRoute('script-workflow-new'))
const hasEmployee = computed(() => router.hasRoute('workbench-employee'))
const hasPlans = computed(() => router.hasRoute('plans'))

/** 一档有聊天记录时默认锁定挡位切换，需用户显式解锁（同一会话内保持） */
const gearNavUserUnlocked = ref(false)
const gearNavHardLocked = computed(
  () => Boolean(hasWorkflow.value && directMessages.value.length && !gearNavUserUnlocked.value),
)

function unlockGearNav() {
  gearNavUserUnlocked.value = true
}

watch(activeConversationId, () => {
  gearNavUserUnlocked.value = false
})

watch(
  () => wbSidebar.activeConversationId,
  (id) => {
    if (!id) return
    if (id === activeConversationId.value) {
      const fresh = loadConversations().find((c) => c.id === id)
      if (directMessages.value.length === 0 && (fresh?.messages?.length ?? 0) > 0) {
        setActiveConversation(id)
      }
      return
    }
    setActiveConversation(id)
  },
)

watch(
  () => wbSidebar.conversations.map((c) => `${c.id}:${c.updatedAt}:${c.messages?.length ?? 0}`).join('|'),
  () => {
    if (syncingConvToSidebar) return
    const loaded = loadConversations()
    const aid = wbSidebar.activeConversationId || loadActiveId() || activeConversationId.value
    if (aid) {
      conversations.value = mergeConversationsForPick(
        conversations.value,
        loaded,
        aid,
        directMessages.value.length,
      )
    } else {
      conversations.value = loaded
    }
    if (aid && loaded.some((c) => c.id === aid)) {
      activeConversationId.value = aid
    } else if (loaded.length) {
      activeConversationId.value = loaded[0].id
      saveActiveId(activeConversationId.value)
      wbSidebar.setActiveConversationId(activeConversationId.value)
    }
  },
)

watch(
  () => directMessages.value.length,
  (len, prev) => {
    if (!len) {
      gearNavUserUnlocked.value = false
      return
    }
    /* 从「无消息」到「有消息」时强制重新解锁；避免空会话里提前点解锁绕过 */
    if (!prev) gearNavUserUnlocked.value = false
  },
)

const greetingLine = computed(() => {
  const n = displayName.value.trim()
  if (!n) return ''
  return `你好，${n}`
})

const placeholder = computed(() => {
  if (composerIntent.value === 'mod') return '描述你想做的 Mod…'
  if (composerIntent.value === 'employee') return '描述员工职责…'
  return '描述你的想法…'
})

/** 「做」模式主输入：无规划或与助手对话时合并到底栏，避免双文本框 */
const makeComposerInput = computed({
  get() {
    if (planSession.value?.phase === 'chat') return planReplyDraft.value
    return draft.value
  },
  set(v: string) {
    if (planSession.value?.phase === 'chat') {
      planReplyDraft.value = v
    } else {
      draft.value = v
    }
  },
})

const makeComposerInputLabel = computed(() =>
  planSession.value?.phase === 'chat' ? '补充或追问' : '描述想法',
)

const makeComposerPlaceholder = computed(() =>
  planSession.value?.phase === 'chat' ? '补充…' : placeholder.value,
)

const composerSendDisabled = computed(() => {
  if (knowledgeUploading.value) return true
  const ps = planSession.value
  if (ps?.phase === 'chat') {
    return ps.loading || !String(planReplyDraft.value || '').trim()
  }
  if (ps) return true
  if (!hasWorkflow.value) return true
  const text = String(draft.value || '').trim()
  const uploading = directAttachedFiles.value.some((f: any) => f.status === 'uploading')
  if (uploading) return true
  return !text && !directAttachedFiles.value.length
})

const currentLlmBlock = computed(() => {
  if (!llmCatalog.value?.providers) return null
  return llmCatalog.value.providers.find((p) => p.provider === selectedProvider.value) || null
})

const currentProviderLabel = computed(() => {
  const list = llmCatalog.value?.providers
  if (!Array.isArray(list)) return '厂商'
  const b = list.find((p) => p.provider === selectedProvider.value)
  const lab = typeof b?.label === 'string' ? b.label.trim() : ''
  const id = typeof b?.provider === 'string' ? b.provider.trim() : ''
  return lab || id || '厂商'
})

const modelModeHint = computed(() => {
  if (modelMode.value === 'auto') {
    return 'Auto：系统将根据任务自动选择合适模型'
  }
  if (selectedModel.value) {
    return `自选：${currentProviderLabel.value} · ${selectedModel.value}`
  }
  return '自选：请选择厂商与模型'
})

const modelPickerEnabled = computed(() => {
  const block = currentLlmBlock.value
  return Boolean(block && Array.isArray(block.models) && block.models.length)
})

function categoryLabel(cat) {
  return llmCatalog.value?.category_labels?.[cat] || cat
}

function modelsForWorkbenchCategory(cat) {
  const block = currentLlmBlock.value
  const detailed = block?.models_detailed
  if (detailed && detailed.length) {
    return detailed.filter((r) => r.category === cat)
  }
  if (cat === 'llm' && block?.models?.length) {
    return block.models.map((id) => ({ id, category: 'llm' }))
  }
  return []
}

function syncManualSelectionFromPreferences() {
  const res = llmCatalog.value
  if (!res?.providers?.length) return
  const pref = res.preferences || {}
  let p = pref.provider || 'openai'
  if (!res.providers.some((x) => x.provider === p)) {
    p = res.providers[0]?.provider || 'openai'
  }
  selectedProvider.value = p
  const block = res.providers.find((x) => x.provider === p)
  const mids = block?.models || []
  let m = pref.model || ''
  if (!m || !mids.includes(m)) m = mids[0] || ''
  selectedModel.value = m
}

async function loadLlmCatalogForWorkbench() {
  if (!localStorage.getItem('modstore_token')) return
  llmCatalogLoading.value = true
  llmCatalogError.value = ''
  try {
    const res = await api.llmCatalog(false)
    llmCatalog.value = res
    syncManualSelectionFromPreferences()
  } catch (e) {
    llmCatalog.value = null
    llmCatalogError.value = e.message || String(e)
  } finally {
    llmCatalogLoading.value = false
  }
}

watch(modelMode, (mode) => {
  llmDdOpen.value = null
  if (mode === 'manual') syncManualSelectionFromPreferences()
})

function onWorkbenchProviderChange() {
  const block = currentLlmBlock.value
  const mids = block?.models || []
  selectedModel.value = mids[0] || ''
}

function toggleLlmDd(which) {
  llmDdOpen.value = llmDdOpen.value === which ? null : which
}

function pickProvider(p) {
  if (typeof p !== 'string' || !p) return
  selectedProvider.value = p
  onWorkbenchProviderChange()
  llmDdOpen.value = null
}

function pickModel(id) {
  if (typeof id !== 'string' || !id) return
  selectedModel.value = id
  llmDdOpen.value = null
}

function onLlmDocPointerDown(ev) {
  if (!llmDdOpen.value) return
  const t = ev.target
  if (t && typeof t.closest === 'function' && t.closest('.wb-llm-dd')) return
  llmDdOpen.value = null
}

function onLlmEscape(ev) {
  if (ev.key === 'Escape') llmDdOpen.value = null
}

async function retryOrchStep(_st: any) {
  const sid = String(orchestrationSessionId.value || '').trim()
  if (!sid) return
  try {
    const res = await api.workbenchRetrySession(sid)
    if (res?.session_id) {
      orchestrationSessionId.value = res.session_id
      pollStop.value = false
      if (orchPhase.value !== 'estimating') {
        orchPhase.value = 'running'
        if (!orchTimingStartMs.value) orchTimingStartMs.value = Date.now()
        startOrchestrationElapsedTicker()
      }
      const final = await pollWorkbenchSession(res.session_id)
      if (final && final.status === 'error') {
        finalizeError.value = final.error || '编排失败'
      }
    }
  } catch (e: any) {
    finalizeError.value = String(e?.message || e || '重试失败')
  }
}

function orchStepClass(st) {
  return {
    'wb-step--done': st.status === 'done',
    'wb-step--running': st.status === 'running',
    'wb-step--error': st.status === 'error',
    'wb-step--pending': st.status === 'pending',
    'wb-step--skipped': st.status === 'skipped',
  }
}

/** 返回某步骤已运行的秒数（仅 running 状态 + 有 started_at 时），null 表示不展示。
 *  orchElapsedTick 作为响应式依赖使其每 0.5 秒刷新一次。*/
function orchStepRunningSec(st) {
  orchElapsedTick.value // 依赖订阅，使每次 tick 重新计算
  if (st.status !== 'running' || !st.started_at) return null
  const t0 = new Date(st.started_at).getTime()
  if (!Number.isFinite(t0)) return null
  return Math.max(0, Math.floor((Date.now() - t0) / 1000))
}

/** 跟踪各步骤最近一次 message 变化时间，用于「响应较慢」提示（B3）。*/
const _stepLastMsgChange: Record<string, { msg: string; ts: number }> = {}

function orchStepSlowHint(st) {
  orchElapsedTick.value // 响应式订阅
  if (st.status !== 'running') return false
  const sec = orchStepRunningSec(st)
  if (sec === null || sec < 60) return false
  const tracked = _stepLastMsgChange[st.id]
  if (!tracked) return true // 从未记录过，说明消息一直没来
  return (Date.now() - tracked.ts) >= 30000
}

/** 每次轮询后调用，更新 message 变化时间戳。 */
function _trackStepMessages(steps: Array<{ id: string; message?: any }>) {
  for (const st of steps || []) {
    const cur = typeof st.message === 'object' && st.message
      ? String(st.message.summary || JSON.stringify(st.message))
      : String(st.message || '')
    const prev = _stepLastMsgChange[st.id]
    if (!prev || prev.msg !== cur) {
      _stepLastMsgChange[st.id] = { msg: cur, ts: Date.now() }
    }
  }
}

// ---------------------------------------------------------------- AgentLoop v2 message helpers

/** Returns the display summary string from a step's message (str or dict). */
function stepMsgSummary(st: any): string {
  const msg = st?.message
  if (!msg) return ''
  if (typeof msg === 'string') return msg
  if (typeof msg === 'object') return String(msg.summary || '')
  return ''
}

/** Returns the current tool name from a structured message, or empty string. */
function stepMsgCurrentTool(st: any): string {
  const msg = st?.message
  if (!msg || typeof msg !== 'object') return ''
  return String(msg.current_tool || '')
}

/** Returns the todo list from a structured message, or empty array. */
function stepMsgTodos(st: any): Array<{ id: string; content: string; status: string }> {
  const msg = st?.message
  if (!msg || typeof msg !== 'object') return []
  const todos = msg.todos
  if (!Array.isArray(todos)) return []
  return todos.filter((t: any) => t && typeof t === 'object')
}

/** Returns true if the structured message indicates a slow-model hint. */
function stepMsgSlowHint(st: any): boolean {
  const msg = st?.message
  if (!msg || typeof msg !== 'object') return false
  return Boolean(msg.slow_hint)
}

function serializablePlanSession(ps) {
  if (!ps || typeof ps !== 'object') return null
  return {
    ...ps,
    files: Array.isArray(ps.files)
      ? ps.files.map((f) => ({
          name: String(f?.name || ''),
          size: Number(f?.size || 0),
          type: String(f?.type || ''),
          cachedOnly: true,
        }))
      : [],
  }
}

function restorePlanSession(ps) {
  if (!ps || typeof ps !== 'object') return null
  const out = {
    ...ps,
    files: Array.isArray(ps.files) ? ps.files : [],
    messages: Array.isArray(ps.messages) ? ps.messages : [],
    checklistLines: Array.isArray(ps.checklistLines) ? ps.checklistLines : [],
  }
  if (out.loading) {
    out.loading = false
    out.planError =
      out.planError ||
      '页面切换前的规划请求已中断；已恢复当前进度，你可以继续补充或重新触发本步骤。'
  }
  return out
}

function serializablePendingHandoff(h) {
  if (!h || typeof h !== 'object') return null
  return {
    ...h,
    files: Array.isArray(h.files)
      ? h.files.map((f) => ({
          name: String(f?.name || ''),
          size: Number(f?.size || 0),
          type: String(f?.type || ''),
          cachedOnly: true,
        }))
      : [],
    planningMessages: Array.isArray(h.planningMessages)
      ? h.planningMessages.map((m) => ({ role: m.role, content: m.content }))
      : [],
    executionChecklist: Array.isArray(h.executionChecklist) ? [...h.executionChecklist] : [],
    sourceDocuments: Array.isArray(h.sourceDocuments) ? [...h.sourceDocuments] : [],
  }
}

function restorePendingHandoff(h) {
  if (!h || typeof h !== 'object') return null
  return {
    ...h,
    files: Array.isArray(h.files) ? h.files : [],
    planningMessages: Array.isArray(h.planningMessages) ? h.planningMessages : [],
    executionChecklist: Array.isArray(h.executionChecklist) ? h.executionChecklist : [],
    sourceDocuments: Array.isArray(h.sourceDocuments) ? h.sourceDocuments : [],
  }
}

function makeHasCachedProgress() {
  return Boolean(
    planSession.value ||
      pendingHandoff.value ||
      workflowLinkOffer.value ||
      finalizeLoading.value ||
      finalizeError.value ||
      orchestrationSession.value?.steps?.length ||
      orchestrationSessionId.value ||
      voiceMessages.value.length,
  )
}

function cacheMakeProgress() {
  try {
    if (!makeHasCachedProgress()) {
      sessionStorage.removeItem(MAKE_PROGRESS_CACHE_KEY)
      return
    }
    sessionStorage.setItem(
      MAKE_PROGRESS_CACHE_KEY,
      JSON.stringify({
        savedAt: Date.now(),
        activeGear: activeGear.value,
        draft: draft.value,
        composerIntent: composerIntent.value,
        modFrontendEnabled: modFrontendEnabled.value,
        planSession: serializablePlanSession(planSession.value),
        planReplyDraft: planReplyDraft.value,
        planOptionSelections: planOptionSelections.value,
        planOptionOtherText: { ...planOptionOtherText },
        pendingHandoff: serializablePendingHandoff(pendingHandoff.value),
        finalizeLoading: finalizeLoading.value,
        finalizeError: finalizeError.value,
        orchestrationSession: orchestrationSession.value,
        orchestrationSessionId: orchestrationSessionId.value,
        orchPhase: orchPhase.value,
        orchestrationEtaSeconds: orchestrationEtaSeconds.value,
        orchestrationEtaReason: orchestrationEtaReason.value,
        orchTimingStartMs: orchTimingStartMs.value,
        workflowLinkOffer: workflowLinkOffer.value,
        voiceMessages: voiceMessages.value,
        voiceChatPhase: voiceChatPhase.value,
        voiceWorkPhase: voiceWorkPhase.value,
        voiceInjectQueue: voiceInjectQueue.value,
      }),
    )
  } catch {
    /* ignore */
  }
}

function clearMakeProgressCache() {
  try {
    sessionStorage.removeItem(MAKE_PROGRESS_CACHE_KEY)
  } catch {
    /* ignore */
  }
}

function restoreMakeProgressCache() {
  try {
    const raw = sessionStorage.getItem(MAKE_PROGRESS_CACHE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw)
    if (!cached || Date.now() - Number(cached.savedAt || 0) > MAKE_PROGRESS_CACHE_TTL_MS) {
      clearMakeProgressCache()
      return
    }
    if (cached.activeGear && ['direct', 'make', 'voice'].includes(cached.activeGear)) {
      activeGear.value = cached.activeGear
    }
    if (typeof cached.draft === 'string' && !draft.value.trim()) draft.value = cached.draft
    if (cached.composerIntent === 'workflow') {
      composerIntent.value = CANVAS_SKILL_INTENT
    } else if (INTENT_META[cached.composerIntent]) {
      composerIntent.value = cached.composerIntent
    }
    if (typeof cached.modFrontendEnabled === 'boolean') {
      modFrontendEnabled.value = cached.modFrontendEnabled
    }
    planSession.value = restorePlanSession(cached.planSession)
    planReplyDraft.value = typeof cached.planReplyDraft === 'string' ? cached.planReplyDraft : ''
    planOptionSelections.value =
      cached.planOptionSelections && typeof cached.planOptionSelections === 'object'
        ? cached.planOptionSelections
        : {}
    clearPlanOptionOtherText()
    if (cached.planOptionOtherText && typeof cached.planOptionOtherText === 'object') {
      for (const [k, v] of Object.entries(cached.planOptionOtherText)) {
        planOptionOtherText[k] = String(v || '')
      }
    }
    pendingHandoff.value = restorePendingHandoff(cached.pendingHandoff)
    finalizeLoading.value = Boolean(cached.finalizeLoading)
    finalizeError.value = typeof cached.finalizeError === 'string' ? cached.finalizeError : ''
    orchestrationSession.value = cached.orchestrationSession || null
    orchestrationSessionId.value = String(cached.orchestrationSessionId || '').trim()
    orchPhase.value = cached.orchPhase || (finalizeLoading.value ? 'running' : 'idle')
    orchestrationEtaSeconds.value =
      cached.orchestrationEtaSeconds == null ? null : Number(cached.orchestrationEtaSeconds)
    orchestrationEtaReason.value =
      typeof cached.orchestrationEtaReason === 'string' ? cached.orchestrationEtaReason : ''
    orchTimingStartMs.value =
      cached.orchTimingStartMs == null ? null : Number(cached.orchTimingStartMs)
    workflowLinkOffer.value = cached.workflowLinkOffer || null
    if (Array.isArray(cached.voiceMessages)) voiceMessages.value = cached.voiceMessages
    if (cached.voiceChatPhase) voiceChatPhase.value = cached.voiceChatPhase
    if (cached.voiceInjectQueue) voiceInjectQueue.value = cached.voiceInjectQueue
    syncVoiceWorkPhase()
  } catch {
    clearMakeProgressCache()
  }
}


function applyInlineVoiceText(suffix: string) {
  if (!inlineVoiceTarget) return
  const value = inlineVoicePrefix + suffix
  if (inlineVoiceTarget === 'direct') directDraft.value = value
  else makeComposerInput.value = value
}

function stopInlineVoiceCapture() {
  inlineVoiceTarget = null
  inlineVoicePrefix = ''
}

function clearInlineVoicePermissionHint(target: 'direct' | 'make') {
  if (target === 'direct') directVoicePermissionHint.value = ''
  else makeVoicePermissionHint.value = ''
}

function setInlineVoicePermissionHint(target: 'direct' | 'make', msg: string) {
  const text = String(msg || '').trim()
  if (!text) return
  if (target === 'direct') {
    directVoicePermissionHint.value = text
    directError.value = text
  } else {
    makeVoicePermissionHint.value = text
  }
  showAppToast(text, { variant: 'error' })
}

function cancelInlineVoice(target: 'direct' | 'make', opts?: { silent?: boolean }) {
  const wasRecording = target === 'direct' ? directVoiceListening.value : makeVoiceListening.value
  const wasRecognizing = target === 'direct' ? directVoiceRecognizing.value : makeVoiceRecognizing.value
  if (!wasRecording && !wasRecognizing && inlineVoiceTarget !== target) return

  inlineAsr.abort()
  inlineHoldActive = false
  inlineHoldPointerId = -1
  inlineHoldCancelIntent = false
  inlineHoldStartY = 0

  if (target === 'direct') {
    directVoiceListening.value = false
    directVoiceRecognizing.value = false
    directVoiceAudioLevel.value = 0
    if (inlineVoiceTarget === 'direct') directDraft.value = inlineVoicePrefix
  } else {
    makeVoiceListening.value = false
    makeVoiceRecognizing.value = false
    if (inlineVoiceTarget === 'make') makeComposerInput.value = inlineVoicePrefix
  }
  stopInlineVoiceCapture()
  if (!opts?.silent && (wasRecording || wasRecognizing)) {
    showAppToast('已取消语音输入', { variant: 'info' })
  }
}

async function startInlineVoice(target: 'direct' | 'make', opts?: { ptt?: boolean }) {
  if (target === 'direct' && (directVoiceListening.value || directVoiceRecognizing.value)) return
  if (target === 'make' && (makeVoiceListening.value || makeVoiceRecognizing.value)) return
  if (!localStorage.getItem('modstore_token')) {
    const msg = '请先登录后再使用语音输入。'
    if (target === 'direct') directError.value = msg
    else window.alert(msg)
    return
  }
  if (voiceListening.value) resetVoiceCaptureUi()
  inlineAsr.abort()
  clearInlineVoicePermissionHint(target)
  inlineVoiceTarget = target
  if (opts?.ptt) {
    inlineVoicePrefix = ''
    if (target === 'direct') directDraft.value = ''
    else makeComposerInput.value = ''
  } else {
    inlineVoicePrefix = target === 'direct' ? directDraft.value : makeComposerInput.value
  }
  if (target === 'direct') {
    directVoiceListening.value = true
    directVoiceRecognizing.value = false
    directError.value = ''
  } else {
    makeVoiceListening.value = true
    makeVoiceRecognizing.value = false
  }
  await inlineAsr.startListening(
    (r) => {
      if (r.text) applyInlineVoiceText(r.text)
    },
    (msg) => {
      const text = String(msg || '语音输入失败')
      if (isMicPermissionError(text)) setInlineVoicePermissionHint(target, text)
      else showAppToast(text, { variant: 'error' })
      if (target === 'direct') {
        if (!isMicPermissionError(text)) directError.value = text
        directVoiceListening.value = false
        directVoiceRecognizing.value = false
      } else {
        makeVoiceListening.value = false
        makeVoiceRecognizing.value = false
      }
      stopInlineVoiceCapture()
    },
    (level) => {
      if (target === 'direct') directVoiceAudioLevel.value = level
    },
  )
}

async function stopInlineVoice(target: 'direct' | 'make'): Promise<string> {
  if (target === 'direct') {
    directVoiceListening.value = false
    directVoiceRecognizing.value = true
  } else {
    makeVoiceListening.value = false
    makeVoiceRecognizing.value = true
  }
  directVoiceAudioLevel.value = 0
  let finalText = ''
  try {
    const text = await inlineAsr.stopListening()
    finalText = text.trim()
    if (finalText && inlineVoiceTarget === target) {
      applyInlineVoiceText(finalText)
    } else if (!finalText) {
      finalText = (target === 'direct' ? directDraft.value : makeComposerInput.value).trim()
    }
  } finally {
    if (target === 'direct') directVoiceRecognizing.value = false
    else makeVoiceRecognizing.value = false
  }
  stopInlineVoiceCapture()
  return finalText
}

async function finishInlineHoldAndSend(target: 'direct' | 'make') {
  const finalText = (await stopInlineVoice(target)).trim()
  if (!finalText) {
    const msg = '未识别到文字，请按住说话后再松手发送。'
    if (target === 'direct') directError.value = msg
    else window.alert(msg)
    return
  }
  if (target === 'direct') {
    await sendDirectChat(finalText)
  } else {
    makeComposerInput.value = finalText
    await onComposerSendClick()
  }
}

function onInlineHoldStart(target: 'direct' | 'make', e: PointerEvent) {
  if (inlineHoldActive) return
  if (target === 'direct' && directLoading.value) return
  inlineHoldActive = true
  inlineHoldCancelIntent = false
  inlineHoldStartY = e.clientY
  inlineHoldPointerId = e.pointerId
  try {
    (e.currentTarget as HTMLElement)?.setPointerCapture(e.pointerId)
  } catch { /* ignore */ }
  void startInlineVoice(target, { ptt: true })
}

function onInlineHoldMove(e: PointerEvent) {
  if (!inlineHoldActive) return
  if (inlineHoldPointerId >= 0 && e.pointerId !== inlineHoldPointerId) return
  inlineHoldCancelIntent = inlineHoldStartY - e.clientY > 56
}

async function onInlineHoldEnd(target: 'direct' | 'make', e?: PointerEvent) {
  if (!inlineHoldActive) return
  if (e && inlineHoldPointerId >= 0 && e.pointerId !== inlineHoldPointerId) return
  const cancel = inlineHoldCancelIntent
  inlineHoldActive = false
  inlineHoldPointerId = -1
  inlineHoldCancelIntent = false
  inlineHoldStartY = 0
  if (cancel) {
    cancelInlineVoice(target, { silent: true })
    showAppToast('已取消', { variant: 'info' })
    return
  }
  await finishInlineHoldAndSend(target)
}

function onDirectVoicePointerDown(e: PointerEvent) {
  if (wbNav.isMobile) {
    onInlineHoldStart('direct', e)
    return
  }
  voiceBtnLongPressStart()
}

function onDirectVoicePointerMove(e: PointerEvent) {
  if (wbNav.isMobile) onInlineHoldMove(e)
}

function onDirectVoicePointerUp(e: PointerEvent) {
  if (wbNav.isMobile) {
    void onInlineHoldEnd('direct', e)
    return
  }
  voiceBtnLongPressCancel()
}

function onDirectVoiceClick() {
  if (wbNav.isMobile) return
  toggleDirectVoice()
}

function startDirectVoice() {
  startInlineVoice('direct')
}

function stopDirectVoice() {
  void stopInlineVoice('direct')
}

function toggleDirectVoice() {
  if (voiceBtnLongPressFired) {
    voiceBtnLongPressFired = false
    return
  }
  if (directVoiceRecognizing.value) {
    cancelInlineVoice('direct')
    return
  }
  if (directVoiceListening.value) {
    void stopDirectVoice()
    return
  }
  void startDirectVoice()
}

let voiceBtnLongPressTimer: ReturnType<typeof setTimeout> | null = null
let voiceBtnLongPressFired = false

function voiceBtnLongPressStart() {
  voiceBtnLongPressFired = false
  voiceBtnLongPressTimer = setTimeout(() => {
    voiceBtnLongPressFired = true
    requestMicInUserGesture()
    void unlockVoiceAudioPlayback()
    wbSidebar.activeMode = 'voice'
  }, 600)
}

function voiceBtnLongPressCancel() {
  if (voiceBtnLongPressTimer) {
    clearTimeout(voiceBtnLongPressTimer)
    voiceBtnLongPressTimer = null
  }
}

function startMakeVoice() {
  startInlineVoice('make')
}

function stopMakeVoice() {
  void stopInlineVoice('make')
}

function toggleMakeVoice() {
  if (makeVoiceRecognizing.value) {
    cancelInlineVoice('make')
    return
  }
  if (makeVoiceListening.value) {
    void stopMakeVoice()
    return
  }
  void startMakeVoice()
}

function onWbOpenSettings() {
  personalSettingsOpen.value = true
}

function onWbNewChat() {
  newConversationHandler()
}

function onWbPickConversation(e: Event) {
  const detail = (e as CustomEvent<{ id?: string }>).detail
  const id = typeof detail?.id === 'string' ? detail.id.trim() : ''
  if (id) setActiveConversation(id)
}

onMounted(async () => {
  butlerTrayStore.registerActions({
    removeAttachment: (id) => void removeDirectAttachedFile(id),
    removeGenerated: removeDirectGeneratedFile,
    downloadGenerated: (f) => void downloadGeneratedOutput(f),
  })
  setTimeout(() => {
    directBoxEnter.value = false
    composerPanelEnter.value = false
    contentEnter.value = false
  }, 30)
  document.addEventListener('pointerdown', onLlmDocPointerDown, true)
  window.addEventListener('wb-new-chat', onWbNewChat)
  window.addEventListener('wb-pick-conversation', onWbPickConversation)
  window.addEventListener('wb-open-settings', onWbOpenSettings)
  window.addEventListener('keydown', onLlmEscape)
  try {
    const pendingDraft = sessionStorage.getItem('workbench_home_pending_draft')
    const pendingIntent = sessionStorage.getItem('workbench_home_pending_intent')
    if (pendingDraft && !draft.value.trim()) draft.value = pendingDraft
    if (pendingIntent && INTENT_META[pendingIntent]) {
      composerIntent.value = pendingIntent === 'workflow' ? CANVAS_SKILL_INTENT : pendingIntent
    }
    sessionStorage.removeItem('workbench_home_pending_draft')
    sessionStorage.removeItem('workbench_home_pending_intent')
  } catch {
    /* ignore */
  }
  restoreMakeProgressCache()
  try {
    const emp = sessionStorage.getItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
    if (emp && emp.trim()) directChatEmployeeId.value = emp.trim()
  } catch {
    /* ignore */
  }
  try {
    const raw = sessionStorage.getItem(WB_DIRECT_WEB_SEARCH_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { enabled?: boolean; queryDraft?: string }
      if (typeof parsed.enabled === 'boolean') directWebSearchEnabled.value = parsed.enabled
    }
  } catch {
    /* ignore */
  }
  try {
    const rawImg = sessionStorage.getItem(WB_DIRECT_IMAGE_GEN_KEY)
    if (rawImg) {
      const p = JSON.parse(rawImg) as {
        enabled?: boolean
        size?: string
        style?: string
        count?: number
      }
      if (typeof p.enabled === 'boolean') directImageGenEnabled.value = p.enabled
      if (p.size) directImageSize.value = p.size
      if (p.style) directImageStyle.value = p.style
      if (typeof p.count === 'number') directImageCount.value = p.count
    }
    const rawVid = sessionStorage.getItem(WB_DIRECT_VIDEO_GEN_KEY)
    if (rawVid) {
      const p = JSON.parse(rawVid) as {
        enabled?: boolean
        aspect?: string
        durationSec?: number
      }
      if (typeof p.enabled === 'boolean') directVideoGenEnabled.value = p.enabled
      if (p.aspect) directVideoAspect.value = p.aspect
      if (typeof p.durationSec === 'number') directVideoDurationSec.value = p.durationSec
    }
    if (directImageGenEnabled.value && directVideoGenEnabled.value) {
      directVideoGenEnabled.value = false
    }
  } catch {
    /* ignore */
  }
  /* 须在首个 await 之前完成：否则 keep-alive 下 onActivated 可能先于 bots/会话加载执行，客服深链会漏处理 */
  try {
    refreshAllBots()
    activeBotId.value = loadActiveBotId() || ''
  } catch {
    /* ignore */
  }
  try {
    conversations.value = loadConversations()
    const storedActive = loadActiveId()
    if (storedActive && conversations.value.some((c) => c.id === storedActive)) {
      activeConversationId.value = storedActive
    } else if (conversations.value.length) {
      activeConversationId.value = conversations.value[0].id
      saveActiveId(activeConversationId.value)
    }
    wbSidebar.setConversations(conversations.value)
    if (activeConversationId.value) {
      wbSidebar.setActiveConversationId(activeConversationId.value)
    }
  } catch {
    /* ignore */
  }
  try {
    applyCustomerServiceRouteContext()
  } catch {
    /* ignore */
  }

  if (getAccessToken()) {
    try {
      const me = await api.me()
      if (me && typeof me === 'object' && me.ok !== false && me.success !== false) {
        const u = typeof me.username === 'string' ? me.username.trim() : ''
        const e = typeof me.email === 'string' ? me.email.trim() : ''
        displayName.value = u || (e ? e.split('@')[0] || e : '')
      } else {
        displayName.value = ''
      }
    } catch {
      displayName.value = ''
    }
  }
  await loadLlmCatalogForWorkbench()
  await loadWorkbenchRepoPicks()
  await loadKnowledgeDocuments()

  try {
    personalSettings.value = loadPersonalSettings()
    applyThemeToDocument(personalSettings.value.theme)
    const t = personalSettings.value.theme
    currentThemeIsLight.value = t === 'light' || (t === 'auto' && window.matchMedia?.('(prefers-color-scheme: light)').matches)
  } catch {
    /* ignore */
  }
  void resumeCachedOrchestration()
})

onActivated(() => {
  window.addEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  try {
    const loaded = loadConversations()
    const aid = wbSidebar.activeConversationId || loadActiveId() || activeConversationId.value
    if (aid) {
      conversations.value = mergeConversationsForPick(
        conversations.value,
        loaded,
        aid,
        directMessages.value.length,
      )
      if (loaded.some((c) => c.id === aid)) {
        setActiveConversation(aid)
      }
    } else {
      conversations.value = loaded
    }
  } catch {
    /* ignore */
  }
  try {
    applyCustomerServiceRouteContext()
  } catch {
    /* ignore */
  }
  try {
    applyWbGearFromRoute()
  } catch {
    /* ignore */
  }
})

function applySidebarModeSideEffects(mode: 'direct' | 'make' | 'voice') {
  if (mode === 'voice') {
    enablePlatformChatMode()
    return
  }
  if (mode === 'direct') {
    voiceCasualChatMode.value = false
    platformChatMode.value = false
    return
  }
  if (mode === 'make') {
    if (readPlatformChatModePreference()) {
      enablePlatformChatMode()
      directBoxEnter.value = false
    } else {
      disablePlatformChatMode()
    }
  }
}

function handleModeSwitchFromSidebar(e: Event) {
  const mode = (e as CustomEvent).detail as 'direct' | 'make' | 'voice'
  if (!mode) return
  if (mode !== 'voice' && mode !== 'make') {
    if (planSession.value) planSession.value = null
    if (pendingHandoff.value) pendingHandoff.value = null
  }
  if (mode === 'direct') {
    composerIntent.value = CANVAS_SKILL_INTENT
  }
  applySidebarModeSideEffects(mode)
  composerPanelEnter.value = true
  contentEnter.value = true
  directBoxEnter.value = true
  titleEnterDone.value = true
  wbSidebar.setActiveMode(mode)
  activeGear.value = mode
  setTimeout(() => {
    composerPanelEnter.value = false
    titleEnterDone.value = false
    contentEnter.value = false
    // 「做」+ 平台闲聊也复用 .wb-direct-box，须结束 enter 态，否则 opacity:0 看不见输入框
    directBoxEnter.value = false
  }, 30)
}

function applyWbGearFromRoute() {
  const gear = parseWbGearQuery(route.query.wbGear)
  if (!gear) return
  handleModeSwitchFromSidebar(new CustomEvent('wb-mode-switch', { detail: gear }))
}

watch(
  () => route.query.wbGear,
  () => {
    applyWbGearFromRoute()
  },
)

onMounted(() => {
  window.addEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  applyWbGearFromRoute()
  applySidebarModeSideEffects(wbSidebar.activeMode)
  setTimeout(() => {
    directBoxEnter.value = false
    contentEnter.value = false
    composerPanelEnter.value = false
    titleEnterDone.value = false
  }, 30)
  if (wbSidebar.activeMode === 'voice' && !voiceMicPausedByUser.value && !voiceListening.value) {
    streamingTts.warmUp()
    if (!wbNav.isMobile) {
      void startVoiceRecognition({ fresh: true })
    } else {
      voiceMicPausedByUser.value = true
    }
  }
  if (typeof window !== 'undefined') {
    ;(window as Window & { __wbOpenSixDimTest?: () => void }).__wbOpenSixDimTest = openSixDimTestPreview
    try {
      if (new URLSearchParams(window.location.search).get('wb_test_sixdim') === '1') {
        openSixDimTestPreview()
      }
    } catch {
      /* ignore */
    }
  }
  document.addEventListener('mousedown', onScenePanelOutside)
  document.addEventListener('keydown', onScenePanelKeydown)
  window.addEventListener('resize', onScenePanelReposition)
  window.addEventListener('scroll', onScenePanelReposition, true)
})

watch(tierPanelOpen, (open) => {
  if (open) nextTick(() => updateTierPanelAnchor())
})
watch(empPanelOpen, (open) => {
  if (open) nextTick(() => updateEmpPanelAnchor())
})
watch(
  () => wbSidebar.mobileOpen,
  (open) => {
    if (open) {
      tierPanelOpen.value = false
      empPanelOpen.value = false
    }
  },
)

watch(
  () => wbSidebar.activeMode,
  (mode, prev) => {
    if (mode === 'direct') {
      voiceCasualChatMode.value = false
      platformChatMode.value = false
    } else {
      applySidebarModeSideEffects(mode)
    }
    if (mode === 'voice') {
      wbSidebar.closeMobile()
      ensureVoiceEmployeeIntent()
      void unlockVoiceAudioPlayback()
      streamingTts.warmUp()
      if (!voiceListening.value) {
        if (wbNav.isMobile) {
          voiceMicPausedByUser.value = true
          voiceError.value = ''
        } else if (!voiceMicPausedByUser.value) {
          void startVoiceRecognition({ fresh: true })
        }
      }
    } else if (prev === 'voice') {
      voiceChat.clearContinuousSilenceTimer()
      voiceChat.stopSilenceWatchdog()
      if (voiceListening.value || voiceState.value === 'listening') {
        void stopVoiceRecognition()
      }
      if (streamingTts.state.value !== 'idle') {
        streamingTts.stop()
      }
      voiceState.value = 'idle'
    }
  },
)

/** cascade 播报时暂停 ASR；unified/s2s 保持麦克风全双工，靠 barge-in */
watch(
  () => streamingTts.state.value,
  (state, prev) => {
    if (wbSidebar.activeMode !== 'voice' || voiceMicPausedByUser.value) return
    if (voiceUsePhonePipeline.value) return
    if (state !== 'idle' && prev === 'idle' && voiceListening.value) {
      void voiceChat.stopListening()
    }
  },
)

onDeactivated(() => {
  window.removeEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  dismissHomeBodyOverlays()
})

watch(
  () => route.name,
  (name) => {
    const n = String(name || '')
    if (n !== 'workbench-home' && n !== 'home') {
      dismissHomeBodyOverlays()
    }
  },
)

watch(
  [planSession, pendingHandoff, orchPhase, finalizeLoading],
  () => {
    syncVoiceWorkPhase()
  },
  { deep: true },
)

watch(directChatEmployeeId, (v) => {
  try {
    const s = String(v || '').trim()
    if (s) sessionStorage.setItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, s)
    else sessionStorage.removeItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
  } catch {
    /* ignore */
  }
})

watch(directWebSearchEnabled, (enabled) => {
  try {
    sessionStorage.setItem(WB_DIRECT_WEB_SEARCH_KEY, JSON.stringify({ enabled: Boolean(enabled) }))
  } catch {
    /* ignore */
  }
})

watch(
  [directImageGenEnabled, directImageSize, directImageStyle, directImageCount],
  () => {
    try {
      sessionStorage.setItem(
        WB_DIRECT_IMAGE_GEN_KEY,
        JSON.stringify({
          enabled: directImageGenEnabled.value,
          size: directImageSize.value,
          style: directImageStyle.value,
          count: directImageCount.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)

watch(
  [directVideoGenEnabled, directVideoAspect, directVideoDurationSec],
  () => {
    try {
      sessionStorage.setItem(
        WB_DIRECT_VIDEO_GEN_KEY,
        JSON.stringify({
          enabled: directVideoGenEnabled.value,
          aspect: directVideoAspect.value,
          durationSec: directVideoDurationSec.value,
        }),
      )
    } catch {
      /* ignore */
    }
  },
)

watch(
  () => Boolean(planSession.value?.loading),
  (loading) => {
    if (planLoadingIntervalId !== null) {
      clearInterval(planLoadingIntervalId)
      planLoadingIntervalId = null
    }
    planLoadingAdvance.value = 0
    if (!loading) return
    const step = () => {
      const ps = planSession.value
      const list = ps?.phase === 'summary' ? planLoadingStepsSummary : planLoadingStepsChat
      const max = Math.max(0, list.length - 1)
      if (planLoadingAdvance.value < max) planLoadingAdvance.value += 1
    }
    planLoadingIntervalId = window.setInterval(step, 2000)
  },
)

watch(
  [
    planSession,
    planReplyDraft,
    planOptionSelections,
    pendingHandoff,
    workflowLinkOffer,
    finalizeLoading,
    finalizeError,
    orchestrationSession,
    orchestrationSessionId,
    orchPhase,
    orchestrationEtaSeconds,
    orchestrationEtaReason,
    orchTimingStartMs,
    composerIntent,
    draft,
    modFrontendEnabled,
    activeGear,
  ],
  cacheMakeProgress,
  { deep: true },
)

watch(
  () => ({ ...planOptionOtherText }),
  cacheMakeProgress,
  { deep: true },
)

onBeforeUnmount(() => {
  butlerTrayStore.clearActions()
  document.removeEventListener('mousedown', onScenePanelOutside)
  document.removeEventListener('keydown', onScenePanelKeydown)
  window.removeEventListener('resize', onScenePanelReposition)
  window.removeEventListener('scroll', onScenePanelReposition, true)
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  closePlanDiagramPreview()
  if (planLoadingIntervalId !== null) {
    clearInterval(planLoadingIntervalId)
    planLoadingIntervalId = null
  }
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onLlmDocPointerDown, true)
  window.removeEventListener('keydown', onLlmEscape)
  window.removeEventListener('wb-mode-switch', handleModeSwitchFromSidebar)
  window.removeEventListener('wb-open-settings', onWbOpenSettings)
  window.removeEventListener('wb-new-chat', onWbNewChat)
  window.removeEventListener('wb-pick-conversation', onWbPickConversation)
  stopDirectVoice()
  stopMakeVoice()
  stopDirectTtsPlayback()
  voiceS2s.disconnect()
})

function clearWorkbenchHandoffSession() {
  try {
    sessionStorage.removeItem('workbench_home_draft')
    sessionStorage.removeItem('workbench_home_intent')
    sessionStorage.removeItem('workbench_home_llm')
    sessionStorage.removeItem('workbench_home_llm_mode')
  } catch {
    /* ignore */
  }
  clearMakeProgressCache()
}

/** 做 Mod 时屏蔽「选语言 / 选 API 风格 / 选 UI 库」等通用脚手架题（旧回复或误遵指令时兜底） */
function isModHostStackSurveyQuestion(q) {
  const t = String(q?.title || '').trim()
  if (!t) return false
  if (/员工包.*语言|后端.*语言|^语言$/i.test(t)) return true
  if (/API\s*(设计|风格)|RESTful|RPC\s*风格|统一前缀/i.test(t)) return true
  if (/前端\s*UI|UI\s*框架|Element\s*Plus|Ant\s*Design|Vant/i.test(t)) return true
  return false
}

function normalizePlanOptions(raw) {
  const out = []
  if (!Array.isArray(raw)) return out
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const qid = String(item.id || '').trim().slice(0, 48)
    const title = String(item.title || item.question || '').trim().slice(0, 120)
    const choicesIn = item.choices
    if (!qid || !title || !Array.isArray(choicesIn)) continue
    const choices = []
    for (const c of choicesIn) {
      if (!c || typeof c !== 'object') continue
      const cid = String(c.id || '').trim().slice(0, 48)
      const label = String(c.label || c.text || '').trim().slice(0, 160)
      if (!cid || !label) continue
      choices.push({ id: cid, label })
    }
    if (choices.length < 2) continue
    if (choices.length > 5) choices.length = 5
    out.push({ id: qid, title, choices })
  }
  return out.slice(0, 6)
}

/** 解析规划助手回复：Mermaid + <<<PLAN_DETAILS>>> + <<<PLAN_OPTIONS>>> JSON（与 buildPlanSystemPrompt 约定一致） */
function parsePlanAssistantContent(raw) {
  const s = String(raw || '')
  const mer = s.match(/```mermaid\s*([\s\S]*?)```/i)
  const diagram = mer ? mer[1].trim() : ''
  const det = s.match(/<<<PLAN_DETAILS>>>([\s\S]*?)<<<END_PLAN_DETAILS>>>/i)
  const opt = s.match(/<<<PLAN_OPTIONS>>>([\s\S]*?)<<<END_PLAN_OPTIONS>>>/i)
  let options = []
  if (opt) {
    const rawJson = opt[1].trim()
    try {
      options = normalizePlanOptions(JSON.parse(rawJson))
    } catch {
      options = []
    }
  }
  let details = det ? det[1].trim() : ''
  if (!details) {
    let rest = stripInternalMarkers(s)
    if (mer) rest = rest.replace(mer[0], '')
    if (det) rest = rest.replace(det[0], '')
    if (opt) rest = rest.replace(opt[0], '')
    rest = rest.replace(/<<<PLAN_DETAILS>>>[\s\S]*/gi, '')
    rest = rest.replace(/<<<PLAN_OPTIONS>>>[\s\S]*/gi, '')
    rest = rest.replace(/```mermaid[\s\S]*?```/gi, '')
    details = rest.replace(/^\s*\n+|\n+\s*$/g, '').trim()
  }
  if (!details && diagram) details = '（仅流程图，无补充说明）'
  const hasDiagram = diagram.length > 0
  return { diagram, details, hasDiagram, options }
}

const planQuickOptions = computed(() => {
  const ps = planSession.value
  if (!ps?.messages?.length) return []
  for (let i = ps.messages.length - 1; i >= 0; i--) {
    if (ps.messages[i].role === 'assistant') {
      let o = parsePlanAssistantContent(ps.messages[i].content).options
      if (!Array.isArray(o)) return []
      if (ps.intentKey === 'mod') {
        o = o.filter((q) => !isModHostStackSurveyQuestion(q))
      }
      return o
    }
  }
  return []
})

const planPanelTitle = computed(() => {
  const ps = planSession.value
  if (!ps) return '需求规划'
  if (ps.phase === 'summary') return ps.summaryTitle || '确认任务摘要'
  return ps.summaryTitle || '需求规划'
})

const planChecklistFlowMarkdown = computed(() => {
  const lines = Array.isArray(planSession.value?.checklistLines) ? planSession.value.checklistLines : []
  return buildChecklistFlowMarkdown(lines)
})

function mermaidChecklistLabel(text, max = 30) {
  const s = String(text || '')
    .replace(/^\s*\d+[\.)、]\s*/, '')
    .replace(/[<>]/g, '')
    .replace(/["[\]{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '步骤'
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function buildChecklistFlowMarkdown(lines) {
  const list = Array.isArray(lines) ? lines.filter((x) => String(x || '').trim()).slice(0, 18) : []
  if (!list.length) {
    return '```mermaid\nflowchart TD\n  start["开始"] --> done["完成"]\n```'
  }
  const out = ['```mermaid', 'flowchart TD', '  start["开始"]']
  list.forEach((line, idx) => {
    out.push(`  S${idx + 1}["${idx + 1}. ${mermaidChecklistLabel(line)}"]`)
  })
  out.push('  done["完成"]')
  out.push('  start --> S1')
  for (let i = 1; i < list.length; i += 1) {
    out.push(`  S${i} --> S${i + 1}`)
  }
  out.push(`  S${list.length} --> done`)
  out.push('```')
  return out.join('\n')
}

function cancelPlanSummary() {
  planSummaryStreamHandle?.abort()
  planSummaryStreamHandle = null
  dismissPlanSession()
  showAppToast('已取消任务摘要生成', { variant: 'info' })
}

function compactPlanVisibleText(text, max = 260) {
  const s = stripInternalMarkers(String(text || ''))
    .replace(/【本次上传附件全文】[\s\S]*?(?=\n\n---\n|$)/g, '【本次上传附件全文已读取，界面不展开】')
    .replace(/【我的文件资料库命中片段】[\s\S]*?(?=\n\n---\n|$)/g, '【资料库片段已读取，界面不展开】')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '请根据上传内容和输入描述进行规划'
  return s.length > max ? `${s.slice(0, max)}…` : s
}

/** 制作区大标题：从交接描述里优先取「初始想法」段，否则整段压缩 */
function extractInitialIdeaFromHandoff(description) {
  const s = String(description || '')
  const m = s.match(/【初始想法】\s*\n+([\s\S]*?)(?=\n\n---|\n【|$)/)
  const chunk = m?.[1]?.trim() ? m[1].trim() : s.trim()
  if (!chunk) return ''
  return compactPlanVisibleText(chunk, 900)
}

const MAKE_HERO_TITLE_MAX = 64

const makeHeroTitle = computed(() => {
  if (!makeHasActiveTask.value) return '今天有什么安排？'
  const ps = planSession.value
  if (ps) {
    const title = String(ps.summaryTitle || '').trim()
    if (title) return truncateWorkbenchText(title, MAKE_HERO_TITLE_MAX)
    if (ps.phase === 'summary') {
      const body = String(ps.summaryText || '').replace(/\s+/g, ' ').trim()
      if (body) return truncateWorkbenchText(body, MAKE_HERO_TITLE_MAX)
    }
    const firstUser = ps.messages?.find((m) => m.role === 'user')
    if (firstUser?.content) {
      return truncateWorkbenchText(compactPlanVisibleText(String(firstUser.content), 800), MAKE_HERO_TITLE_MAX)
    }
    return truncateWorkbenchText(planPanelTitle.value, MAKE_HERO_TITLE_MAX)
  }
  if (finalizeLoading.value) {
    const ps = planSession.value
    const title = String(ps?.summaryTitle || '').trim()
    if (title) return truncateWorkbenchText(title, MAKE_HERO_TITLE_MAX)
    const h = pendingHandoff.value
    const nm = h?.workflowName?.trim() || h?.employeeWorkflowName?.trim()
    if (nm) return truncateWorkbenchText(nm, MAKE_HERO_TITLE_MAX)
    const idea = h ? extractInitialIdeaFromHandoff(h.description) : ''
    if (idea) return truncateWorkbenchText(idea, MAKE_HERO_TITLE_MAX)
    return '制作进行中…'
  }
  if (makeCompletionResult.value?.title) {
    return truncateWorkbenchText(String(makeCompletionResult.value.title), MAKE_HERO_TITLE_MAX)
  }
  const h = pendingHandoff.value
  if (h) {
    if (isCanvasSkillIntent(h.intentKey) && h.workflowName?.trim()) {
      return truncateWorkbenchText(h.workflowName.trim(), MAKE_HERO_TITLE_MAX)
    }
    const idea = extractInitialIdeaFromHandoff(h.description)
    if (idea) return truncateWorkbenchText(idea, MAKE_HERO_TITLE_MAX)
    return truncateWorkbenchText(h.intentTitle || '制作草稿', MAKE_HERO_TITLE_MAX)
  }
  const orch = orchestrationSession.value
  if (orch?.steps?.length) {
    const art = orch.artifact || {}
    const nm = String(art.workflow_name || art.workflowName || art.name || orch.workflow_name || '').trim()
    if (nm) return truncateWorkbenchText(nm, MAKE_HERO_TITLE_MAX)
    const st = orch.steps.find((s) => s.status === 'running') || orch.steps[0]
    if (st?.label) return truncateWorkbenchText(String(st.label), MAKE_HERO_TITLE_MAX)
    return '制作进行中'
  }
  const wf = workflowLinkOffer.value
  if (wf?.workflowName) return truncateWorkbenchText(String(wf.workflowName), MAKE_HERO_TITLE_MAX)
  return '进行中的任务'
})

const activeModeReset = computed(() => wbSidebar.activeMode)
const directTitleText = computed(() => {
  if (activeBot.value) return activeBot.value.name
  if (showMakePlatformCasualChat.value) return '先说说你想做什么'
  return '有什么想问的？'
})
const directSubText = computed(() => {
  if (activeBot.value?.desc) return activeBot.value.desc
  if (showMakePlatformCasualChat.value) {
    return '仍在「做」档位：先对齐需求再动手。需要规划 Mod / 员工 / Skill 时，先关闭顶栏「闲聊」再使用做 Mod / 做员工。'
  }
  return '像聊天一样提问，我直接帮你分析、总结和给出可执行答案。'
})
const makeKickerText = computed(() => greetingLine.value || '')
const makeTitleText = computed(() => makeHeroTitle.value)
const directTitleTw = useTypewriter(directTitleText, 55, activeModeReset)
const directSubTw = useTypewriter(directSubText, 40, activeModeReset)
const makeKickerTw = useTypewriter(makeKickerText, 40, activeModeReset)
const makeTitleTw = useTypewriter(makeTitleText, 40, activeModeReset)
const voiceKickerText = computed(() => voiceState.value === 'idle' ? '' : voiceStatusText.value)
const voiceTitleText = computed(() => voiceTitle.value)
const voiceKickerTw = useTypewriter(voiceKickerText, 40, activeModeReset)
const voiceTitleTw = useTypewriter(voiceTitleText, 55, activeModeReset)

function buildPlanSummarySystemPrompt(intentTitle, mode?: string) {
  const lines = [
    '你是需求摘要助手。你只负责把用户上传文件和输入内容总结成一个简短、准确的任务摘要，供用户确认。',
    `当前制作类型：${intentTitle || '未指定'}`,
    '输出格式必须严格为：',
    'TITLE: 一句话任务标题，不超过22个中文字符',
    'SUMMARY: 2到3句话说明任务目标、输入文件、期望产出',
  ]
  if (mode === 'employee-voice') {
    lines.push(
      '若输入含【语音对话记录】且用户已说明员工职责、处理对象或期望产出，必须给出具体 TITLE，禁止 TITLE:待澄清。',
      '对话中已确认的细节（如全量提取、JSON 输出、使用场景）应写入 SUMMARY；仅把对话里尚未回答的问题列为「待确认：…」。',
    )
  } else {
    lines.push(
      '若输入信息不足以构成明确任务（如 ASR 噪声、闲聊碎片、缺少具体职责），必须输出：',
      'TITLE: 待澄清',
      'SUMMARY: 列出还需要用户补充的具体信息（不要编造未提及的内容）',
    )
  }
  lines.push(
    '禁止编造用户未提及的上传文件、工作表现数据、Excel 等内容。',
    '不要输出流程图，不要输出选项，不要输出执行清单，不要泄露附件全文。',
  )
  return lines.join('\n')
}

function parsePlanSummary(raw, fallback) {
  const text = String(raw || '').trim()
  const titleMatch = text.match(/^TITLE:\s*(.+)$/im)
  const summaryMatch = text.match(/^SUMMARY:\s*([\s\S]+)$/im)
  const lines = text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  const fallbackText = compactPlanVisibleText(fallback, 180)
  const title = (titleMatch?.[1] || lines[0] || fallbackText || '确认任务').replace(/^#+\s*/, '').trim().slice(0, 36)
  const summary = (summaryMatch?.[1] || lines.slice(1).join(' ') || fallbackText || title).trim()
  return { title, summary }
}

const canSendPlanQuickPicks = computed(() => {
  const opts = planQuickOptions.value
  if (!opts.length) return false
  const sel = planOptionSelections.value
  return opts.every((q) => {
    const cid = sel[q.id]
    if (!cid) return false
    if (cid === PLAN_OPTION_OTHER_ID) {
      return Boolean(String(planOptionOtherText[q.id] || '').trim())
    }
    return true
  })
})

watch(
  () => {
    const ps = planSession.value
    if (!ps?.messages?.length) return ''
    for (let i = ps.messages.length - 1; i >= 0; i--) {
      if (ps.messages[i].role === 'assistant') return ps.messages[i].content
    }
    return ''
  },
  () => {
    planOptionSelections.value = {}
    clearPlanOptionOtherText()
  },
)

function planAssistantParts(raw) {
  return parsePlanAssistantContent(raw)
}

/** 助手气泡 Mermaid 渲染错误（按消息下标） */
const planDiagramError = ref({})

/** 规划流程图：完整预览浮层（消息下标，null 为关闭） */
const planDiagramPreviewIdx = ref(null)
const planDiagramPreviewMountRef = ref(null)
const planDiagramPreviewViewportRef = ref(null)
const planPreviewScale = ref(1)
const planPreviewTx = ref(0)
const planPreviewTy = ref(0)
let planDiagramPreviewEscUnlisten = null
let planDiagramPreviewPointerCleanup = null

const planDiagramPreviewPanStyle = computed(() => ({
  transform: `translate(${planPreviewTx.value}px, ${planPreviewTy.value}px) scale(${planPreviewScale.value})`,
  transformOrigin: '0 0',
}))

function clearPlanDiagramPreviewPointerListeners() {
  if (planDiagramPreviewPointerCleanup) {
    planDiagramPreviewPointerCleanup()
    planDiagramPreviewPointerCleanup = null
  }
  planDiagramPreviewViewportRef.value?.classList.remove('wb-plan-diagram-preview-viewport--drag')
}

function onPlanDiagramPreviewWheel(e: WheelEvent) {
  const vp = planDiagramPreviewViewportRef.value
  if (!vp) return
  const rect = vp.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const oldS = planPreviewScale.value
  const factor = e.deltaY > 0 ? 0.9 : 1.1
  const newS = Math.min(6, Math.max(0.06, oldS * factor))
  if (Math.abs(newS - oldS) < 1e-6) return
  planPreviewTx.value = mx - ((mx - planPreviewTx.value) * newS) / oldS
  planPreviewTy.value = my - ((my - planPreviewTy.value) * newS) / oldS
  planPreviewScale.value = newS
}

function onPlanDiagramPreviewPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const vp = planDiagramPreviewViewportRef.value
  if (!vp || !planDiagramPreviewMountRef.value) return
  clearPlanDiagramPreviewPointerListeners()
  const sx = e.clientX
  const sy = e.clientY
  const stx = planPreviewTx.value
  const sty = planPreviewTy.value
  vp.classList.add('wb-plan-diagram-preview-viewport--drag')
  const move = (ev: PointerEvent) => {
    planPreviewTx.value = stx + (ev.clientX - sx)
    planPreviewTy.value = sty + (ev.clientY - sy)
  }
  const end = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
    vp.classList.remove('wb-plan-diagram-preview-viewport--drag')
    planDiagramPreviewPointerCleanup = null
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', end)
  window.addEventListener('pointercancel', end)
  planDiagramPreviewPointerCleanup = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
    vp.classList.remove('wb-plan-diagram-preview-viewport--drag')
  }
}

function planDiagramPreviewZoomStep(dir: number) {
  const vp = planDiagramPreviewViewportRef.value
  if (!vp) return
  const mx = vp.clientWidth / 2
  const my = vp.clientHeight / 2
  const oldS = planPreviewScale.value
  const factor = dir < 0 ? 1 / 1.22 : 1.22
  const newS = Math.min(6, Math.max(0.06, oldS * factor))
  planPreviewTx.value = mx - ((mx - planPreviewTx.value) * newS) / oldS
  planPreviewTy.value = my - ((my - planPreviewTy.value) * newS) / oldS
  planPreviewScale.value = newS
}

async function planDiagramPreviewFitView() {
  await nextTick()
  const vp = planDiagramPreviewViewportRef.value
  const mount = planDiagramPreviewMountRef.value
  const svg = mount?.querySelector('svg')
  if (!vp || !svg) return
  planPreviewScale.value = 1
  planPreviewTx.value = 0
  planPreviewTy.value = 0
  await nextTick()
  await new Promise<void>((r) => requestAnimationFrame(() => r()))
  let nw = 0
  let nh = 0
  try {
    const bb = svg.getBBox()
    nw = bb.width
    nh = bb.height
  } catch {
    /* ignore */
  }
  if (!nw || !nh) {
    const r = svg.getBoundingClientRect()
    nw = r.width || 1
    nh = r.height || 1
  }
  const pad = 36
  const vw = Math.max(64, vp.clientWidth - pad * 2)
  const vh = Math.max(64, vp.clientHeight - pad * 2)
  const s = Math.min(vw / nw, vh / nh, 3)
  const fit = Number.isFinite(s) && s > 0 ? s : 1
  planPreviewScale.value = fit
  const bw = nw * fit
  const bh = nh * fit
  planPreviewTx.value = (vp.clientWidth - bw) / 2
  planPreviewTy.value = (vp.clientHeight - bh) / 2
}

async function openPlanDiagramPreview(idx) {
  planDiagramPreviewIdx.value = idx
  planPreviewScale.value = 1
  planPreviewTx.value = 0
  planPreviewTy.value = 0
  if (planDiagramPreviewEscUnlisten) {
    planDiagramPreviewEscUnlisten()
    planDiagramPreviewEscUnlisten = null
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closePlanDiagramPreview()
  }
  window.addEventListener('keydown', onKey)
  planDiagramPreviewEscUnlisten = () => window.removeEventListener('keydown', onKey)
  await nextTick()
  await nextTick()
  const host = document.getElementById(`wb-plan-mer-${idx}`)
  const svg = host?.querySelector('svg')
  const target = planDiagramPreviewMountRef.value
  if (!target) return
  target.innerHTML = ''
  if (svg) {
    const clone = svg.cloneNode(true) as SVGElement
    clone.style.maxWidth = 'none'
    clone.style.width = 'auto'
    clone.style.height = 'auto'
    target.appendChild(clone)
  } else {
    const p = document.createElement('p')
    p.className = 'wb-plan-diagram-preview-empty'
    p.textContent = '流程图尚未渲染完成，请稍后再次点击「完整预览」。'
    target.appendChild(p)
  }
  await nextTick()
  await planDiagramPreviewFitView()
  target.focus()
}

function closePlanDiagramPreview() {
  clearPlanDiagramPreviewPointerListeners()
  if (planDiagramPreviewEscUnlisten) {
    planDiagramPreviewEscUnlisten()
    planDiagramPreviewEscUnlisten = null
  }
  planDiagramPreviewIdx.value = null
}

let mermaidApi = null
let mermaidInitDone = false

async function getMermaidSingleton() {
  if (!mermaidApi) {
    const mod = await import('mermaid')
    mermaidApi = mod.default
  }
  if (!mermaidInitDone) {
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'dark',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    })
    mermaidInitDone = true
  }
  return mermaidApi
}

async function flushPlanMermaidDiagrams() {
  const ps = planSession.value
  if (!ps?.messages?.length) {
    planDiagramError.value = {}
    return
  }
  const nextErr = {}
  let mer
  try {
    mer = await getMermaidSingleton()
  } catch {
    planDiagramError.value = { _: '无法加载流程图组件' }
    return
  }
  for (const [idx, m] of ps.messages.entries()) {
    if (m.role !== 'assistant') continue
    const { diagram, hasDiagram } = parsePlanAssistantContent(m.content)
    const host = document.getElementById(`wb-plan-mer-${idx}`)
    if (!host) continue
    host.innerHTML = ''
    if (!hasDiagram) continue
    const cleaned = sanitizeMermaidSource(diagram)
    const graphEl = document.createElement('div')
    graphEl.className = 'mermaid'
    graphEl.textContent = cleaned
    host.appendChild(graphEl)
    try {
      await mer.run({ nodes: [graphEl] })
    } catch (e) {
      if (cleaned !== diagram) {
        host.innerHTML = ''
        const retryEl = document.createElement('div')
        retryEl.className = 'mermaid'
        retryEl.textContent = diagram
        host.appendChild(retryEl)
        try {
          await mer.run({ nodes: [retryEl] })
          continue
        } catch {
          host.innerHTML = ''
        }
      } else {
        host.innerHTML = ''
      }
      nextErr[idx] = friendlyMermaidRenderError(e)
    }
  }
  planDiagramError.value = nextErr
}

watch(
  () => {
    const ps = planSession.value
    if (!ps?.messages) return ''
    return ps.messages.map((m) => `${m.role}\t${m.content}`).join('\n')
  },
  async () => {
    await nextTick()
    if (!planSession.value) {
      planDiagramError.value = {}
      return
    }
    await flushPlanMermaidDiagrams()
  },
)

function dismissPlanSession() {
  closePlanDiagramPreview()
  planSession.value = null
  planReplyDraft.value = ''
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  planDiagramError.value = {}
}

/** 二档制作主输入：开启全新任务，清空草稿、附件、规划与执行态。 */
function resetMakeComposer() {
  if (knowledgeUploading.value) return
  dismissPendingHandoff()
  dismissPlanSession()
  makeCompletionResult.value = null
  employeeSixDimModalOpen.value = false
  employeeSixDimReport.value = null
  draft.value = ''
  knowledgeError.value = ''
  const files = directAttachedFiles.value.slice()
  directAttachedFiles.value = []
  for (const item of files as Array<{ docId?: string }>) {
    if (item.docId) {
      void api.knowledgeDeleteDocument(item.docId).catch(() => {
        /* 与移除单附件一致 */
      })
    }
  }
  clearMakeProgressCache()
  nextTick(() => {
    const el = inputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}

async function loadKnowledgeDocuments(requireLogin = false) {
  if (!getAccessToken()) {
    if (requireLogin) requireLoginForWorkbenchUse()
    knowledgeStatus.value = null
    knowledgeDocs.value = []
    knowledgeError.value = ''
    return
  }
  knowledgeLoading.value = true
  knowledgeError.value = ''
  try {
    const [st, docs] = await Promise.all([
      api.knowledgeStatus(),
      api.knowledgeListDocuments(),
    ])
    knowledgeStatus.value = st
    knowledgeDocs.value = Array.isArray(docs?.documents) ? docs.documents : []
  } catch (e) {
    knowledgeError.value = e?.message || String(e)
    knowledgeDocs.value = []
  } finally {
    knowledgeLoading.value = false
  }
}

function openKnowledgeFilePicker() {
  if (knowledgeUploading.value || planSession.value) return
  if (!requireLoginForWorkbenchUse()) return
  knowledgeFileInputRef.value?.click?.()
}

async function uploadKnowledgeFiles(files) {
  const list = Array.from(files || []).filter(Boolean)
  if (!list.length || knowledgeUploading.value) return
  if (!requireLoginForWorkbenchUse()) return
  knowledgeError.value = ''
  try {
    await ingestComposerFiles(list as File[], 'make')
  } catch (err) {
    knowledgeError.value = err?.message || String(err)
  } finally {
    if (knowledgeFileInputRef.value) knowledgeFileInputRef.value.value = ''
  }
}

async function onKnowledgeFileChange(e) {
  await uploadKnowledgeFiles(e?.target?.files)
}

function onKnowledgeDragEnter() {
  if (knowledgeUploading.value || planSession.value) return
  knowledgeDragActive.value = true
}

function onKnowledgeDragLeave(e) {
  const current = e?.currentTarget
  const related = e?.relatedTarget
  if (current && related && current.contains?.(related)) return
  knowledgeDragActive.value = false
}

async function onKnowledgeDrop(e) {
  knowledgeDragActive.value = false
  if (knowledgeUploading.value || planSession.value) return
  if (!requireLoginForWorkbenchUse()) return
  await uploadKnowledgeFiles(e?.dataTransfer?.files)
}

function fileExtension(filename) {
  const ext = String(filename || '').split('.').pop()?.toLowerCase() || 'file'
  return ext.length > 5 ? ext.slice(0, 5) : ext
}

function fileKind(doc) {
  const ext = fileExtension(doc?.filename)
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx') return 'doc'
  if (ext === 'xlsx' || ext === 'csv') return 'sheet'
  if (ext === 'json') return 'json'
  if (ext === 'md') return 'md'
  return 'text'
}

function fileKindClass(doc) {
  return `wb-kb-card--${fileKind(doc)}`
}

function fileKindLabel(doc) {
  const m = {
    pdf: 'PDF 文档',
    doc: 'Word 文档',
    sheet: '表格数据',
    json: 'JSON 配置',
    md: 'Markdown',
    text: '文本资料',
  }
  return m[fileKind(doc)] || '文件'
}

function formatBytes(value) {
  const n = Number(value || 0)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  if (n < 1024) return `${Math.round(n)} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function deleteKnowledgeDocument(docId) {
  if (!docId) return
  if (!requireLoginForWorkbenchUse()) return
  try {
    await api.knowledgeDeleteDocument(docId)
    await loadKnowledgeDocuments()
  } catch (e) {
    knowledgeError.value = e?.message || String(e)
  }
}

function formatKnowledgeContext(items) {
  const rows = Array.isArray(items) ? items : []
  if (!rows.length) return ''
  return rows
    .slice(0, 6)
    .map((it, i) => {
      const filename = it?.filename || '资料'
      const pageNo = Number(it?.page_no || it?.pageNo || 0) || 0
      const content = String(it?.content || '').trim()
      return `### ${i + 1}. ${filename}${pageNo ? `（第 ${pageNo} 页）` : ''}\n${content}`
    })
    .join('\n\n---\n\n')
}

function dismissWorkflowLinkOffer() {
  workflowLinkOffer.value = null
  linkMods.value = []
  linkModId.value = ''
  linkError.value = ''
  linkBusy.value = false
}

async function loadLinkMods() {
  try {
    const res = await api.listMods()
    linkMods.value = Array.isArray(res?.data) ? res.data : []
  } catch {
    linkMods.value = []
  }
}

async function openWorkflowCanvasOnly() {
  const o = workflowLinkOffer.value
  if (!o) return
  const wid = o.workflowId
  dismissWorkflowLinkOffer()
  await router.push({ name: 'workbench-workflow', query: { edit: String(wid) } })
}

async function confirmWorkflowModLink() {
  const o = workflowLinkOffer.value
  if (!o || !linkModId.value) return
  linkBusy.value = true
  linkError.value = ''
  try {
    await api.modWorkflowLink(String(linkModId.value), {
      workflow_id: o.workflowId,
      label: o.workflowName,
    })
    const mid = linkModId.value
    dismissWorkflowLinkOffer()
    await router.push({ name: 'mod-authoring', params: { modId: mid } })
  } catch (e) {
    linkError.value = e.message || String(e)
  } finally {
    linkBusy.value = false
  }
}

function dismissPendingHandoff() {
  pendingHandoff.value = null
  finalizeError.value = ''
  makeCompletionResult.value = null
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  pollStop.value = true
  stopOrchestrationElapsedTicker()
  orchPhase.value = 'idle'
  orchTimingStartMs.value = null
  orchestrationEtaSeconds.value = null
  orchestrationEtaReason.value = ''
  finalizeLoading.value = false
  dismissWorkflowLinkOffer()
  clearWorkbenchHandoffSession()
}

function buildMakeCompletionResult(final, intent, handoffSnapshot) {
  const art = final?.artifact || {}
  const finIntent = final?.intent || intent
  if (finIntent === 'employee') {
    const packId = art.pack_id != null ? String(art.pack_id) : ''
    const q = {
      focus: 'employee',
      fromAi: '1',
      packId,
      name: art.name != null ? String(art.name) : '',
      desc: art.description != null ? String(art.description) : '',
    }
    const wfId = art.workflow_id ?? art.workflow_attachment?.workflow_id
    if (wfId != null && Number(wfId) > 0) q.wfId = String(wfId)
    const name = String(art.name || handoffSnapshot?.employeeWorkflowName || '员工包').trim()
    return {
      intent: 'employee',
      title: `${name} 已生成`,
      subtitle: packId ? `员工包 ID：${packId}` : '员工包已写入本地库',
      usageLines: [
        '员工包已写入本地目录，尚未自动上架到商店。',
        '打开「员工制作」→ 测试运行 → 确认无误后手动上传/上架。',
        'Word 提取类员工：上传 .doc/.docx，输出同名 .txt。',
        wfId ? `已绑定画布工作流 id=${wfId}，可在 Skill 组画布继续调整。` : '',
      ].filter(Boolean),
      primaryLabel: '打开员工制作',
      primaryRoute: hasEmployee.value
        ? { name: 'workbench-unified', query: q }
        : null,
      secondaryLabel: wfId ? '打开 Skill 组画布' : '',
      secondaryRoute: wfId && hasWorkflow.value
        ? { name: 'workbench-unified', query: { focus: 'skill', edit: String(wfId) } }
        : null,
    }
  }
  if (finIntent === 'mod' && art.mod_id) {
    return {
      intent: 'mod',
      title: `Mod「${art.mod_id}」已生成`,
      subtitle: '仓库骨架、manifest 与员工名片已写入',
      usageLines: [
        '在 Mod 制作页完善行业 JSON、员工包与工作流绑定。',
        '完成绑定后可在宿主中切换 Mod 并做真实执行验证。',
      ],
      primaryLabel: '打开 Mod 制作',
      primaryRoute: { name: 'mod-authoring', params: { modId: String(art.mod_id) } },
      secondaryLabel: '',
      secondaryRoute: null,
    }
  }
  const gid = art.skill_group_id ?? art.workflow_id
  if (isCanvasSkillIntent(finIntent) && gid != null) {
    const nm = String(
      art.skill_group_name || art.workflow_name || handoffSnapshot?.workflowName || `Skill 组 ${gid}`,
    ).trim()
    return {
      intent: 'skill',
      title: `${nm} 已生成`,
      subtitle: art.sandbox_ok === false ? '部分校验未通过，请在画布中查看详情' : '节点与 Skill 已写入画布',
      usageLines: [
        '打开 Skill 组画布查看节点、连线和沙箱校验结果。',
        '可按需调整 Skill 输入输出与触发策略后再发布。',
      ],
      primaryLabel: '打开 Skill 组画布',
      primaryRoute: hasWorkflow.value ? { name: 'workbench-workflow', query: { edit: String(gid) } } : null,
      secondaryLabel: '',
      secondaryRoute: null,
    }
  }
  return {
    intent: finIntent,
    title: '制作已完成',
    subtitle: '',
    usageLines: ['请在工作台相关页面查看产物详情。'],
    primaryLabel: '知道了',
    primaryRoute: null,
    secondaryLabel: '',
    secondaryRoute: null,
  }
}

async function scrollMakeFlowToEnd() {
  await nextTick()
  const el = makeCompletionRef.value || handoffPanelRef.value || planPanelRef.value
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    return
  }
  const scene = document.querySelector('.wb-mode-scene--make-flow')
  if (scene && typeof scene.scrollTo === 'function') {
    scene.scrollTo({ top: scene.scrollHeight, behavior: 'smooth' })
  }
}

async function openMakeCompletionPrimary() {
  const r = makeCompletionResult.value
  if (!r?.primaryRoute) {
    makeCompletionResult.value = null
    return
  }
  try {
    await router.push(r.primaryRoute)
  } catch {
    finalizeError.value = '无法打开目标页面，请从左侧导航进入对应功能。'
  }
}

async function openMakeCompletionSecondary() {
  const r = makeCompletionResult.value
  if (!r?.secondaryRoute) return
  try {
    await router.push(r.secondaryRoute)
  } catch {
    finalizeError.value = '无法打开 Skill 组画布，请从工作流列表进入。'
  }
}

function closeEmployeeSixDimModal() {
  employeeSixDimModalOpen.value = false
}

/** Teleport 到 body 的遮罩在 keep-alive 切走首页后仍会挡住「统一工作台」等路由（z-index 12000）。 */
function dismissHomeBodyOverlays() {
  employeeSixDimModalOpen.value = false
  planDiagramPreviewIdx.value = null
  convPopoverOpen.value = false
  personalSettingsOpen.value = false
}

/** 开发/联调：打开六维雷达弹窗样例（?wb_test_sixdim=1 或控制台 __wbOpenSixDimTest()） */
/** 仅 ?wb_test_sixdim=1 / 控制台联调用；正式完成走 artifact.six_dimension_report */
function openSixDimTestPreview() {
  employeeSixDimReport.value = {
    dimensions: {
      requirement_clarity: {
        score: 88,
        grade: 'A',
        grade_label: 'A级·优秀',
        label: '需求理解',
        description: '需求是否被正确理解：brief 净化、结构化规格与 Word/资产管线识别是否一致。',
        reasons: ['routing brief 有效', 'Word 场景已识别 direct_python'],
      },
      pack_compliance: {
        score: 92,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '包体合规',
        description: 'manifest 可读性、artifact 类型、员工声明字段与 validate 硬错误。',
        reasons: ['manifest 可读', '包体声明与校验通过'],
      },
      code_robustness: {
        score: 85,
        grade: 'A',
        grade_label: 'A级·优秀',
        label: '代码健壮',
        description: 'Python 编译、包体一致性、mod 沙箱轻量校验结果。',
        reasons: ['Python 编译通过', 'mod 沙箱轻量校验通过'],
      },
      executability: {
        score: 90,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '可执行性',
        description: 'handlers 契约、独立 zipapp 自检、目录登记与领域 runtime。',
        reasons: ['handlers 契约通过', 'Word convert runtime 就绪'],
      },
      workflow_connectivity: {
        score: 78,
        grade: 'B',
        grade_label: 'B级·良好',
        label: '流程贯通',
        description: '员工包登记、工作流结构校验与真实员工调用。',
        reasons: ['登记成功', '工作流结构校验通过'],
      },
      domain_delivery: {
        score: 95,
        grade: 'S',
        grade_label: 'S级·卓越',
        label: '领域交付',
        description: '与 Word 全量提取管线匹配的交付能力。',
        reasons: ['Word 全量提取 runtime 通过', 'rule_spec runtime_kind 正确'],
      },
    },
    overall_score: 94.9,
    overall_grade: 'S',
    overall_grade_label: 'S级·卓越',
    passed: true,
    critical_failed: false,
    pipeline_label: 'word_full_extract',
    grade_scale: {
      S: '92–100：卓越，可直接交付',
      A: '85–91.9：优秀',
      B: '78–84.9：良好',
      P: '70–77.9：平级达标（达到流水线通过线）',
      C: '60–69.9：合格但有明显短板',
      D: '50–59.9：待改进',
      F: '40–49.9：高风险',
      G: '0–39.9 或关键维未达标：不可用',
    },
  }
  employeeSixDimModalOpen.value = true
}

function tryOpenEmployeeSixDimModal(final) {
  const art = final?.artifact
  if (!art || typeof art !== 'object') return
  const rep =
    (art as Record<string, unknown>).six_dimension_report ||
    ((art as Record<string, unknown>).quality_report as Record<string, unknown> | undefined)
      ?.six_dimension_report
  if (!rep || typeof rep !== 'object' || !(rep as Record<string, unknown>).dimensions) return
  employeeSixDimReport.value = rep
  employeeSixDimModalOpen.value = true
}

function applyMakeCompletion(final, intent, handoffSnapshot) {
  makeCompletionResult.value = buildMakeCompletionResult(final, intent, handoffSnapshot)
  pendingHandoff.value = null
  if (intent === 'employee') {
    tryOpenEmployeeSixDimModal(final)
  }
  void scrollMakeFlowToEnd()
  void maybeAutoOpenMakeCompletionInVoiceMode()
}

/** 说模式：14/14 完成后自动跳进员工画布（带 packId），避免停在语音页不知道下一步 */
async function maybeAutoOpenMakeCompletionInVoiceMode() {
  if (wbSidebar.activeMode !== 'voice') return
  if (employeeSixDimModalOpen.value) return
  const r = makeCompletionResult.value
  if (!r || r.intent !== 'employee' || !r.primaryRoute) return
  const qr = orchestrationSession.value?.artifact?.quality_report
  if (qr && (qr.critical_failed || qr.runnable === false)) return
  const spoken = String(r.title || '员工包已生成').replace(/。$/, '')
  await speakVoiceShort(`${spoken}，正在打开员工制作画布。`)
  await openMakeCompletionPrimary()
}

async function persistManualLlmIfNeeded() {
  if (modelMode.value !== 'manual' || !selectedModel.value || !selectedProvider.value) return
  try {
    await api.llmSavePreferences(selectedProvider.value, selectedModel.value)
  } catch {
    /* 仍尝试创建工作流 */
  }
}

async function pollWorkbenchSession(sessionId) {
  const delay = (ms) => new Promise((r) => setTimeout(r, ms))
  /**
   * 轮询策略：基础 1500ms（约 40 次/分钟），落在后端 RateLimiterMiddleware
   * 默认 60 次/60 秒的限额内，避免「开始生成员工包」长时间运行被 429 截断。
   * 后端同时为 GET /api/workbench/sessions/{id} 单独抬高了上限作为兜底。
   */
  const baseIntervalMs = 1500
  const runningIntervalMs = 1000
  /** 总等待预算约 30 分钟（配套小程序等步骤可走多轮 Agent），墙钟时间而非轮询次数（应对动态退避）。 */
  const deadline = Date.now() + 30 * 60 * 1000
  let backoffMs = 0
  while (!pollStop.value) {
    try {
      const s = await api.workbenchGetSession(sessionId)
      const prevSteps = orchestrationSession.value?.steps
      const mergedSteps = mergeOrchStepsMonotonic(prevSteps, s.steps || [])
      orchestrationSession.value = { ...s, steps: mergedSteps }
      _trackStepMessages(mergedSteps)
      if (s.status === 'done' || s.status === 'error') {
        if (s.status === 'done') {
          const nonTerminal = (mergedSteps || []).filter(
            (x: { status?: string }) =>
              x.status !== 'done' && x.status !== 'error' && x.status !== 'skipped',
          )
          if (nonTerminal.length > 0) {
            for (let i = 0; i < 3 && !pollStop.value; i++) {
              await delay(800)
              try {
                const s2 = await api.workbenchGetSession(sessionId)
                const merged2 = mergeOrchStepsMonotonic(
                  orchestrationSession.value?.steps,
                  s2.steps || [],
                )
                orchestrationSession.value = { ...s2, steps: merged2 }
                _trackStepMessages(merged2)
                const stillPending = (merged2 || []).filter(
                  (x: { status?: string }) =>
                    x.status !== 'done' && x.status !== 'error' && x.status !== 'skipped',
                )
                if (stillPending.length === 0) break
              } catch {
                break
              }
            }
          }
        }
        return orchestrationSession.value as typeof s
      }
      backoffMs = 0
    } catch (e) {
      const status = e && typeof e === 'object' && typeof (e as any).status === 'number' ? (e as any).status : 0
      // 429（限流）/ 503（短暂不可用）属于可恢复抖动：指数退避后继续轮询，
      // 而非把整个编排会话标记为失败。其余错误按原行为向上抛出。
      if (status === 429 || status === 503) {
        backoffMs = backoffMs ? Math.min(backoffMs * 2, 30000) : 5000
      } else {
        throw e
      }
    }
    if (Date.now() >= deadline) {
      const steps = Array.isArray(orchestrationSession.value?.steps) ? orchestrationSession.value.steps : []
      const stuckStep = steps.find((x) => x.status === 'running') || steps.slice().reverse().find((x) => x.status === 'done')
      const stuckLabel = stuckStep ? `「${String(stuckStep.label || stuckStep.id)}」` : ''
      throw new Error(`在${stuckLabel}步骤等待超时（约 30 分钟）。若会话仍在后端运行可刷新后从历史恢复；否则可重试。请检查后端日志、网络或 LLM 配置。`)
    }
    const sessStatus = orchestrationSession.value?.status
    const hasRunningStep = Array.isArray(orchestrationSession.value?.steps)
      && orchestrationSession.value.steps.some((x) => x.status === 'running')
    const tickMs =
      backoffMs || (sessStatus === 'running' || hasRunningStep ? runningIntervalMs : baseIntervalMs)
    await delay(tickMs)
  }
  return null
}

async function resumeCachedOrchestration() {
  const sid = String(orchestrationSessionId.value || '').trim()
  if (!sid || !finalizeLoading.value) return
  pollStop.value = false
  if (orchPhase.value !== 'estimating') {
    orchPhase.value = 'running'
    if (!orchTimingStartMs.value) orchTimingStartMs.value = Date.now()
    startOrchestrationElapsedTicker()
  }
  try {
    const final = await pollWorkbenchSession(sid)
    if (!final || pollStop.value) return
    orchestrationSession.value = final
    if (final.status === 'error') {
      finalizeError.value = final.error || '编排失败'
    }
  } catch (e: any) {
    const m = e?.message || String(e)
    finalizeError.value = m
  } finally {
    stopOrchestrationElapsedTicker()
    finalizeLoading.value = false
    orchPhase.value = 'idle'
    orchTimingStartMs.value = null
  }
}

async function runOrchestration(): Promise<boolean> {
  const h = pendingHandoff.value
  if (!h || !hasWorkflow.value || finalizeLoading.value) return false
  if (!requireLoginForWorkbenchUse()) return
  if (!canRunOrchestration.value) {
    if (isCanvasSkillIntent(h.intentKey)) finalizeError.value = '请填写 Skill 组名称与描述'
    else finalizeError.value = '请填写描述'
    return false
  }
  enrichEmployeeHandoffBeforeOrchestration(h)
  const handoffSnapshot = { ...h }
  finalizeError.value = ''
  makeCompletionResult.value = null
  finalizeLoading.value = true
  pollStop.value = false
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  orchPhase.value = 'estimating'
  orchestrationEtaSeconds.value = null
  orchestrationEtaReason.value = ''
  orchTimingStartMs.value = null
  stopOrchestrationElapsedTicker()
  try {
    await persistManualLlmIfNeeded()
    const intent = h.intentKey || CANVAS_SKILL_INTENT
    const checklist = Array.isArray(h.executionChecklist) ? h.executionChecklist : []
    const scriptFiles = isCanvasSkillIntent(intent) && Array.isArray(h.files) ? h.files : []
    const eta = await estimateOrchestrationSeconds({
      intent,
      brief: String(handoffSnapshot.description || '').trim(),
      checklistLen: checklist.length,
      generateFrontend: intent === 'mod' ? modFrontendEnabled.value : false,
      employeeTarget: intent === 'employee' ? String(h.employeeTarget || '').trim() : '',
      scriptFileCount: scriptFiles.length,
    })
    let etaSec = eta.seconds
    let etaReason = String(eta.reason || '').trim()
    if (etaSec == null || !Number.isFinite(etaSec)) {
      etaSec = fallbackOrchestrationSecondsEstimate({
        intent,
        checklistLen: checklist.length,
        generateFrontend: intent === 'mod' ? modFrontendEnabled.value : false,
        employeeTarget: intent === 'employee' ? String(h.employeeTarget || '').trim() : '',
        scriptFileCount: scriptFiles.length,
      })
      if (!etaReason) etaReason = '按步骤量粗估（模型未返回数值）'
    }
    orchestrationEtaSeconds.value = etaSec
    orchestrationEtaReason.value = etaReason
    orchPhase.value = 'running'
    orchTimingStartMs.value = Date.now()
    startOrchestrationElapsedTicker()

    const body: Record<string, unknown> = {
      intent,
      brief:
        intent === 'employee' && String(handoffSnapshot.employeeRoutingBrief || '').trim()
          ? String(handoffSnapshot.employeeRoutingBrief).trim()
          : (handoffSnapshot.description || '').trim(),
      workflow_name:
        isCanvasSkillIntent(intent) ? (h.workflowName || '').trim() : undefined,
      plan_notes: isCanvasSkillIntent(intent) ? (h.planNotes || '').trim() : '',
      suggested_mod_id:
        intent === 'mod' ? (h.suggestedModId || '').trim() || undefined : undefined,
      replace: true,
      planning_messages: Array.isArray(h.planningMessages) ? h.planningMessages : [],
      execution_checklist: checklist,
      source_documents: Array.isArray(h.sourceDocuments) ? h.sourceDocuments : [],
      planning_context:
        intent === 'employee' ? String(handoffSnapshot.planningContext || handoffSnapshot.description || '').trim() : undefined,
      // 以当前「制作前端」开关为准，避免交接对象上缺失或陈旧的 generateFrontend
      generate_frontend: intent === 'mod' ? modFrontendEnabled.value : false,
    }
    if (intent === 'employee') {
      const et = String(h.employeeTarget || 'pack_only').trim()
      body.employee_target = et === 'pack_only' ? 'pack_only' : 'pack_plus_workflow'
      body.embed_script_workflow = true
      const wfn = String(h.employeeWorkflowName || '').trim()
      if (wfn) body.employee_workflow_name = wfn
      const fhd = String(h.fhdBaseUrl || '').trim()
      if (fhd) body.fhd_base_url = fhd
    }
    if (modelMode.value === 'manual' && selectedProvider.value && selectedModel.value) {
      body.provider = selectedProvider.value
      body.model = selectedModel.value
    } else {
      // Auto：与需求规划相同逻辑——默认厂商无密钥时换到已配置密钥的厂商，并显式传给编排接口
      const { provider, model } = await resolveChatProviderModel()
      body.provider = provider
      body.model = model
    }
    const useScriptMode = isCanvasSkillIntent(intent) && scriptFiles.length > 0
    const employeeFiles =
      intent === 'employee' && Array.isArray(h.files) && h.files.length ? h.files : []
    const started = useScriptMode
      ? await api.workbenchStartScriptSession(
          {
            brief: body.brief,
            workflow_name: body.workflow_name,
            provider: body.provider,
            model: body.model,
          },
          scriptFiles,
        )
      : employeeFiles.length
        ? await api.workbenchStartSessionWithFiles(body, employeeFiles)
        : await api.workbenchStartSession(body)
    const sid = started?.session_id
    if (!sid) throw new Error('未返回 session_id')
    orchestrationSessionId.value = String(sid)
    const final = await pollWorkbenchSession(sid)
    if (pollStop.value) return false
    if (!final) throw new Error('轮询已取消')
    void scrollMakeFlowToEnd()
    if (final.status === 'error') {
      finalizeError.value = final.error || '编排失败'
      return false
    }
    const art = final.artifact || {}
    const finIntent = final.intent || intent
    clearWorkbenchHandoffSession()
    try {
      if (modelMode.value === 'manual' && selectedProvider.value && selectedModel.value) {
        sessionStorage.setItem(
          'workbench_home_llm',
          JSON.stringify({
            provider: selectedProvider.value,
            model: selectedModel.value,
          }),
        )
        sessionStorage.setItem('workbench_home_llm_mode', 'manual')
      }
      sessionStorage.setItem('workbench_home_intent', finIntent)
    } catch {
      /* ignore */
    }
    if (art.execution_mode === 'script') {
      const scriptWorkflowId = Number(art.script_workflow_id || 0)
      applyMakeCompletion(final, finIntent, handoffSnapshot)
      if (Number.isFinite(scriptWorkflowId) && scriptWorkflowId > 0) {
        makeCompletionResult.value = {
          ...makeCompletionResult.value,
          primaryLabel: '打开脚本工作流沙箱',
          primaryRoute: { path: `/script-workflows/${scriptWorkflowId}/edit`, query: { tab: 'sandbox' } },
          usageLines: [
            '脚本工作流已生成，可在沙箱页上传同类文件反复验证输出。',
            '确认脚本正确后，可保存并发布为可复用工作流。',
          ],
        }
      }
      return true
    }
    const gid = art.skill_group_id ?? art.workflow_id
    if (isCanvasSkillIntent(finIntent) && gid != null) {
      workflowLinkOffer.value = {
        workflowId: gid,
        workflowName: String(
          art.skill_group_name ||
            art.workflow_name ||
            (h.workflowName || '').trim() ||
            `Skill 组 ${gid}`,
        ),
        validationErrors: Array.isArray(art.validation_errors) ? art.validation_errors : [],
        llmWarnings: Array.isArray(art.llm_warnings) ? art.llm_warnings : [],
        sandboxOk: art.sandbox_ok !== false,
      }
      linkModId.value = ''
      linkError.value = ''
      void loadLinkMods()
      pendingHandoff.value = null
      void scrollMakeFlowToEnd()
      return true
    }
    if (finIntent === 'mod' && art.mod_id) {
      applyMakeCompletion(final, finIntent, handoffSnapshot)
      return true
    }
    if (finIntent === 'employee') {
      applyMakeCompletion(final, finIntent, handoffSnapshot)
      return true
    }
    pendingHandoff.value = null
    orchestrationSession.value = null
    orchestrationSessionId.value = ''
    return true
  } catch (e: any) {
    const m = e?.message || String(e)
    const low = m.toLowerCase()
    if (
      low.includes('not found') ||
      low.includes('404') ||
      m.includes('会话不存在') ||
      m.includes('已过期')
    ) {
      finalizeError.value =
        '无法查询编排会话（可能命中了另一台后端进程）。请部署并重启带「工作台会话落盘」的版本后重试；若已更新仍失败，请再点一次「开始生成 Mod」。'
    } else {
      finalizeError.value = m
    }
    pendingHandoff.value = handoffSnapshot
    return false
  } finally {
    stopOrchestrationElapsedTicker()
    orchPhase.value = 'idle'
    orchTimingStartMs.value = null
    orchestrationEtaSeconds.value = null
    orchestrationEtaReason.value = ''
    finalizeLoading.value = false
  }
  return false
}

function applyStarter(kind) {
  if (hasWorkflow.value) {
    if (!INTENT_META[kind]) return
    dismissPlanSession()
    composerIntent.value = kind
    nextTick(() => {
      const el = inputRef.value
      if (el && typeof el.focus === 'function') el.focus()
    })
    return
  }
  const fallback = {
    mod: hasRepo.value ? 'workbench-repository' : null,
    employee: hasEmployee.value ? 'workbench-employee' : null,
    skill: hasWorkflow.value ? 'workbench-workflow' : null,
    workflow: hasWorkflow.value ? 'workbench-workflow' : null,
  }[kind]
  if (fallback && router.hasRoute(fallback)) {
    router.push({ name: fallback })
  }
}

function buildPlanSystemPrompt(intentKey, intentTitle) {
  const typeHint =
    isCanvasSkillIntent(intentKey)
      ? '区分两类产物：（1）Skill 组合工作流＝先把需求拆成可复用 ESkill/Skill，再把这些 Skill 组合成画布工作流；（2）脚本工作流＝可运行程序、直接完成任务。规划时若用户要「程序本体」，引导其需求规划结束后去「脚本工作流」新建；此处必须先识别业务能力边界，拆出多个 Skill，说明每个 Skill 的输入、输出、质量门和触发策略，再描述 Skill 之间的顺序、条件与失败重试。流程图用 flowchart LR 或 TD；节点 id 仅用英文字母；子图写 subgraph sg1["中文标题"]，结束用单独一行 end（禁止 endsubgraph）；含冒号/括号的中文标签必须加双引号。'
      : intentKey === 'mod'
        ? [
            '用户目标可能有两档：（1）Mod 草稿骨架：仓库、manifest、行业 JSON、workflow_employees 名片；（2）可执行员工：在骨架基础上生成/登记 employee_pack，绑定 workflow_id，让工作流 employee 节点使用可执行包 id，并完成非 Mock 真实执行验证。',
            '【宿主软件 FHD / XCAGI 已定型，禁止「技术栈问卷」】宿主主程序为 Vue 3 + Vite + Element Plus（FHD/frontend）；本 Mod 前端作为专业版切换（侧栏 proModeToggle 等入口）后的「第二套前端」，挂在现有 /mods/<id>/frontend 路由体系，UI 语汇与宿主一致，不要引导用户再选「Node/Python/Go 员工包语言」「REST/RPC」「Element Plus / Ant Design / Vant」等通用栈。',
            '宿主与平台服务侧为 Python + FastAPI 等，不要提议用 Express/Gin 替换宿主 API。澄清时围绕：行业与场景、仓库与数据、员工职责与工具、工作流绑定、外部系统（微信/电话/合同等）、合规与脱敏、是否需要额外宿主路由/页面；不要把这些写成「选语言/选框架」的多选题。',
            'Mermaid 须用 flowchart 画出「建仓库 → 员工名片 → 员工包登记 → 工作流绑定 → 真实验证」的主线，节点名两到六字中文，不用括号。',
            '<<<PLAN_OPTIONS>>>：若需要点选澄清，只能出与业务/交付相关的题；若当前轮没有合适的二选一/多选一，必须输出 []。严禁出现「后端语言」「前端 UI 框架」「API 风格 REST/RPC」类标题或选项。',
          ].join(' ')
        : '关注员工角色、可用工具/能力标识、输入输出与行业场景。Mermaid 用 flowchart 表示角色、工具、输出关系即可。节点 id 仅用英文字母 A/B/C…；子图写 subgraph sg1["中文标题"]，结束用单独一行 end（禁止 endsubgraph）；含冒号/括号的中文标签必须加双引号。'
  const diagramParity =
    intentKey === 'mod'
      ? '【与做员工对齐】每条回复的流程图要求与「做员工」完全相同：不得以「暂无图」「略」或纯文字代替拓扑；必须在 fenced Mermaid 中给出 flowchart。信息不足时仍输出极简示例，例如：flowchart LR 建仓库 --> 写JSON骨架 --> 员工命名。'
      : intentKey === 'employee'
        ? '【流程图】每条回复须含 fenced Mermaid flowchart，不得以纯文字代替；信息不足时用 3～5 个短中文节点概括角色与产出。'
        : ''
  return [
    `你是 XCAGI 工作台的「需求规划」助手。用户当前制作类型：「${intentTitle}」。`,
    `${typeHint}`,
    ...(diagramParity ? [diagramParity] : []),
    '流程：先根据用户的初步想法提出 2～4 个高价值澄清问题（用数字编号列出）；用户补充后，可继续追问直到需求足够具体。',
    '不要生成最终代码、manifest JSON 或工作流节点配置；不要代替用户直接写执行清单（清单由用户点击「生成执行清单」触发）。',
    '用语简洁，中文。',
    '',
    '【输出格式必须严格遵守，便于界面展示】',
    '1) 回复开头必须先输出且仅输出一段 fenced Mermaid（主视图流程草图），例如：',
    '```mermaid',
    'flowchart LR',
    '  A[开始] --> B[步骤]',
    '  B --> C[结束]',
    '```',
    '2) 紧接着输出澄清与说明文字，且必须用以下标记包裹（界面默认折叠在「详细」中）：',
    '<<<PLAN_DETAILS>>>',
    '（此处写编号问题与补充，可多段）',
    '<<<END_PLAN_DETAILS>>>',
    '3) 再输出快捷选项：单行 JSON 数组，用以下标记包裹（供界面点选；不需要选项时输出 []）：',
    '<<<PLAN_OPTIONS>>>',
    intentKey === 'mod'
      ? '[{"id":"q_scope","title":"交付档位","choices":[{"id":"skeleton","label":"先骨架（manifest/行业 JSON/名片）"},{"id":"full","label":"骨架 + 可执行员工包 + 工作流绑定"}]}]'
      : '[{"id":"q1","title":"短标题","choices":[{"id":"c1","label":"选项甲"},{"id":"c2","label":"选项乙"}]}]',
    '<<<END_PLAN_OPTIONS>>>',
    'JSON 须为单行；每项含 id、title、choices（2～5 项，每项 id 与 label）；label 内勿用英文双引号。',
    '除上述各段外不要输出其它前言或后记。',
  ].join('\n')
}

/** 仅用于「生成执行清单」单次请求：不得沿用对话里的 Mermaid/PLAN_* 格式，否则模型会拒写 <<<CHECKLIST>>> */
function buildChecklistGenerationSystemPrompt(intentKey, intentTitle) {
  const scope =
    isCanvasSkillIntent(intentKey)
      ? '每条任务应可执行、可验证。若用户要「程序本体」，清单中应出现脚本工作流（编写/运行/沙箱）相关条目；否则必须围绕 Skill 生成闭环：拆分 Skill 蓝图、定义每个 Skill 的输入输出契约、静态逻辑、质量门、动态触发策略、固化策略、Skill 间数据映射、组合工作流与沙盒校验。普通画布节点只作为 start/end/condition 等控制节点。'
      : intentKey === 'mod'
        ? '每条任务应可落到 Mod 仓库与真实可用闭环：仓库、manifest、行业 JSON、员工名片、employee_pack 登记、workflow_id 绑定、employee 节点 id 匹配、Mock 结构沙盒与非 Mock 真实执行验证。若用户只要草稿骨架，也必须在清单中标明后续成为可执行员工还缺哪些步骤。'
        : '每条任务应可落到员工能力、工具配置与交付物。'
  return [
    `你是 XCAGI 工作台的「执行清单」生成助手。当前制作类型：「${intentTitle}」。`,
    `${scope}`,
    '用户与助手的前文是对话历史；你的**整段回复只允许**输出下面这一块，不要写任何其它字符（不要写「好的」、不要写 mermaid、不要写 <<<PLAN_DETAILS>>>、不要写 <<<PLAN_OPTIONS>>>、不要用 ``` 代码围栏）。',
    '',
    '【必须严格按行输出】',
    '<<<CHECKLIST>>>',
    '1. …',
    '2. …',
    '<<<END>>>',
    '',
    '至少 4 条、建议 6～12 条；中文短句；行首编号必须为「数字 + 英文句点 + 空格」。',
  ].join('\n')
}

function formatPlanMessagesForBrief(msgs) {
  if (!Array.isArray(msgs) || !msgs.length) return ''
  const topicHint = msgs.map((m) => m.content).join(' ')
  return formatFilteredPlanMessagesForBrief(msgs, topicHint)
}

/** 编排前净化员工 handoff brief，去掉 ASR 噪声与占位符 */
function enrichEmployeeHandoffBeforeOrchestration(h) {
  if (!h || h.intentKey !== 'employee') return
  const msgs = Array.isArray(h.planningMessages) && h.planningMessages.length
    ? h.planningMessages
    : voiceMessages.value
  const best = pickBestEmployeeBriefFromVoice(voiceSessionState.value, msgs)
  const topicHint = [best, h.description, ...msgs.map((m) => m.content)].join(' ')
  const qaText = formatFilteredPlanMessagesForBrief(msgs, topicHint)
  const initialFromDesc = String(h.description || '').split('【澄清对话】')[0].replace('【初始想法】', '').trim()
  const initial = best || initialFromDesc || String(h.description || '').trim()
  h.employeeRoutingBrief = initial.slice(0, 200)
  const descChunks = [`【初始想法】\n${initial}`]
  if (qaText) descChunks.push(`【澄清对话】\n${qaText}`)
  const checklistMatch = String(h.description || '').match(/【执行清单】\s*([\s\S]*)$/)
  if (checklistMatch?.[1]?.trim()) {
    descChunks.push(`【执行清单】\n${checklistMatch[1].trim()}`)
  } else if (Array.isArray(h.executionChecklist) && h.executionChecklist.length) {
    descChunks.push(
      `【执行清单】\n${h.executionChecklist.map((l, i) => `${i + 1}. ${l}`).join('\n')}`,
    )
  }
  h.planningContext = descChunks.join('\n\n---\n\n')
  h.description = h.planningContext
}

/** 规划面板：把 nginx 504 HTML 等转成可读中文，避免整页 HTML 贴在 planError 里 */
function friendlyPlanPanelApiError(err) {
  const raw = err && typeof err === 'object' && 'message' in err ? String(err.message) : String(err || '')
  const s = raw.trim()
  if (!s) return '请求失败，请稍后重试。'
  if (/504|Gateway Time-out|网关超时/i.test(s) || /<title>\s*504/i.test(s)) {
    return '网关超时（504）：最前面的 nginx 在超时时间内没等到后端返回就断开了连接。需求规划调用模型往往较慢，请在对外提供站点的那台 nginx 里为 /api/ 增大 proxy_read_timeout、proxy_send_timeout（建议 3600s），nginx -t 后 reload；若直连本机 API 正常而域名访问 504，说明问题在这一层反代。仓库示例见 market/nginx.conf、docs/nginx-https-example.conf。'
  }
  if (/<\s*html[\s>]/i.test(s)) {
    return '服务器返回了 HTML 错误页（多为反代或网关层），请在浏览器网络面板查看该请求的 HTTP 状态码，并检查 nginx 与 modstore 服务日志。'
  }
  return s.length > 900 ? `${s.slice(0, 900)}…` : s
}

function _checklistBodyToResult(body) {
  const lines = String(body || '')
    .split(/\r?\n/)
    .map((l) => l.replace(/^\s*\d+[\.)]\s*/, '').trim())
    .filter((l) => l && !/^<<<[\s\S]*>>>$/.test(l))
  if (!lines.length) return null
  const text = lines.map((l, i) => `${i + 1}. ${l}`).join('\n')
  return { text, lines }
}

/** 模型漏写结束标签时：取文末连续「数字. 」行作为清单（仅当正文含 <<<CHECKLIST>>> 时由上层调用） */
function parseChecklistNumberedTail(raw) {
  const lines = String(raw || '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  while (lines.length && /^```/.test(lines[lines.length - 1])) {
    lines.pop()
  }
  const collected = []
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const l = lines[i]
    if (/^\d+[\.)]\s+\S/.test(l)) {
      collected.unshift(l.replace(/^\d+[\.)]\s+/, '').trim())
    } else if (collected.length) {
      break
    }
  }
  if (collected.length < 2) return null
  return _checklistBodyToResult(collected.join('\n'))
}

function parseChecklistBlock(raw) {
  let s = String(raw || '').trim()
  const fullFence = s.match(/^```(?:\w*)?\s*\n([\s\S]*?)\n```\s*$/m)
  if (fullFence) s = fullFence[1].trim()
  const mer = s.match(/```mermaid\s*[\s\S]*?```/i)
  if (mer) s = s.replace(mer[0], '')
  const pd = s.match(/<<<PLAN_DETAILS>>>([\s\S]*?)<<<END_PLAN_DETAILS>>>/i)
  if (pd) s = s.replace(pd[0], '')
  const po = s.match(/<<<PLAN_OPTIONS>>>([\s\S]*?)<<<END_PLAN_OPTIONS>>>/i)
  if (po) s = s.replace(po[0], '')
  s = s.replace(/<<<\s*CHECKLIST\s*>>>/gi, '<<<CHECKLIST>>>')
  s = s.replace(/<<<\s*END\s*CHECKLIST\s*>>>/gi, '<<<END>>>')
  s = s.replace(/<<<\s*END_CHECKLIST\s*>>>/gi, '<<<END>>>')
  s = s.replace(/<<<\s*END\s*>>>/gi, '<<<END>>>')
  const tryBodies = []
  let m = s.match(/<<<CHECKLIST>>>([\s\S]*?)<<<END>>>/i)
  if (m) tryBodies.push(m[1])
  if (!tryBodies.length) {
    m = s.match(/<<<CHECKLIST>>>([\s\S]*?)$/im)
    if (m) tryBodies.push(m[1])
  }
  for (const body of tryBodies) {
    const r = _checklistBodyToResult(body)
    if (r) return r
  }
  if (/<<<CHECKLIST>>>/i.test(s)) {
    const t = parseChecklistNumberedTail(s)
    if (t) return t
  }
  return null
}

function _providerRowHasUsableKey(row, fernetOk) {
  if (!row) return false
  if (row.provider === 'xiaomi' && row.has_platform_key) return true
  if (row.has_user_override && fernetOk) return true
  return false
}

const RESOLVE_CHAT_CACHE_MS = 5 * 60 * 1000
let resolveChatCache: { at: number; mode: string; provider: string; model: string } | null = null

/**
 * Auto 模式：优先请求服务端 /resolve-chat-default（与 /chat 共用 resolve_api_key），
 * 避免前端 /status + 目录推断与后端不一致；失败时再回退到本地推断。
 */
async function resolveChatProviderModel() {
  if (modelMode.value === 'manual') {
    resolveChatCache = null
    if (!selectedProvider.value || !selectedModel.value) {
      throw new Error('自选模式下请选择厂商与模型')
    }
    return { provider: selectedProvider.value, model: selectedModel.value }
  }
  const modeKey = 'auto'
  if (
    resolveChatCache &&
    resolveChatCache.mode === modeKey &&
    Date.now() - resolveChatCache.at < RESOLVE_CHAT_CACHE_MS
  ) {
    return { provider: resolveChatCache.provider, model: resolveChatCache.model }
  }
  if (localStorage.getItem('modstore_token')) {
    try {
      const resolved = await api.llmResolveChatDefault()
      const rp = typeof resolved?.provider === 'string' ? resolved.provider.trim() : ''
      const rm = typeof resolved?.model === 'string' ? resolved.model.trim() : ''
      if (rp && rm) {
        resolveChatCache = { at: Date.now(), mode: modeKey, provider: rp, model: rm }
        return { provider: rp, model: rm }
      }
    } catch (e) {
      const msg = e?.message || String(e)
      if (/404|Not Found/i.test(msg)) {
        /* 旧服务端无此路由时回退到下方本地推断 */
      } else {
        throw e
      }
    }
  }
  if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
    await loadLlmCatalogForWorkbench()
  }
  const pref = llmCatalog.value?.preferences || {}
  let p = typeof pref.provider === 'string' ? pref.provider.trim() : ''
  let m = typeof pref.model === 'string' ? pref.model.trim() : ''
  if (!p || !m) {
    throw new Error('请先在 LLM 设置中选择默认模型，或切换到「自选」')
  }

  let statusPayload
  try {
    statusPayload = await api.llmStatus()
  } catch {
    statusPayload = null
  }
  const fernetOk = Boolean(statusPayload?.fernet_configured)
  const rows = Array.isArray(statusPayload?.providers) ? statusPayload.providers : []
  const rowP = rows.find((r) => r.provider === p)

  if (!_providerRowHasUsableKey(rowP, fernetOk)) {
    const withModels = rows.filter((r) => {
      if (!_providerRowHasUsableKey(r, fernetOk)) return false
      const b = llmCatalog.value?.providers?.find((x) => x.provider === r.provider)
      return b && Array.isArray(b.models) && b.models.length
    })
    const fallback = withModels[0] || rows.find((r) => _providerRowHasUsableKey(r, fernetOk))
    if (!fallback) {
      if (!fernetOk && rows.some((r) => r.has_user_override)) {
        throw new Error(
          '已保存 BYOK，但服务端未配置 MODSTORE_LLM_MASTER_KEY，无法解密使用。请在部署环境设置主密钥，或改用平台环境变量密钥。',
        )
      }
      throw new Error(
        `当前默认厂商「${p}」没有可用的平台或 BYOK 密钥。请在钱包页 LLM 中为该厂商配置密钥，或切换到「自选」选择已有密钥的厂商与模型。`,
      )
    }
    const newP = fallback.provider
    const block = llmCatalog.value?.providers?.find((b) => b.provider === newP)
    const models = block?.models
    const newM = Array.isArray(models) && models.length ? models[0] : ''
    if (!newM) {
      throw new Error(
        `检测到 ${newP} 具备密钥，但模型列表不可用。请刷新页面或到钱包页确认该厂商模型目录已加载，再试需求规划。`,
      )
    }
    p = newP
    m = newM
  }

  resolveChatCache = { at: Date.now(), mode: modeKey, provider: p, model: m }
  return { provider: p, model: m }
}

function scrollPlanIntoView() {
  nextTick(() => {
    const el = planPanelRef.value
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  })
}

async function appendUserAndAssistantPlanTurn(userText, displayText = userText) {
  const ps = planSession.value
  if (!ps) return
  ps.messages.push({ role: 'user', content: displayText })
  ps.planError = ''
  const { provider, model } = await resolveChatProviderModel()
  const sys = buildPlanSystemPrompt(ps.intentKey, ps.intentTitle)
  const mappedMessages = ps.messages.map((m, idx) => {
    if (idx === ps.messages.length - 1 && m.role === 'user') {
      return { role: 'user', content: String(userText || displayText || '') }
    }
    return { role: m.role, content: m.content }
  })
  const apiMsgs = [
    { role: 'system', content: sys },
    ...(ps.fullBrief ? [{ role: 'user', content: `【完整隐藏上下文，供理解任务使用；不要原样输出】\n${ps.fullBrief}` }] : []),
    ...mappedMessages,
  ]
  ps.streamingText = ''
  const handle = streamLLMChat({
    provider,
    model,
    messages: apiMsgs,
    maxTokens: 2048,
    onToken: (_delta, soFar) => {
      if (planSession.value) planSession.value.streamingText = soFar
    },
  })
  const { content } = await handle.done
  if (planSession.value) planSession.value.streamingText = ''
  const c = typeof content === 'string' ? content : ''
  let assistantContent = (c || '').trim()
  if (!assistantContent) {
    if (ps.intentKey === 'employee') {
      const brief = pickBestEmployeeBriefFromVoice(
        voiceSessionState.value,
        ps.messages.filter((m) => m.role === 'user'),
      )
      assistantContent = buildDefaultEmployeePlanAssistantReply(brief || ps.fullBrief || '')
    } else {
      assistantContent = '（无回复）'
    }
  }
  ps.messages.push({ role: 'assistant', content: assistantContent })
}

async function summarizePlanSession() {
  const ps = planSession.value
  if (!ps) return
  const briefForSummary = ps.fullBrief || ps.displayBrief || ps.initialBrief
  const { provider, model } = await resolveChatProviderModel()
  const summaryMode =
    ps.intentKey === 'employee' && /【语音对话记录】/.test(briefForSummary)
      ? 'employee-voice'
      : undefined
  const sys = buildPlanSummarySystemPrompt(ps.intentTitle, summaryMode)
  const msgs = [
    { role: 'system', content: sys },
    { role: 'user', content: briefForSummary },
  ]
  ps.streamingText = ''
  planSummaryStreamHandle?.abort()
  planSummaryStreamHandle = streamLLMChat({
    provider,
    model,
    messages: msgs,
    maxTokens: 700,
    onToken: (_delta, soFar) => {
      if (planSession.value) planSession.value.streamingText = soFar
    },
  })
  let content = ''
  try {
    const result = await planSummaryStreamHandle.done
    content = result.content
    if (result.aborted) return
  } finally {
    planSummaryStreamHandle = null
  }
  if (planSession.value) planSession.value.streamingText = ''
  const parsed = parsePlanSummary(content, ps.displayBrief || ps.fullBrief)
  ps.summaryTitle = parsed.title
  ps.summaryText = parsed.summary
  ps.summaryNeedsClarification = isSummaryNeedsClarification(parsed.title, parsed.summary)
  ps.initialBrief = `${parsed.title}\n${parsed.summary}`
}

async function openPlanSession(input) {
  planSurfaceKey.value += 1
  const effectiveIntent = composerIntent.value || CANVAS_SKILL_INTENT
  const meta = INTENT_META[effectiveIntent] || INTENT_META.workflow
  const fullBrief = typeof input === 'object' && input ? String(input.fullBrief || '') : String(input || '')
  const displayBrief = typeof input === 'object' && input ? String(input.displayBrief || '') : compactPlanVisibleText(fullBrief)
  planSession.value = {
    intentKey: effectiveIntent,
    intentTitle: meta.title,
    phase: 'summary',
    initialBrief: displayBrief,
    fullBrief,
    displayBrief,
    generateFrontend: effectiveIntent === 'mod' ? input?.generateFrontend !== false : false,
    summaryTitle: '',
    summaryText: '',
    summaryNeedsClarification: false,
    files: Array.isArray(input?.files) ? input.files : [],
    messages: [],
    checklistText: '',
    checklistLines: [],
    planError: '',
    loading: true,
    streamingText: '',
  }
  draft.value = ''
  planReplyDraft.value = ''
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  finalizeError.value = ''
  await nextTick()
  scrollPlanIntoView()
  try {
    await summarizePlanSession()
  } catch (e) {
    const aborted =
      (e as Error)?.name === 'AbortError' ||
      String((e as Error)?.message || e).toLowerCase().includes('abort')
    if (aborted) return
    if (planSession.value) {
      const fallback = parsePlanSummary('', displayBrief || fullBrief)
      planSession.value.summaryTitle = fallback.title
      planSession.value.summaryText = fallback.summary
      planSession.value.summaryNeedsClarification = isSummaryNeedsClarification(fallback.title, fallback.summary)
      planSession.value.initialBrief = `${fallback.title}\n${fallback.summary}`
      planSession.value.planError = `摘要生成失败，已使用输入内容兜底：${friendlyPlanPanelApiError(e)}`
    }
  } finally {
    if (planSession.value) planSession.value.loading = false
  }
}

function backSummaryToComposer() {
  const ps = planSession.value
  if (ps?.displayBrief) draft.value = ps.displayBrief
  dismissPlanSession()
  nextTick(() => {
    const el = inputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}

async function confirmSummaryAndStartPlanning() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'summary' || ps.loading) return
  ps.phase = 'chat'
  ps.messages = []
  ps.planError = ''
  ps.loading = true
  directAttachedFiles.value = []
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  const visible = `已确认任务：${ps.summaryTitle || '任务摘要'}\n${ps.summaryText || ps.displayBrief || ''}`
  try {
    await appendUserAndAssistantPlanTurn(ps.fullBrief || ps.displayBrief || ps.summaryText, visible)
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
    ps.messages = []
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}

/** 自主生成：无 LLM 澄清回合时注入默认理解，避免卡在「澄清回合不足」 */
function ensureAutoPilotReadyChatTurns(useDefault = false) {
  const ps = planSession.value
  if (!ps || ps.phase !== 'chat') return
  if ((ps.messages?.length || 0) >= 2) return
  if (!useDefault) return
  const isEmployee = ps.intentKey === 'employee'
  let brief = ''
  if (isEmployee) {
    brief = pickBestEmployeeBriefFromVoice(voiceSessionState.value, voiceMessages.value)
    if (!brief) {
      brief = String(ps.fullBrief || ps.summaryText || ps.displayBrief || '').trim().slice(0, 2000)
    }
  } else {
    brief = String(ps.fullBrief || ps.summaryText || ps.displayBrief || '').trim().slice(0, 2000)
  }
  if (!ps.messages.length) {
    ps.messages.push({ role: 'user', content: brief || '按前述语音需求继续' })
  }
  ps.messages.push({
    role: 'assistant',
    content: isEmployee
      ? buildDefaultEmployeePlanAssistantReply(brief)
      : [
          `已确认任务：${ps.summaryTitle || '员工包'}`,
          ps.summaryText || brief,
          '',
          '未决细节按默认方案：图片单独存储；格式保留标题层级与表格结构；适用通用 Word 文档场景。',
        ]
          .filter(Boolean)
          .join('\n'),
  })
}

function fastEnterChatForAutoPilot() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'summary') return
  ps.phase = 'chat'
  ps.messages = []
  ps.planError = ''
  ps.loading = false
  directAttachedFiles.value = []
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  ensureAutoPilotReadyChatTurns(true)
  scrollPlanIntoView()
}

/**
 * 「AI 自主全部进行」：从 summary 阶段一路串到后端编排完成。
 * 流程：confirmSummaryAndStartPlanning → 自动答快捷题（如有） →
 * requestExecutionChecklist → confirmPlanAndOpenHandoff → runOrchestration。
 * 任一步失败：把可读错误写入 autoPilotError，停在当前阶段，让用户手动接管。
 */
async function runAutoPilotFromSummary(opts?: { force?: boolean }) {
  const ps0 = planSession.value
  if (!ps0 || ps0.phase !== 'summary' || ps0.loading) return
  if (autoPilotRunning.value) return
  if (!ps0.summaryText) return
  if (!opts?.force && ps0.summaryNeedsClarification) return
  autoPilotRunning.value = true
  autoPilotError.value = ''
  try {
    if (opts?.force) {
      fastEnterChatForAutoPilot()
    } else {
      await confirmSummaryAndStartPlanning()
      let ps = planSession.value
      if (!ps || ps.phase !== 'chat') {
        throw new Error('未能进入澄清阶段')
      }
      if (ps.planError) throw new Error(ps.planError)

      await nextTick()
      if (planQuickOptions.value.length) {
        autoPickPlanQuickOptions()
        await nextTick()
        if (canSendPlanQuickPicks.value) {
          await sendPlanReplyFromQuickPicks()
        }
        ps = planSession.value
        if (ps?.planError) throw new Error(ps.planError)
      }
    }

    let ps = planSession.value
    if (!ps || ps.phase !== 'chat') {
      throw new Error('澄清阶段已被打断')
    }
    ensureAutoPilotReadyChatTurns(Boolean(opts?.force))
    if ((ps.messages?.length || 0) < 2) {
      throw new Error('澄清回合不足，无法生成执行清单')
    }

    await requestExecutionChecklist()
    ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')
    if (ps.planError) throw new Error(ps.planError)
    if (ps.phase !== 'checklist') throw new Error('未能生成执行清单')

    confirmPlanAndOpenHandoff()
    await nextTick()
    if (!pendingHandoff.value) throw new Error('未能生成制作草稿')

    await runOrchestration()
    if (finalizeError.value) throw new Error(finalizeError.value)
  } catch (e) {
    autoPilotError.value = friendlyPlanPanelApiError(e)
  } finally {
    autoPilotRunning.value = false
  }
}

/** 规划面板已在「需求澄清」阶段时，用户说「开始写吧」等口令 → 自动跑完清单与生成 */
async function runAutoPilotFromChat() {
  const ps0 = planSession.value
  if (!ps0 || ps0.phase !== 'chat' || ps0.loading) return
  if (autoPilotRunning.value) return
  autoPilotRunning.value = true
  autoPilotError.value = ''
  try {
    let ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')

    if ((ps.messages?.length || 0) < 2) {
      await nextTick()
      if (planQuickOptions.value.length) {
        autoPickPlanQuickOptions()
        await nextTick()
        if (canSendPlanQuickPicks.value) {
          await sendPlanReplyFromQuickPicks()
        }
      }
      ps = planSession.value
      if (ps && (ps.messages?.length || 0) < 2) {
        planReplyDraft.value = '按前面描述的需求继续，默认方案即可。'
        await sendPlanReply()
      }
    }

    ps = planSession.value
    if (!ps || ps.phase !== 'chat') throw new Error('澄清阶段已被打断')
    if (ps.planError) throw new Error(ps.planError)
    ensureAutoPilotReadyChatTurns(true)
    if ((ps.messages?.length || 0) < 2) {
      throw new Error('澄清回合不足，无法生成执行清单')
    }

    await requestExecutionChecklist()
    ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')
    if (ps.planError) throw new Error(ps.planError)
    if (ps.phase !== 'checklist') throw new Error('未能生成执行清单')

    confirmPlanAndOpenHandoff()
    await nextTick()
    if (!pendingHandoff.value) throw new Error('未能生成制作草稿')

    await runOrchestration()
    if (finalizeError.value) throw new Error(finalizeError.value)
  } catch (e) {
    autoPilotError.value = friendlyPlanPanelApiError(e)
  } finally {
    autoPilotRunning.value = false
  }
}

function pickPlanOption(qid, cid) {
  planOptionSelections.value = { ...planOptionSelections.value, [qid]: cid }
}

/** 每道快捷题选中第一个选项（非「其他」），便于快速填表后再微调 */
function autoPickPlanQuickOptions() {
  const ps = planSession.value
  if (!ps || ps.loading || ps.phase !== 'chat') return
  const opts = planQuickOptions.value
  if (!opts.length) return
  clearPlanOptionOtherText()
  const sel = { ...planOptionSelections.value }
  for (const q of opts) {
    const first = q.choices?.[0]
    if (first?.id) sel[q.id] = first.id
  }
  planOptionSelections.value = sel
}

async function submitPlanUserMessage(userText) {
  const ps = planSession.value
  const t = String(userText || '').trim()
  if (!t || !ps || ps.loading || ps.phase !== 'chat') return
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  ps.loading = true
  ps.planError = ''
  try {
    await appendUserAndAssistantPlanTurn(t)
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
    if (ps.messages.length && ps.messages[ps.messages.length - 1].role === 'user') {
      ps.messages.pop()
    }
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}

async function sendPlanReply() {
  const t = planReplyDraft.value.trim()
  if (!t) return
  planReplyDraft.value = ''
  await submitPlanUserMessage(t)
}

async function sendPlanReplyFromQuickPicks() {
  const opts = planQuickOptions.value
  if (!opts.length || !canSendPlanQuickPicks.value) return
  const sel = planOptionSelections.value
  const lines = []
  for (const q of opts) {
    const cid = sel[q.id]
    if (cid === PLAN_OPTION_OTHER_ID) {
      lines.push(`【${q.title}】${String(planOptionOtherText[q.id] || '').trim()}`)
    } else {
      const c = (q.choices || []).find((x) => x.id === cid)
      lines.push(`【${q.title}】${c ? c.label : cid}`)
    }
  }
  await submitPlanUserMessage(lines.join('\n'))
}

async function requestExecutionChecklist() {
  const ps = planSession.value
  if (!ps || ps.loading || ps.phase !== 'chat') return
  if (ps.messages.length < 2) {
    ps.planError = '请先与助手完成至少一轮问答，再生成执行清单。'
    return
  }
  ps.loading = true
  ps.planError = ''
  try {
    const { provider, model } = await resolveChatProviderModel()
    const sys = buildChecklistGenerationSystemPrompt(ps.intentKey, ps.intentTitle)
    const tail = {
      role: 'user',
      content: [
        '请根据以上整段对话，输出一份可直接照着实现的「执行清单」。',
        '',
        '只输出下面这一块，不要前言、不要后记；不要用 markdown 代码围栏（不要用 ```）包住整块；不要输出 mermaid；不要输出 <<<PLAN_DETAILS>>> / <<<PLAN_OPTIONS>>>。',
        '',
        '必须严格使用这三行作为头尾标记（尖括号与单词一致）：',
        '<<<CHECKLIST>>>',
        '1. 第一条任务（一行一条，行首为数字+英文句点+空格）',
        '2. 第二条任务',
        '（按需继续编号）',
        '<<<END>>>',
        '',
        '注意：结束标记必须是单独的 <<<END>>>（与需求规划里其它 <<<END_…>>> 不同），否则系统无法解析。',
      ].join('\n'),
    }
    const apiMsgs = [
      { role: 'system', content: sys },
      ...(ps.fullBrief ? [{ role: 'user', content: `【完整隐藏上下文，供生成清单使用；不要原样输出】\n${ps.fullBrief}` }] : []),
      ...ps.messages.map((m) => ({ role: m.role, content: m.content })),
      tail,
    ]
    ps.streamingText = ''
    const handle = streamLLMChat({
      provider,
      model,
      messages: apiMsgs,
      maxTokens: 6144,
      onToken: (_delta, soFar) => {
        if (planSession.value) planSession.value.streamingText = soFar
      },
    })
    const { content } = await handle.done
    if (planSession.value) planSession.value.streamingText = ''
    const raw = typeof content === 'string' ? content : ''
    const parsed = parseChecklistBlock(raw)
    if (!parsed) {
      ps.planError =
        '未能解析清单：请确认模型输出含 <<<CHECKLIST>>> 与 <<<END>>>（勿用 ``` 包裹），且至少两条编号任务；仍失败可把清单要点再发一轮对话后重试「生成执行清单」。'
      return
    }
    ps.checklistText = parsed.text
    ps.checklistLines = parsed.lines
    ps.phase = 'checklist'
    voiceChecklistPaused.value = false
    if (
      wbSidebar.activeMode === 'voice' &&
      ps.intentKey === 'employee' &&
      composerIntent.value === 'employee' &&
      !autoPilotRunning.value
    ) {
      void scheduleVoiceChecklistAutoStart()
    }
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}

/** 语音做员工：清单生成后自动确认并开跑（避免停在清单页等口令） */
async function scheduleVoiceChecklistAutoStart() {
  await nextTick()
  const ps = planSession.value
  if (!ps || ps.phase !== 'checklist' || ps.intentKey !== 'employee') return
  if (
    voiceChecklistPaused.value ||
    autoPilotRunning.value ||
    finalizeLoading.value ||
    orchestrationSessionId.value
  ) {
    return
  }
  await confirmEmployeeChecklistAndRunFromVoice()
}

function backPlanToChat() {
  const ps = planSession.value
  if (!ps) return
  ps.phase = 'chat'
  ps.checklistText = ''
  ps.checklistLines = []
  ps.planError = ''
}

function confirmPlanAndOpenHandoff() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'checklist') return
  const isEmployee = ps.intentKey === 'employee'
  const topicHint = [ps.initialBrief, ps.fullBrief, ...ps.messages.map((m) => m.content)].join(' ')
  const qaText = formatFilteredPlanMessagesForBrief(ps.messages, topicHint)
  let initialChunk = ps.initialBrief
  let employeeBrief = ''
  if (isEmployee) {
    employeeBrief = pickBestEmployeeBriefFromVoice(
      voiceSessionState.value,
      voiceMessages.value.length ? voiceMessages.value : ps.messages,
    )
    if (employeeBrief) {
      initialChunk = [(ps.summaryTitle || '').trim(), employeeBrief].filter(Boolean).join('\n')
    }
  }
  const descChunks = [`【初始想法】\n${initialChunk}`]
  if (qaText) descChunks.push(`【澄清对话】\n${qaText}`)
  descChunks.push(`【执行清单】\n${ps.checklistText}`)
  const description = descChunks.join('\n\n---\n\n')
  const ik = ps.intentKey
  const defaultName =
    (ps.summaryTitle || '').trim() ||
    suggestModIdFromText(`${ps.initialBrief}\n${ps.checklistText}`)
  pendingHandoff.value = {
    description,
    employeeRoutingBrief: isEmployee ? (employeeBrief || ps.initialBrief || '').slice(0, 200) : undefined,
    planningContext: description,
    intentTitle: ps.intentTitle,
    intentKey: ik,
    workflowName: isCanvasSkillIntent(ik) ? defaultName : '',
    planNotes: isCanvasSkillIntent(ik) ? ps.checklistText : '',
    suggestedModId: ik === 'mod' ? suggestModIdFromText(`${ps.initialBrief}\n${ps.checklistText}`) : '',
    files: Array.isArray(ps.files) ? ps.files : [],
    generateFrontend: ik === 'mod' ? modFrontendEnabled.value : false,
    planningMessages: Array.isArray(ps.messages) ? ps.messages.map((m) => ({ role: m.role, content: m.content })) : [],
    executionChecklist: Array.isArray(ps.checklistLines) ? [...ps.checklistLines] : [],
    sourceDocuments: Array.isArray(ps.files)
      ? ps.files.map((f) => ({ name: String(f?.name || ''), size: Number(f?.size || 0), type: String(f?.type || '') }))
      : [],
    employeeTarget: ik === 'employee' ? 'pack_only' : 'pack_only',
    employeeWorkflowName: ik === 'employee' ? defaultName : '',
    fhdBaseUrl: '',
  }
  ps.phase = 'done'
  ps.planError = ''
  nextTick(() => {
    void scrollMakeFlowToEnd()
  })
}

async function submitDraft() {
  const text = draft.value.trim()
  if ((!text && directAttachedFiles.value.length === 0) || !hasWorkflow.value) return
  if (!requireLoginForWorkbenchUse()) return
  if (
    shouldHandleAsOfficeTask(text, directAttachedFiles.value, planSession.value) &&
    !platformChatMode.value
  ) {
    directDraft.value = text || directDraft.value
    draft.value = ''
    await sendDirectChat(text || directDraft.value.trim())
    return
  }
  if (platformChatMode.value) {
    directDraft.value = text
    draft.value = ''
    await sendDirectChat(text)
    return
  }
  if (directAttachedFiles.value.some((f) => f.status === 'uploading')) {
    knowledgeError.value = '附件仍在读取中，请稍候'
    return
  }
  if (planSession.value?.phase === 'chat') return
  if (planSession.value && planSession.value.phase !== 'done') {
    finalizeError.value = '请先完成或关闭上方的「需求规划」面板。'
    return
  }
  if (pendingHandoff.value || finalizeLoading.value || makeCompletionResult.value) {
    finalizeError.value = '请先完成当前制作任务，或点击完成卡片中的「开始新任务」。'
    return
  }
  finalizeError.value = ''
  const filesSnapshot = [...directAttachedFiles.value]
  const note = directAttachmentNote(filesSnapshot)
  const inlineBlocks = filesSnapshot
    .filter((f: any) => (f.status === 'inline' || f.status === 'ready') && f.extractedText)
    .map((f: any, idx: number) => `### @附件${idx + 1}：${f.name}\n\n${f.extractedText}`)
    .join('\n\n---\n\n')
  let knowledgePack = ''
  if (text && isEmbeddingConfigured()) {
    try {
      const embeddingChoice = await resolveChatProviderModel()
      const res = await api.knowledgeSearch(text, 6, {
        embeddingProvider: embeddingChoice.provider,
        embeddingModel: embeddingChoice.model,
      })
      knowledgePack = formatKnowledgeContext(res?.items)
    } catch (e) {
      knowledgeError.value = e?.message || String(e)
    }
  }
  const payloadParts = [text]
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const wantsModFrontend = intent === 'mod' && modFrontendEnabled.value
  if (intent === 'mod') {
    payloadParts.push(
      wantsModFrontend
        ? '【制作选项】本次需要为 Mod 生成可路由的定制 Vue 前端页面，并在 manifest.frontend.menu 中暴露入口。'
        : '【制作选项】本次暂不生成定制前端，只保留 Mod 骨架、员工和工作流能力。',
    )
  }
  if (note) payloadParts.push(note)
  if (inlineBlocks) {
    payloadParts.push(`【本次上传附件全文】\n用户按上传顺序提供了以下文件；@附件1、@附件2 等编号与上方附件顺序一致，请按编号理解文件之间的先后逻辑。\n\n${inlineBlocks}`)
  }
  if (knowledgePack) payloadParts.push(`【我的文件资料库命中片段】\n${knowledgePack}`)
  const payload = payloadParts.filter(Boolean).join('\n\n---\n')
  const displayPayload = [text, note].filter(Boolean).join('\n\n')
  await openPlanSession({
    fullBrief: payload,
    displayBrief: displayPayload,
    files: filesSnapshot.map((f: any) => f.file).filter(Boolean),
    generateFrontend: wantsModFrontend,
  })
}

async function onComposerSendClick() {
  if (planSession.value?.phase === 'chat') {
    await sendPlanReply()
    return
  }
  await submitDraft()
}

function onComposerKeydown(e) {
  if (e.key !== 'Enter' || e.shiftKey) return
  const ps = planSession.value
  if (ps?.phase === 'chat') {
    e.preventDefault()
    void sendPlanReply()
    return
  }
  if (ps) return
  e.preventDefault()
  void submitDraft()
}

const coverageHooks = {
  __setRef(key: string, value: unknown) {
    if (key === 'planOptionOtherText') {
      Object.assign(planOptionOtherText, value && typeof value === 'object' ? value : {})
      return true
    }
    if (key === 'planDiagramPreviewOpen') {
      planDiagramPreviewIdx.value = value ? 0 : null
      return true
    }
    if (key === 'planDiagramPreviewScale') {
      planPreviewScale.value = Number(value) || 1
      return true
    }
    if (key === 'planDiagramPreviewTranslate' && value && typeof value === 'object') {
      const v = value as { x?: number; y?: number }
      planPreviewTx.value = Number(v.x) || 0
      planPreviewTy.value = Number(v.y) || 0
      return true
    }
    const refs: Record<string, { value: any }> = {
      activeBotId,
      activeConversationId,
      allBots,
      autoPilotError,
      autoPilotRunning,
      composerIntent,
      contentEnter,
      conversations,
      directChatEmployeeId,
      directDraft,
      directEmployeeOptions,
      directGeneratedFiles,
      directGeneratingFile,
      directVoiceAudioLevel,
      directVoiceListening,
      directVoicePermissionHint,
      directVoiceRecognizing,
      directAttachedFiles,
      directError,
      directImageCount,
      directImageGenEnabled,
      directImageSize,
      directImageStyle,
      directLoading,
      directMediaGenerating,
      directSendPending,
      directVideoAspect,
      directVideoDurationSec,
      directVideoGenEnabled,
      directWebSearchEnabled,
      draft,
      empDropdownOpen,
      empPanelOpen,
      finalizeError,
      finalizeLoading,
      knowledgeDocs,
      knowledgeError,
      knowledgeStatus,
      knowledgeUploading,
      linkBusy,
      linkError,
      linkModId,
      linkMods,
      llmCatalog,
      llmDdOpen,
      llmMobileSheetOpen,
      makeCompletionResult,
      makeVoiceListening,
      makeVoicePermissionHint,
      makeVoiceRecognizing,
      modelMode,
      orchPhase,
      orchestrationEtaReason,
      orchestrationEtaSeconds,
      orchestrationSession,
      orchestrationSessionId,
      pendingHandoff,
      personalSettings,
      planDiagramError,
      planDiagramPreviewIdx,
      planDiagramPreviewMountRef,
      planDiagramPreviewViewportRef,
      planOptionSelections,
      planReplyDraft,
      planSession,
      planPreviewScale,
      planPreviewTx,
      planPreviewTy,
      platformChatMode,
      pollStop,
      selectedModel,
      selectedProvider,
      showAgentMarket,
      showMediaGen,
      showVoicePhone,
      tierPanelOpen,
      titleEnterDone,
      ttsAutoRead,
      voiceAudioLevel,
      voiceCasualChatMode,
      voiceError,
      voiceMessages,
      voiceMicFallbackHint,
      voiceReport,
      voiceState,
      waveformCanvas,
      workflowLinkOffer,
    }
    const target = refs[key]
    if (!target) return false
    target.value = value
    return true
  },
  appendVoiceUserTurn,
  applyDirectReadEmployeePick,
  closePlanDiagramPreview,
  buildDirectAttachItem,
  canSpeculateForPartial,
  clearPlanOptionOtherText,
  clearPlanDiagramPreviewPointerListeners,
  confirmSummaryAndStartPlanning,
  customerServiceQueryContext,
  directAttachmentKind,
  directAttachmentKindLabel,
  directAttachmentNote,
  directAttachmentStatusText,
  directFileChipTitle,
  drawDirectWaveform,
  drawWaveform,
  formatBytes,
  formatDirectChatError,
  formatEmbeddingLabel,
  formatKnowledgeContext,
  isCanvasSkillIntent,
  isEmbeddingConfigured,
  onPlanDiagramPreviewPointerDown,
  onPlanDiagramPreviewWheel,
  openPlanDiagramPreview,
  parsePlanSummary,
  persistManualLlmIfNeeded,
  planDiagramPreviewFitView,
  planDiagramPreviewZoomStep,
  pollWorkbenchSession,
  readStoredConsumptionTier,
  requestExecutionChecklist,
  resolveDirectFileEmployeeId,
  resolveChatProviderModel,
  retryOrchStep,
  runAutoPilotFromChat,
  runAutoPilotFromSummary,
  runOrchestration,
  applyCustomerServiceRouteContext,
  applyMakeCompletion,
  applyStarterPrompt,
  applyWbGearFromRoute,
  autoPickPlanQuickOptions,
  backPlanToChat,
  backSummaryToComposer,
  cancelEditUserMessage,
  closeEmployeeSixDimModal,
  commitEditedUserMessage,
  confirmPlanAndOpenHandoff,
  confirmWorkflowModLink,
  deleteKnowledgeDocument,
  dismissHomeBodyOverlays,
  dispatchVoiceUtterance,
  downloadGeneratedOutput,
  ensureVoiceListening,
  fileExtension,
  fileKind,
  fileKindClass,
  fileKindLabel,
  handleDirectChatAuthFailure,
  handleVoicePlanReplySmart,
  handleVoiceUtteranceReady,
  loadDirectEmployeeOptions,
  loadLinkMods,
  markDirectFirstToken,
  onComposerKeydown,
  onComposerPaste,
  onKnowledgeDragEnter,
  onKnowledgeDragLeave,
  onKnowledgeDrop,
  onKnowledgeFileChange,
  onRemoveAgent,
  onStartWithAgent,
  openEmployeeSixDimModal: tryOpenEmployeeSixDimModal,
  openKnowledgeFilePicker,
  openMakeCompletionPrimary,
  openMakeCompletionSecondary,
  openSixDimTestPreview,
  openWorkflowCanvasOnly,
  pickPlanOption,
  pushDirectGeneratedDownloads,
  regenerateAssistant,
  removeDirectAttachedFile,
  removeDirectGeneratedFile,
  resetMakeComposer,
  retrieveKnowledgeForDirect,
  retrieveWebForDirect,
  runDirectChatTurn,
  runDirectEmployeeReadForLlm,
  runDirectOfficeGeneratePhase,
  runVoiceChatTurn,
  runVoiceS2STurn,
  sendDirectChat,
  sendPlanReplyFromQuickPicks,
  setFilePurpose,
  speakTextAndListen,
  startEditUserMessage,
  startInlineVoice,
  startSpeculativeVoiceTurn,
  stopGeneration,
  submitDraft,
  switchMakeIntent,
  toggleDirectImageGen,
  toggleDirectVideoGen,
  toggleDirectWebSearch,
  toggleEmpPanel,
  togglePlatformChatMode,
  toggleTierPanel,
  triggerVoiceBargeIn,
  tryOpenEmployeeSixDimModal,
  uploadDirectAttachedFile,
  uploadKnowledgeFiles,
  suggestModIdFromText,
  voiceAsrAdapter,
  voiceAsrBackendLabel,
  voiceSessionModeForIntent,
}

defineExpose({
  __coverage: coverageHooks,
})

if (import.meta.env.MODE === 'test') {
  ;(globalThis as any).__WORKBENCH_HOME_COVERAGE_HOOKS__ = coverageHooks
}
</script>

<style>
.wb-direct-main--chatting{display:flex;flex-direction:column;flex:1 1 0;min-height:0;overflow:hidden;position:relative}
.wb-direct-flow-host{flex:1 1 0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
/* 问档对话：单层滚动，去掉 scene/main/flow 多层 padding 造成的「框中框」 */
.wb-mode-scene--direct-flow{overflow:hidden!important;padding:0!important;gap:0!important}
.wb-mode-scene--direct-flow .wb-direct-shell{flex:1 1 0;min-height:0;width:100%}
.wb-mode-scene--direct-flow .wb-direct-main--chatting{padding:0!important;gap:0!important}
.wb-mode-scene--direct-flow .wb-direct-flow-host{flex:1 1 0;min-height:0;min-width:0}
.wb-mode-scene--direct-flow .wb-direct-composer-shell{flex-shrink:0}
.wb-mode-scene--direct-flow .wb-direct-shell{display:flex;flex-direction:column;flex:1 1 0;min-height:0;overflow:hidden}
.wb-mode-scene--direct-flow .wb-direct-box--chatting{display:flex;flex-direction:column;align-items:stretch;gap:.35rem;max-height:min(72dvh,100%);overflow:visible}
.wb-mode-scene--direct-flow .wb-direct-box-attachments{display:flex;flex-direction:column;gap:.25rem;flex-shrink:0}
.wb-mode-scene--direct-flow .wb-direct-box-attachments--hints-only{max-height:none;overflow:visible}
.wb-mode-scene--direct-flow .wb-direct-box-main{flex-shrink:0}
/* 对齐规则见 workbench-home-ux.css（.wb-mode-scene .wb-direct-box） */
.wb-voice-orb-area{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:2rem 0 1rem;min-height:200px;flex-shrink:0}
.wb-voice-orb-area--active{position:sticky;top:0;z-index:6;background:linear-gradient(to bottom,rgba(8,8,12,.98) 70%,transparent);padding-bottom:1.25rem}
.wb-voice-orb-btn{border:none;background:transparent;padding:0;cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:50%;transition:transform .15s ease}
.wb-voice-orb-btn:hover{transform:scale(1.03)}
.wb-voice-orb-btn:active{transform:scale(0.97)}
.wb-voice-orb-hint,.wb-voice-orb-status{margin:.75rem 0 0;font-size:.88rem;line-height:1.45;color:rgba(255,255,255,.55);text-align:center;max-width:420px}
.wb-voice-orb-hint{color:rgba(251,191,36,.92)}
.wb-voice-hero{text-align:left;margin-bottom:.5rem;padding:0 24px}
.wb-voice-hero .wb-voice-kicker{font-size:.82rem;color:rgba(255,255,255,.4);font-weight:500;margin:0 0 .2rem}
.wb-voice-hero .wb-voice-title{font-size:1.5rem;font-weight:700;letter-spacing:-.02em;color:var(--wb-text-primary,#f0f0f5);margin:0;line-height:1.25}
.wb-voice-hero.wb-title-enter{opacity:0}
.wb-voice-scene--no-contain{contain:none!important;isolation:auto!important;display:flex;flex-direction:column;align-items:stretch;height:100%;min-height:0;overflow:hidden;padding:0!important;gap:0!important}
.wb-voice-scene--chatting .wb-voice-flow-host{flex:1 1 0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.wb-voice-bottom{position:fixed;bottom:0;left:var(--wb-sidebar-w,240px);right:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;padding:.35rem 1rem .75rem;background:linear-gradient(transparent,rgba(8,8,12,.92) 25%);z-index:10;pointer-events:none}
.wb-voice-bottom--portal{z-index:120}
.wb-voice-bottom--portal .wb-voice-dock,.wb-voice-bottom--portal .wb-voice-waveform-wrap{pointer-events:auto}
.wb-voice-waveform-wrap{width:100%;max-width:720px;margin-bottom:.35rem}
.wb-voice-waveform-canvas{width:100%;height:28px;display:block;border-radius:1rem;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);padding:0 .55rem;box-sizing:border-box}
.wb-voice-direct-box{flex:1;width:100%;max-width:520px;position:relative;z-index:1}
.wb-voice-direct-box--listening{display:flex;align-items:center;justify-content:space-between;gap:.5rem}
.wb-voice-input-hint{flex:1;margin:0;padding:0 .5rem;font-size:.88rem;color:rgba(255,255,255,.45);text-align:left;line-height:1.4;user-select:none;pointer-events:none}
.wb-voice-pause-btn{width:44px;height:44px;min-width:44px;min-height:44px;border-radius:50%;border:none;background:rgba(255,255,255,.12);color:rgba(255,255,255,.9);cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;padding:0;transition:background .15s,color .15s;position:relative;z-index:2;touch-action:manipulation;-webkit-tap-highlight-color:transparent}
.wb-voice-pause-btn:hover{background:rgba(255,255,255,.2);color:#fff}
.wb-voice-pause-btn svg{width:18px;height:18px}
.wb-voice-scene .wb-voice-direct-box .wb-direct-voice-btn,
.wb-voice-scene .wb-voice-bottom .wb-direct-voice-btn{display:none!important;pointer-events:none!important;width:0!important;height:0!important;margin:0!important;padding:0!important;overflow:hidden!important;opacity:0!important}
.wb-direct-voice-btn--ptt{touch-action:none;user-select:none;-webkit-user-select:none}
.wb-direct-voice-wave{width:100%;margin-bottom:.35rem;box-sizing:border-box}
.wb-voice-continuous-btn{width:32px;height:32px;border-radius:50%;border:1px solid rgba(255,255,255,.1);background:transparent;color:#86868b;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;flex-shrink:0;padding:0}
.wb-voice-continuous-btn:hover{border-color:rgba(255,255,255,.2);color:#bbb}
.wb-voice-continuous-btn svg{width:16px;height:16px}
.wb-voice-continuous-btn--on{border-color:#34d399;color:#34d399;background:rgba(52,211,153,.1)}
.wb-voice-error{color:#f8a0a8;font-size:.82rem;text-align:center;margin:.5rem 0}
.wb-voice-soft-hint{color:#fbbf24;font-size:.8rem;text-align:center;margin:.45rem 0}
.wb-voice-loading-hint{color:#86868b;font-size:.78rem;text-align:center;margin:.4rem 0;animation:wb-pulse 1.5s ease-in-out infinite}
@keyframes wb-pulse{0%,100%{opacity:.6}50%{opacity:1}}
html[data-workbench-theme='light'] .wb-voice-chat-bar{background:rgba(245,245,247,.9);border-bottom-color:rgba(0,0,0,.06)}
html[data-workbench-theme='light'] .wb-voice-chat-bar__status{color:#86868b}
html[data-workbench-theme='light'] .wb-voice-chat-bar__live{color:#1d1d1f}
html[data-workbench-theme='light'] .wb-voice-orb-area--active{background:linear-gradient(to bottom,rgba(245,245,247,.98) 70%,transparent)}
html[data-workbench-theme='light'] .wb-voice-orb-hint{color:#d97706}
html[data-workbench-theme='light'] .wb-voice-orb-status{color:#86868b}
html[data-workbench-theme='light'] .wb-voice-hero .wb-voice-kicker{color:#86868b}
html[data-workbench-theme='light'] .wb-voice-hero .wb-voice-title{color:#1d1d1f}
html[data-workbench-theme='light'] .wb-voice-transcript{color:#86868b}
html[data-workbench-theme='light'] .wb-voice-bottom{background:linear-gradient(transparent,rgba(245,245,247,.95) 20%)}
html[data-workbench-theme='light'] .wb-voice-input-hint{color:#86868b}
html[data-workbench-theme='light'] .wb-voice-pause-btn{background:rgba(0,0,0,.06);color:#555}
html[data-workbench-theme='light'] .wb-voice-pause-btn:hover{background:rgba(0,0,0,.1);color:#1d1d1f}
html[data-workbench-theme='light'] .wb-voice-continuous-btn:hover{border-color:rgba(0,0,0,.15);color:#555}
html[data-workbench-theme='light'] .wb-voice-continuous-btn--on{border-color:#34d399;color:#059669;background:rgba(52,211,153,.08)}
html[data-workbench-theme='light'] .wb-voice-error{color:#d63040}
html[data-workbench-theme='light'] .wb-voice-soft-hint{color:#b45309}
.wb-tts-toggle{margin-left:auto;flex-shrink:0}
.wb-theme-toggle{flex-shrink:0}
.wb-mode-scene--make-flow{padding-bottom:calc(6.25rem + env(safe-area-inset-bottom) + var(--wb-vv-bottom-offset,0px))}
.wb-plan--done{border-left:2px solid rgba(52,211,153,.35);padding-left:.65rem;margin-left:-.65rem}
.wb-plan-done-badge{font-size:.72rem;color:rgba(52,211,153,.92);background:rgba(52,211,153,.12);padding:.15rem .55rem;border-radius:999px;flex-shrink:0}
.wb-plan--done .wb-plan-title{flex:1;min-width:0}
.wb-handoff--generating{opacity:.95}
.wb-handoff-generating-note{margin:.35rem 0 .75rem;font-size:.84rem;color:rgba(255,255,255,.55);line-height:1.45}
.wb-make-done{margin-top:1rem;padding:1rem 1.1rem;border-radius:.85rem;border:1px solid rgba(52,211,153,.28);background:rgba(52,211,153,.08)}
.wb-make-done-title{margin:0;font-size:1.05rem;font-weight:600;color:rgba(255,255,255,.95)}
.wb-make-done-sub{margin:.35rem 0 0;font-size:.84rem;color:rgba(255,255,255,.55)}
.wb-make-done-howto{margin:.85rem 0 0;padding-left:1.15rem;font-size:.84rem;line-height:1.55;color:rgba(255,255,255,.72)}
.wb-make-done-actions{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}
.wb-make-done-primary,.wb-make-done-secondary,.wb-make-done-ghost{padding:.5rem 1rem;border-radius:.55rem;font:inherit;font-size:.88rem;cursor:pointer;border:none}
.wb-make-done-primary{background:#fff;color:#111;font-weight:600}
.wb-make-done-secondary{background:rgba(255,255,255,.12);color:rgba(255,255,255,.9)}
.wb-make-done-ghost{background:transparent;color:rgba(255,255,255,.45);border:1px solid rgba(255,255,255,.12)}
html[data-workbench-theme='light'] .wb-handoff-generating-note{color:#666}
html[data-workbench-theme='light'] .wb-make-done{background:rgba(52,211,153,.06);border-color:rgba(5,150,105,.25)}
html[data-workbench-theme='light'] .wb-make-done-title{color:#1d1d1f}
html[data-workbench-theme='light'] .wb-make-done-sub,html[data-workbench-theme='light'] .wb-make-done-howto{color:#555}
html[data-workbench-theme='light'] .wb-make-done-primary{background:#1d1d1f;color:#fff}
html[data-workbench-theme='light'] .wb-make-done-secondary{background:rgba(0,0,0,.06);color:#333}
html[data-workbench-theme='light'] .wb-make-done-ghost{color:#888;border-color:rgba(0,0,0,.12)}
.wb-orch-quality{margin-top:1rem;padding:.85rem 1rem;border-radius:.75rem;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03)}
.wb-orch-quality-title{margin:0 0 .5rem;font-size:.88rem;font-weight:600;color:rgba(255,255,255,.85)}
.wb-orch-quality-list{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:.35rem}
.wb-orch-quality-item{font-size:.82rem;line-height:1.45;color:rgba(255,255,255,.65);display:flex;gap:.45rem;align-items:flex-start}
.wb-orch-quality-item--ok{color:rgba(52,211,153,.9)}
.wb-orch-quality-item--warn{color:rgba(248,160,168,.95)}
.wb-orch-quality-item--skip{opacity:.55}
.wb-orch-quality-item--critical{color:rgba(255,100,100,1);font-weight:600}
.wb-orch-quality-score{margin-left:.5rem;font-size:.78rem;font-weight:500;opacity:.85}
.wb-orch-quality-hint{margin:0 0 .45rem;font-size:.82rem;color:rgba(255,255,255,.55)}
.wb-orch-quality-check{flex-shrink:0;font-weight:700}
html[data-workbench-theme='light'] .wb-orch-quality{background:rgba(0,0,0,.03);border-color:rgba(0,0,0,.08)}
html[data-workbench-theme='light'] .wb-orch-quality-title{color:#1d1d1f}
html[data-workbench-theme='light'] .wb-orch-quality-item{color:#555}

/* 手机端：语音底栏抬升到底部 Tab 之上，对话区留白 */
@media (max-width:768px){
.wb-voice-bottom--mobile,.wb-voice-bottom.wb-voice-bottom--portal{left:0!important;right:0!important;bottom:calc(56px + env(safe-area-inset-bottom,0px))!important;z-index:9210!important}
.wb-voice-bottom--mobile{padding:.35rem .65rem .5rem;padding-bottom:calc(.5rem + env(safe-area-inset-bottom,0px));background:linear-gradient(transparent,rgba(8,8,12,.96) 18%)}
.wb-voice-bottom--mobile .wb-voice-waveform-wrap{max-width:100%;margin-bottom:.25rem}
.wb-voice-bottom--mobile .wb-voice-waveform-canvas{height:32px;border-radius:12px}
.wb-voice-scene--mobile .wb-voice-flow-host{flex:1;min-height:0}
.wb-voice-scene--mobile.wb-voice-scene--chatting .wb-voice-orb-area{display:none}
.wb-voice-scene--mobile .wb-voice-orb-area{min-height:140px;padding:1rem 0 .5rem}
.wb-voice-scene--mobile .wb-voice-orb-hint,.wb-voice-scene--mobile .wb-voice-orb-status{font-size:.82rem;padding:0 .75rem}
.wb-voice-error,.wb-voice-soft-hint,.wb-voice-loading-hint{position:fixed;left:.75rem;right:.75rem;bottom:calc(118px + env(safe-area-inset-bottom,0px));z-index:9220;margin:0;padding:.35rem .5rem;border-radius:8px;background:rgba(8,8,12,.88);pointer-events:none}
html[data-workbench-theme='light'] .wb-voice-bottom--mobile{background:linear-gradient(transparent,rgba(245,245,247,.97) 18%)}
html[data-workbench-theme='light'] .wb-voice-error,html[data-workbench-theme='light'] .wb-voice-soft-hint,html[data-workbench-theme='light'] .wb-voice-loading-hint{background:rgba(245,245,247,.92)}
}
@supports (padding-bottom:constant(safe-area-inset-bottom)){
@media (max-width:768px){
.wb-voice-bottom--mobile{bottom:calc(56px + constant(safe-area-inset-bottom))!important}
.wb-voice-error,.wb-voice-soft-hint,.wb-voice-loading-hint{bottom:calc(118px + constant(safe-area-inset-bottom))}
}
}
</style>
