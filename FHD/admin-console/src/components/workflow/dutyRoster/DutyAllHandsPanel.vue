/**
 * 全员汇报（All-Hands）面板。
 *
 * 由 DutyRosterGraphPanel.vue 模板机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './dutyRosterTypes'
import { formatDurationMs, formatTime, isVirtualEmployee } from './dutyRosterConstants'
import type { DutyAllHands } from './useDutyAllHands'
import type { DutyRosterState } from './useDutyRosterState'
import MessageBody from '@/components/chat/MessageBody.vue'

const emit = defineEmits<{
  (e: 'update:allHandsWithResearch', v: Deref<DutyRosterState['allHandsWithResearch']>): void
  (e: 'update:showAllHandsPanel', v: Deref<DutyRosterState['showAllHandsPanel']>): void
  (e: 'update:allHandsQuestion', v: Deref<DutyRosterState['allHandsQuestion']>): void
}>()

const props = defineProps<{
  allHandsWithResearch: Deref<DutyRosterState['allHandsWithResearch']>
  showAllHandsPanel: Deref<DutyRosterState['showAllHandsPanel']>
  allHandsQuestion: Deref<DutyRosterState['allHandsQuestion']>
  allHandsBusy: Deref<DutyRosterState['allHandsBusy']>
  allHandsError: Deref<DutyRosterState['allHandsError']>
  allHandsExpanded: Deref<DutyRosterState['allHandsExpanded']>
  allHandsMeetingMinutes: Deref<DutyRosterState['allHandsMeetingMinutes']>
  allHandsMeetingMinutesEmail: Deref<DutyRosterState['allHandsMeetingMinutesEmail']>
  allHandsPlainLoading: Deref<DutyRosterState['allHandsPlainLoading']>
  allHandsPlainOpen: Deref<DutyRosterState['allHandsPlainOpen']>
  allHandsPlainText: Deref<DutyRosterState['allHandsPlainText']>
  allHandsProgress: Deref<DutyRosterState['allHandsProgress']>
  allHandsReport: Deref<DutyRosterState['allHandsReport']>
  allHandsSessionId: Deref<DutyRosterState['allHandsSessionId']>
  employees: Deref<DutyRosterState['employees']>
  allHandsAreaPalette: Deref<DutyAllHands['allHandsAreaPalette']>
  askAllHandsQuestion: Deref<DutyAllHands['askAllHandsQuestion']>
  copyAllHandsMeetingMinutes: Deref<DutyAllHands['copyAllHandsMeetingMinutes']>
  downloadAllHandsMeetingMinutes: Deref<DutyAllHands['downloadAllHandsMeetingMinutes']>
  focusAllHandsEmployee: Deref<DutyAllHands['focusAllHandsEmployee']>
  publishFollowUpToButler: Deref<DutyAllHands['publishFollowUpToButler']>
  requestPlainLang: Deref<DutyAllHands['requestPlainLang']>
  runAllHands: Deref<DutyAllHands['runAllHands']>
  toggleAllHandsRow: Deref<DutyAllHands['toggleAllHandsRow']>
}>()

const allHandsWithResearch = computed({
  get: () => props.allHandsWithResearch,
  set: (v) => emit('update:allHandsWithResearch', v),
})

const showAllHandsPanel = computed({
  get: () => props.showAllHandsPanel,
  set: (v) => emit('update:showAllHandsPanel', v),
})

const allHandsQuestion = computed({
  get: () => props.allHandsQuestion,
  set: (v) => emit('update:allHandsQuestion', v),
})

</script>

<template>
            <transition name="dg-slide-top">
              <div v-if="showAllHandsPanel" class="dg-allhands-panel">
                <div class="dg-allhands-head">
                  <div class="dg-allhands-head-left">
                    <h3 class="dg-allhands-title">数字管家 · 员工大会汇报</h3>
                    <p class="dg-allhands-sub">
                      每个员工自述：① 文件架构与工作逻辑 ② 最近问题与解决路径
                      ③ 联网+GitHub 调研后的自我优化（含联动其他岗位）。
                      <strong>提问后</strong>每位员工只针对你的问题作答，并由数字管家做综合答复。
                      卡片上的<strong>已汇报</strong>仅表示该员工本轮生成成功，不是待办工单。
                    </p>
                  </div>
                  <div class="dg-allhands-head-right">
                    <label class="dg-run-check">
                      <input v-model="allHandsWithResearch" type="checkbox" :disabled="allHandsBusy" />
                      <span>联网 + GitHub 调研</span>
                    </label>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost"
                      :disabled="allHandsBusy"
                      @click="runAllHands()"
                    >{{ allHandsBusy ? '汇报中…' : (allHandsReport ? '重新生成全员架构汇报' : '生成全员架构汇报') }}</button>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost"
                      @click="showAllHandsPanel = false"
                    >收起</button>
                  </div>
                </div>

                <!-- 用户提问 → 19 名员工讨论 → 综合答复 -->
                <div class="dg-allhands-ask">
                  <textarea
                    v-model="allHandsQuestion"
                    class="dg-allhands-ask__input"
                    rows="2"
                    maxlength="600"
                    :disabled="allHandsBusy"
                    placeholder="例如：有没有员工负责定时清理过期文件？数字猫窝运行情况怎么样？"
                  />
                  <div class="dg-allhands-ask__row">
                    <span class="dg-allhands-ask__hint">{{ allHandsQuestion.length }}/600</span>
                    <button
                      type="button"
                      class="dg-btn dg-btn--dispatch dg-btn--sm"
                      :disabled="allHandsBusy || !allHandsQuestion.trim()"
                      @click="askAllHandsQuestion"
                    >{{ allHandsBusy ? '员工讨论中…' : '向员工大会提问' }}</button>
                  </div>
                </div>

                <p v-if="allHandsBusy && !allHandsReport" class="dg-allhands-loading">
                  <span class="dg-spinner" /> 正在召集 {{ employees.filter(e => !isVirtualEmployee(e.id)).length }} 名员工，
                  后端会话 {{ allHandsSessionId ? `#${allHandsSessionId.slice(0, 8)}` : '' }} 正在执行，
                  页面将每 2 秒轮询一次结果…
                </p>
                <div v-if="allHandsBusy && allHandsProgress.total > 0" class="dg-allhands-progress">
                  <div class="dg-allhands-progress-head">
                    <span>员工完成 {{ allHandsProgress.completed }}/{{ allHandsProgress.total }}</span>
                    <span>{{ allHandsProgress.percent }}%</span>
                  </div>
                  <div class="dg-allhands-progress-track">
                    <div
                      class="dg-allhands-progress-fill"
                      :style="{ width: `${allHandsProgress.percent}%` }"
                    />
                  </div>
                  <p class="dg-allhands-progress-sub">
                    成功 {{ allHandsProgress.ok }} · 异常 {{ allHandsProgress.error }}
                    <span v-if="allHandsProgress.current_employee_id">
                      · 最近完成 {{ allHandsProgress.current_employee_name || allHandsProgress.current_employee_id }}
                    </span>
                  </p>
                </div>
                <p v-if="allHandsError" class="dg-allhands-error">{{ allHandsError }}</p>
                <div v-if="allHandsReport" class="dg-allhands-summary">
                  <span class="dg-run-pill">共 {{ allHandsReport.summary.total ?? 0 }} 人</span>
                  <span class="dg-run-pill dg-run-pill--ok">完成 {{ allHandsReport.summary.ok ?? 0 }}</span>
                  <span
                    v-if="(allHandsReport.summary.error ?? 0) > 0"
                    class="dg-run-pill dg-run-pill--bad"
                  >失败 {{ allHandsReport.summary.error ?? 0 }}</span>
                  <span class="dg-run-pill">
                    Bench: {{ allHandsReport.summary.bench_provider }}/{{ allHandsReport.summary.bench_model }}
                  </span>
                  <span v-if="allHandsReport.summary.with_research" class="dg-run-pill">已联网 + GitHub</span>
                  <span v-if="allHandsReport.summary.user_question" class="dg-run-pill dg-run-pill--ask">
                    Q&A：{{ allHandsReport.summary.user_question.slice(0, 24) }}{{ (allHandsReport.summary.user_question || '').length > 24 ? '…' : '' }}
                  </span>
                </div>

                <!-- 数字管家综合答复（仅在用户提问 + 综合阶段成功时出现） -->
                <section
                  v-if="allHandsReport && allHandsReport.synthesized_answer && allHandsReport.synthesized_answer.markdown"
                  class="dg-allhands-synth"
                >
                  <header class="dg-allhands-synth__head">
                    <span class="dg-allhands-synth__badge">数字管家综合答复</span>
                    <span class="dg-allhands-synth__model">
                      {{ allHandsReport.synthesized_answer.model || '—' }}
                    </span>
                  </header>
                  <p class="dg-allhands-synth__question">
                    问题：{{ allHandsReport.synthesized_answer.question }}
                  </p>
                  <div class="dg-allhands-md dg-allhands-md--synth">
                    <MessageBody :content="allHandsReport.synthesized_answer.markdown" />
                  </div>
                  <div
                    v-if="allHandsReport.synthesized_answer.cited_employees && allHandsReport.synthesized_answer.cited_employees.length"
                    class="dg-allhands-synth__cited"
                  >
                    <span class="dg-allhands-synth__cited-label">引用员工：</span>
                    <button
                      v-for="cid in allHandsReport.synthesized_answer.cited_employees"
                      :key="cid"
                      type="button"
                      class="dg-allhands-synth__cite"
                      @click="focusAllHandsEmployee(cid)"
                    >{{ cid }}</button>
                  </div>
                </section>
                <p
                  v-else-if="allHandsReport && allHandsReport.synthesized_answer && allHandsReport.synthesized_answer.error"
                  class="dg-allhands-synth-error"
                >
                  综合答复未生成：{{ allHandsReport.synthesized_answer.error }}
                </p>

                <section
                  v-if="allHandsReport && (allHandsMeetingMinutes?.text || allHandsMeetingMinutes?.error || allHandsMeetingMinutesEmail)"
                  class="dg-allhands-minutes"
                >
                  <header class="dg-allhands-minutes__head">
                    <span class="dg-allhands-minutes__badge">会议摘要</span>
                    <span
                      v-if="allHandsMeetingMinutes?.model"
                      class="dg-allhands-minutes__model"
                    >{{ allHandsMeetingMinutes.model }}</span>
                    <div class="dg-allhands-minutes__actions">
                      <button
                        type="button"
                        class="dg-btn dg-btn--ghost dg-btn--small"
                        :disabled="!((allHandsMeetingMinutes?.text || '').trim())"
                        @click="copyAllHandsMeetingMinutes"
                      >复制正文</button>
                      <button
                        type="button"
                        class="dg-btn dg-btn--ghost dg-btn--small"
                        :disabled="!((allHandsMeetingMinutes?.text || '').trim())"
                        @click="downloadAllHandsMeetingMinutes"
                      >下载 .txt</button>
                    </div>
                  </header>
                  <p
                    v-if="allHandsMeetingMinutesEmail?.any_delivered"
                    class="dg-allhands-minutes__mail dg-allhands-minutes__mail--ok"
                  >
                    摘要已发送至<strong>每日摘要（早报）</strong>所配置的邮箱（与 MODSTORE_DAILY_DIGEST_EMAIL 一致）。
                  </p>
                  <p
                    v-else-if="allHandsMeetingMinutesEmail && (allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__mail dg-allhands-minutes__mail--muted"
                  >
                    <template v-if="allHandsMeetingMinutesEmail.skipped_reason">
                      未发信：{{ allHandsMeetingMinutesEmail.skipped_reason }}
                    </template>
                    <template v-else>
                      邮件未成功投递（请检查 SMTP 配置或使用 POST /api/admin/email/test）。
                    </template>
                  </p>
                  <pre
                    v-if="(allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__pre"
                  >{{ allHandsMeetingMinutes?.text }}</pre>
                  <p
                    v-if="allHandsMeetingMinutes?.error && !(allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__err"
                  >
                    会议摘要生成失败：{{ allHandsMeetingMinutes.error }}
                  </p>
                </section>

                <div v-if="allHandsReport" class="dg-allhands-list">
                  <article
                    v-for="row in allHandsReport.employees"
                    :key="row.employee_id"
                    class="dg-allhands-card"
                    :style="{ borderLeftColor: allHandsAreaPalette[row.area] || '#6366f1' }"
                  >
                    <header class="dg-allhands-card-head">
                      <div class="dg-allhands-card-title">
                        <span class="dg-allhands-card-name">{{ row.name }}</span>
                        <code class="dg-allhands-card-id">{{ row.employee_id }}</code>
                        <span
                          class="dg-allhands-card-status"
                          :class="row.status === 'ok' ? 'is-ok' : 'is-bad'"
                        >{{ row.status === 'ok' ? '已汇报' : (row.status === 'model_error' ? '模型异常' : (row.status === 'empty' ? '空输出' : '失败')) }}</span>
                      </div>
                      <div class="dg-allhands-card-actions">
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="focusAllHandsEmployee(row.employee_id)"
                        >定位</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="publishFollowUpToButler(row)"
                        >推给管家跟进</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="toggleAllHandsRow(row.employee_id)"
                        >{{ allHandsExpanded[row.employee_id] ? '折叠' : '展开' }}</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small dg-btn--plain"
                          :disabled="allHandsPlainLoading[row.employee_id]"
                          @click="requestPlainLang(row)"
                        >{{ allHandsPlainOpen[row.employee_id] ? '收起说人话' : '说人话' }}</button>
                      </div>
                    </header>

                    <div class="dg-allhands-meta">
                      <span v-if="row.area" class="dg-allhands-meta-tag">{{ row.area }}</span>
                      <span class="dg-allhands-meta-tag">handlers: {{ row.manifest_signals.handlers.join(', ') || '—' }}</span>
                      <span v-if="row.manifest_signals.workflow_id > 0" class="dg-allhands-meta-tag">
                        workflow #{{ row.manifest_signals.workflow_id }}
                      </span>
                      <span v-if="row.manifest_signals.depends_on.length" class="dg-allhands-meta-tag">
                        依赖: {{ row.manifest_signals.depends_on.join(', ') }}
                      </span>
                      <span v-if="(row.duration_ms ?? 0) > 0" class="dg-allhands-meta-tag">
                        {{ formatDurationMs(row.duration_ms || 0) }} · {{ row.llm_tokens || 0 }} tok
                      </span>
                      <span v-if="row.recent_failures.length" class="dg-allhands-meta-tag dg-allhands-meta-tag--warn">
                        近 {{ row.recent_failures.length }} 条失败
                      </span>
                    </div>

                    <div v-if="allHandsPlainOpen[row.employee_id]" class="dg-allhands-plain">
                      <span v-if="allHandsPlainLoading[row.employee_id]" class="dg-allhands-plain-loading">
                        爸爸稍等，AI 正在翻译中<span class="dg-plain-dots">...</span>
                      </span>
                      <p v-else class="dg-allhands-plain-text">{{ allHandsPlainText[row.employee_id] }}</p>
                    </div>

                    <div v-if="allHandsExpanded[row.employee_id]" class="dg-allhands-body">
                      <p v-if="row.cognition_error" class="dg-allhands-cog-err">{{ row.cognition_error }}</p>
                      <details v-if="row.recent_failures.length" class="dg-allhands-details">
                        <summary>近期失败流水（{{ row.recent_failures.length }}）</summary>
                        <ul class="dg-allhands-fail-list">
                          <li v-for="f in row.recent_failures" :key="f.id" class="dg-allhands-fail-item">
                            <span class="dg-allhands-fail-time">{{ formatTime(f.created_at) }}</span>
                            <span class="dg-allhands-fail-status">{{ f.status }}</span>
                            <span v-if="f.task" class="dg-allhands-fail-task">{{ f.task }}</span>
                            <code v-if="f.error" class="dg-allhands-fail-err">{{ f.error }}</code>
                          </li>
                        </ul>
                      </details>

                      <details v-if="row.research_sources.length" class="dg-allhands-details">
                        <summary>调研参考来源（{{ row.research_sources.length }}）</summary>
                        <ul class="dg-allhands-source-list">
                          <li v-for="(s, idx) in row.research_sources" :key="`src-${idx}`">
                            <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title || s.url }}</a>
                            <span v-else>{{ s.title }}</span>
                          </li>
                        </ul>
                      </details>

                      <p v-if="row.warnings.length" class="dg-allhands-warns">
                        <strong>调研提示：</strong>{{ row.warnings.join('；') }}
                      </p>

                      <div v-if="row.report_markdown" class="dg-allhands-md dg-allhands-md--card">
                        <MessageBody :content="row.report_markdown" />
                      </div>
                      <p v-else class="dg-allhands-empty">（员工未输出 Markdown）</p>
                    </div>
                  </article>
                </div>
              </div>
            </transition>
</template>

<style scoped src="../DutyRosterGraphPanel.css"></style>
