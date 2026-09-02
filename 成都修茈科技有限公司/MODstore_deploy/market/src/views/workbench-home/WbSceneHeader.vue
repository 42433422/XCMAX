<script setup lang="ts">
import DirectGeneratedFileStack from '../../components/workbench/direct/DirectGeneratedFileStack.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 3–154 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  wbSidebar, wbNav, CANVAS_SKILL_INTENT, composerIntent, hasModRepo, hasEmployeeIntent,
  platformChatMode, voiceCasualChatMode, togglePlatformChatMode, switchMakeIntent, directGeneratedFiles, directGeneratingFile,
  directGeneratingFormatLabel, showDirectHomeFileStrip, directLoading, ttsAutoRead, isLightTheme, toggleTheme,
  directWebSearchEnabled, directImageGenEnabled, directVideoGenEnabled, headerGeneratedStripPlan, butlerFileOverflowCount, openButlerFileTray,
  consumptionTier, tierPanelOpen, empPanelOpen, tierTriggerRef, empTriggerRef, toggleTierPanel,
  toggleDirectWebSearch, toggleDirectImageGen, toggleDirectVideoGen, toggleEmpPanel, removeDirectGeneratedFile, downloadGeneratedOutput,
  hasWorkflow,
} = props.wb
</script>

<template>
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
        :title="`在小C助理中查看 ${butlerFileOverflowCount} 个收纳文件`"
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
</template>
