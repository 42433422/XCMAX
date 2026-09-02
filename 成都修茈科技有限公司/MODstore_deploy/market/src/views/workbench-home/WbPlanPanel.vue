<script setup lang="ts">
import ConsumptionTierControl from '../../components/workbench/ConsumptionTierControl.vue'
import MessageBody from '../../components/workbench/MessageBody.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 738–1026 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  wbSidebar, planSession, autoPilotRunning, autoPilotError, planOptionSelections, PLAN_OPTION_OTHER_ID,
  planOptionOtherText, planPanelRef, planSurfaceKey, planLoadingAdvance, planLoadingStepLabelsForUi, planLoadingProgressPercent,
  consumptionTier, tierPanelOpen, titleEnterDone, hasWorkflow, greetingLine, placeholder,
  planQuickOptions, planPanelTitle, planChecklistFlowMarkdown, cancelPlanSummary, makeKickerTw, makeTitleTw,
  canSendPlanQuickPicks, planAssistantParts, planDiagramError, openPlanDiagramPreview, dismissPlanSession, backSummaryToComposer,
  confirmSummaryAndStartPlanning, runAutoPilotFromSummary, runAutoPilotFromChat, pickPlanOption, autoPickPlanQuickOptions, sendPlanReplyFromQuickPicks,
  requestExecutionChecklist, backPlanToChat, confirmPlanAndOpenHandoff,
} = props.wb
</script>

<template>
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
            <TransitionGroup v-if="planSession.phase !== 'summary'" name="wb-plan-msg" tag="ul" class="wb-plan-thread">
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
                        v-if="planAssistantParts(m.content).hasDiagram && !planDiagramError[String(idx)]"
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
                            planAssistantParts(m.content).hasDiagram && !planDiagramError[String(idx)],
                        }"
                        aria-hidden="false"
                      />
                      <p v-if="planDiagramError[String(idx)]" class="wb-plan-diagram-err" role="alert">
                        {{ planDiagramError[String(idx)] }}
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
</template>
