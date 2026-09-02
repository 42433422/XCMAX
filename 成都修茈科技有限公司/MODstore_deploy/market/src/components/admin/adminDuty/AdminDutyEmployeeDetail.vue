/**
 * 员工详情侧栏（健康 / 依赖 / LLM / 能力 / 最近执行 / 任务派发）。
 *
 * 由 AdminDutyEmployeeGraph.vue 模板块机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './adminDutyTypes'
import { HEALTH_COLOR, HEALTH_LABEL, RUN_STATUS_COLOR, RUN_STATUS_LABEL, formatDurationMs, formatRate, formatTime } from './adminDutyConstants'
import { describeHandler } from '../../../domain/butlerEmployeeProfile'
import type { EmpRow } from './adminDutyTypes'
import type { AdminDutyExec } from './useAdminDutyExec'
import type { AdminDutyPanels } from './useAdminDutyPanels'
import type { AdminDutyRun } from './useAdminDutyRun'
import type { AdminDutySelection } from './useAdminDutySelection'
import type { AdminDutyState } from './useAdminDutyState'

const emit = defineEmits<{
  (e: 'update:showDispatch', v: Deref<AdminDutyState['showDispatch']>): void
  (e: 'update:taskBrief', v: Deref<AdminDutyState['taskBrief']>): void
  (e: 'update:taskInputJson', v: Deref<AdminDutyState['taskInputJson']>): void
  (e: 'update:dispatchConfirmHighRisk', v: Deref<AdminDutyState['dispatchConfirmHighRisk']>): void
  (e: 'update:selectedEmp', v: Deref<AdminDutyState['selectedEmp']>): void
}>()

const props = defineProps<{
  selectedEmp: Deref<AdminDutyState['selectedEmp']>
  showDispatch: Deref<AdminDutyState['showDispatch']>
  taskBrief: Deref<AdminDutyState['taskBrief']>
  taskInputJson: Deref<AdminDutyState['taskInputJson']>
  dispatchConfirmHighRisk: Deref<AdminDutyState['dispatchConfirmHighRisk']>
  loadingP2: Deref<AdminDutyState['loadingP2']>
  capLoading: Deref<AdminDutyState['capLoading']>
  viewMode: Deref<AdminDutyState['viewMode']>
  execItems: Deref<AdminDutyState['execItems']>
  execTotal: Deref<AdminDutyState['execTotal']>
  execLoading: Deref<AdminDutyState['execLoading']>
  execLoadingMore: Deref<AdminDutyState['execLoadingMore']>
  execError: Deref<AdminDutyState['execError']>
  taskError: Deref<AdminDutyState['taskError']>
  taskResult: Deref<AdminDutyState['taskResult']>
  taskRunning: Deref<AdminDutyState['taskRunning']>
  llmStatusMap: Deref<AdminDutyState['llmStatusMap']>
  healthLevel: Deref<AdminDutyState['healthLevel']>
  selectedHealth: Deref<AdminDutySelection['selectedHealth']>
  selectedDeps: Deref<AdminDutySelection['selectedDeps']>
  selectedCapabilityView: Deref<AdminDutySelection['selectedCapabilityView']>
  isSelectedVirtual: Deref<AdminDutySelection['isSelectedVirtual']>
  selectedLlm: Deref<AdminDutySelection['selectedLlm']>
  selectedCapability: Deref<AdminDutySelection['selectedCapability']>
  selectedRunNode: Deref<AdminDutySelection['selectedRunNode']>
  fetchExecMetrics: Deref<AdminDutyExec['fetchExecMetrics']>
  dispatchTask: Deref<AdminDutyRun['dispatchTask']>
  publishTaskToButler: Deref<AdminDutyRun['publishTaskToButler']>
  isDetailOpen: Deref<AdminDutyPanels['isDetailOpen']>
  toggleDetail: Deref<AdminDutyPanels['toggleDetail']>
  goUse: (emp: EmpRow) => void
  accountKeysNav: () => void
}>()

const showDispatch = computed({
  get: () => props.showDispatch,
  set: (v) => emit('update:showDispatch', v),
})

const taskBrief = computed({
  get: () => props.taskBrief,
  set: (v) => emit('update:taskBrief', v),
})

const taskInputJson = computed({
  get: () => props.taskInputJson,
  set: (v) => emit('update:taskInputJson', v),
})

const dispatchConfirmHighRisk = computed({
  get: () => props.dispatchConfirmHighRisk,
  set: (v) => emit('update:dispatchConfirmHighRisk', v),
})

const selectedEmp = computed({
  get: () => props.selectedEmp,
  set: (v) => emit('update:selectedEmp', v),
})

</script>

<template>
              <transition name="dg-slide">
                <div v-if="selectedEmp && viewMode !== 'client'" class="dg-detail">
                  <div class="dg-detail-header">
                    <span class="dg-detail-dot" :style="{ background: HEALTH_COLOR[healthLevel(selectedEmp.id)] }" />
                    <h3 class="dg-detail-name">{{ selectedEmp.name || selectedEmp.id }}</h3>
                  </div>
                  <p class="dg-detail-id">{{ selectedEmp.id }}</p>
                  <p v-if="selectedEmp.industry" class="dg-detail-meta">行业：{{ selectedEmp.industry }}</p>

                  <p class="dg-detail-badge" :class="selectedEmp.source === 'v1_catalog' ? 'dg-badge--warn' : 'dg-badge--ok'">
                    {{ selectedEmp.source === 'v1_catalog' ? '⚠ 仅目录' : '✓ 已登记' }}
                  </p>

                  <button class="dg-section-toggle" @click="toggleDetail('health')">
                    <span>健康状态</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('health') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('health')">
                    <div v-if="selectedHealth" class="dg-detail-health">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">状态</span>
                        <span class="dg-hval" :style="{ color: HEALTH_COLOR[healthLevel(selectedEmp.id)] }">
                          {{ HEALTH_LABEL[healthLevel(selectedEmp.id)] }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">执行次数</span>
                        <span class="dg-hval">{{ selectedHealth.total }}</span>
                      </div>
                      <div v-if="selectedHealth.total > 0" class="dg-hrow">
                        <span class="dg-hlabel">成功率</span>
                        <span class="dg-hval">{{ formatRate(selectedHealth.rate) }}</span>
                      </div>
                      <div v-if="selectedHealth.lastExecution" class="dg-hrow">
                        <span class="dg-hlabel">最后执行</span>
                        <span class="dg-hval dg-hval--sm">{{ formatTime(selectedHealth.lastExecution) }}</span>
                      </div>
                    </div>
                    <p v-else-if="loadingP2" class="dg-detail-loading">拉取状态中…</p>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('exec')">
                    <span>最近执行</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('exec') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('exec')" class="dg-detail-exec">
                    <p v-if="execLoading" class="dg-detail-loading">加载执行记录…</p>
                    <p v-else-if="execError" class="dg-exec-err">{{ execError }}</p>
                    <template v-else>
                      <p v-if="!execItems.length" class="dg-exec-empty">暂无执行记录</p>
                      <ul v-else class="dg-exec-list">
                        <li v-for="row in execItems" :key="row.id" class="dg-exec-item">
                          <div class="dg-exec-item-meta">
                            <span class="dg-exec-time">{{ formatTime(row.created_at) }}</span>
                            <span>{{ formatDurationMs(row.duration_ms) }}</span>
                            <span
                              class="dg-exec-status"
                              :class="row.status === 'success' ? 'dg-exec-status--ok' : 'dg-exec-status--bad'"
                            >{{ row.status || '—' }}</span>
                            <span class="dg-exec-num">uid {{ row.user_id }}</span>
                            <span v-if="row.llm_tokens" class="dg-exec-num">{{ row.llm_tokens }} tok</span>
                          </div>
                          <p class="dg-exec-task" :title="row.task">{{ row.task || '（无摘要）' }}</p>
                          <p v-if="row.error" class="dg-exec-err-line" :title="row.error">{{ row.error }}</p>
                        </li>
                      </ul>
                      <div v-if="execItems.length" class="dg-exec-footer">
                        <span class="dg-exec-count">共 {{ execTotal }} 条 · 已显示 {{ execItems.length }}</span>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          :disabled="execLoadingMore || execItems.length >= execTotal"
                          @click="fetchExecMetrics(true)"
                        >
                          {{ execLoadingMore ? '加载中…' : '加载更多' }}
                        </button>
                      </div>
                    </template>
                  </div>

                  <button v-if="selectedDeps.length" class="dg-section-toggle" @click="toggleDetail('deps')">
                    <span>依赖员工 ({{ selectedDeps.length }})</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('deps') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="selectedDeps.length && isDetailOpen('deps')" class="dg-detail-deps">
                    <ul class="dg-deps-list">
                      <li v-for="dep in selectedDeps" :key="dep" class="dg-deps-item" :title="dep">{{ dep }}</li>
                    </ul>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('skills')">
                    <span>能做什么 · 怎么做</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('skills') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('skills')">
                    <div v-if="selectedCapabilityView" class="dg-detail-skills">
                      <p v-if="isSelectedVirtual" class="dg-skills-virtual-hint">
                        数字管家：浏览器内常驻智能体，不写入 employee_execution_metrics。
                      </p>
                      <p v-if="selectedCapabilityView.persona" class="dg-skills-persona">
                        {{ selectedCapabilityView.persona }}
                      </p>
                      <div v-if="selectedCapabilityView.expertise.length" class="dg-skills-expertise">
                        <span
                          v-for="tag in selectedCapabilityView.expertise"
                          :key="`exp-${tag}`"
                          class="dg-skills-tag"
                        >{{ tag }}</span>
                      </div>
                      <ul v-if="selectedCapabilityView.skills.length" class="dg-skills-list">
                        <li
                          v-for="(s, i) in selectedCapabilityView.skills"
                          :key="`sk-${i}-${s.name}`"
                          class="dg-skill-row"
                        >
                          <div class="dg-skill-head">
                            <span class="dg-skill-name">{{ s.name }}</span>
                            <span v-if="s.kind" class="dg-skill-kind">{{ s.kind }}</span>
                          </div>
                          <p v-if="s.brief" class="dg-skill-brief">{{ s.brief }}</p>
                          <p v-if="s.how" class="dg-skill-how">
                            <span class="dg-skill-how-label">怎么做</span>
                            <code>{{ s.how }}</code>
                          </p>
                        </li>
                      </ul>
                      <p v-else class="dg-skills-empty">
                        该员工 manifest.cognition.skills 为空；下面的执行通道是它实际可用的能力。
                      </p>
                      <div v-if="selectedCapabilityView.handlers.length" class="dg-skills-handlers">
                        <p class="dg-skills-subtitle">执行通道（actions.handlers）</p>
                        <ul class="dg-handler-list">
                          <li
                            v-for="h in selectedCapabilityView.handlers"
                            :key="`h-${h}`"
                            class="dg-handler-row"
                          >
                            <code class="dg-handler-name">{{ h }}</code>
                            <span class="dg-handler-desc">{{ describeHandler(h) }}</span>
                          </li>
                        </ul>
                      </div>
                      <p v-if="selectedCapabilityView.workflowId > 0" class="dg-skills-workflow">
                        关联工作流：
                        <router-link
                          :to="{ name: 'workflow' }"
                          class="dg-skills-workflow-link"
                        >#{{ selectedCapabilityView.workflowId }}</router-link>
                      </p>
                    </div>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('llm')">
                    <span>LLM 接入状态</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('llm') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('llm')">
                    <div v-if="selectedLlm" class="dg-detail-llm">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">供应商</span>
                        <span class="dg-hval">
                          {{
                            selectedLlm.provider === 'auto'
                              ? '自动（运行时解析）'
                              : llmStatusMap[selectedLlm.provider]?.label || selectedLlm.provider
                          }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">模型</span>
                        <span class="dg-hval dg-hval--sm">{{
                          selectedLlm.model === 'auto' ? '自动' : selectedLlm.model
                        }}</span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">需要 LLM</span>
                        <span class="dg-hval" :style="{ color: selectedLlm.needsLlm ? '#e0e0e0' : '#6b7280' }">
                          {{ selectedLlm.needsLlm ? '是' : '否（echo only）' }}
                        </span>
                      </div>
                      <div v-if="selectedLlm.needsLlm" class="dg-hrow">
                        <span class="dg-hlabel">密钥来源</span>
                        <span
                          class="dg-hval"
                          :style="{
                            color: selectedLlm.keySource === 'none' ? '#ef4444'
                                 : selectedLlm.keySource === 'byok' ? '#818cf8'
                                 : selectedLlm.keySource === 'auto' ? '#4ade80' : '#4ade80'
                          }"
                        >
                          {{
                            selectedLlm.keySource === 'none'
                              ? '✗ 未配置'
                              : selectedLlm.keySource === 'byok'
                                ? '⚡ BYOK'
                                : selectedLlm.keySource === 'auto'
                                  ? '⚡ 自动（账户内已有可用密钥）'
                                  : '⚡ 平台密钥'
                          }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">Handlers</span>
                        <span class="dg-hval dg-hval--sm">{{ selectedLlm.handlers.join(', ') || '—' }}</span>
                      </div>
                      <router-link
                        v-if="selectedLlm.needsLlm && selectedLlm.keySource === 'none'"
                        :to="{ name: 'account', hash: '#api-keys' }"
                        class="dg-llm-fix"
                        @click="accountKeysNav"
                      >→ 去账户页配置密钥</router-link>
                    </div>
                    <p v-else-if="loadingP2" class="dg-detail-loading">LLM 状态加载中…</p>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('cap')">
                    <span>执行能力</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('cap') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('cap')">
                    <div v-if="selectedCapability" class="dg-detail-capability">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">状态</span>
                        <span class="dg-hval" :style="{ color: selectedCapability.executable ? '#22c55e' : '#ef4444' }">
                          {{ selectedCapability.executable ? '可执行' : '不可执行' }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">Handlers</span>
                        <span class="dg-hval dg-hval--sm">{{ selectedCapability.handlers.join(', ') || '—' }}</span>
                      </div>
                      <p v-if="selectedCapability.reasons.length" class="dg-cap-reasons">
                        {{ selectedCapability.reasons.join('；') }}
                      </p>
                      <div v-if="selectedCapability.risk.high_risk" class="dg-cap-risk">
                        <p class="dg-cap-risk-title">高风险动作（需二次确认）</p>
                        <ul class="dg-cap-risk-list">
                          <li
                            v-for="d in selectedCapability.risk.details"
                            :key="`${d.handler}-${d.command_id || ''}-${d.reason || ''}`"
                          >
                            <code>{{ d.handler }}</code>
                            <span v-if="d.command_id"> · {{ d.command_id }}</span>
                            <span v-if="d.requires_approval"> · approval</span>
                          </li>
                        </ul>
                      </div>
                      <router-link
                        v-if="selectedCapability.recent_ops_audits.length"
                        :to="{ name: 'admin-ops-audit', query: { employee_id: selectedEmp!.id } }"
                        class="dg-cap-link"
                      >查看运维审计 →</router-link>
                    </div>
                    <p v-else-if="capLoading" class="dg-detail-loading">执行能力加载中…</p>
                  </div>

                  <div v-if="selectedRunNode" class="dg-detail-run-node">
                    <p class="dg-cap-title">本次图运行</p>
                    <div class="dg-hrow">
                      <span class="dg-hlabel">节点状态</span>
                      <span class="dg-hval" :style="{ color: RUN_STATUS_COLOR[selectedRunNode.status] }">
                        {{ RUN_STATUS_LABEL[selectedRunNode.status] }}
                      </span>
                    </div>
                    <div v-if="selectedRunNode.duration_ms > 0" class="dg-hrow">
                      <span class="dg-hlabel">耗时</span>
                      <span class="dg-hval">{{ formatDurationMs(selectedRunNode.duration_ms) }}</span>
                    </div>
                    <p v-if="selectedRunNode.error" class="dg-cap-reasons">{{ selectedRunNode.error }}</p>
                  </div>

                  <!-- Actions -->
                  <button class="dg-btn dg-btn--primary" @click="goUse(selectedEmp!)">
                    {{ isSelectedVirtual ? '去管家技能管理 →' : '去工作台使用 →' }}
                  </button>

                  <!-- Phase 3-c: task dispatch -->
                  <button class="dg-btn dg-btn--outline dg-btn--full" @click="showDispatch = !showDispatch">
                    {{ showDispatch ? '收起派发' : '派发任务 ▾' }}
                  </button>
                  <transition name="dg-fade">
                    <div v-if="showDispatch" class="dg-dispatch">
                      <textarea
                        v-model="taskBrief"
                        class="dg-dispatch-input"
                        placeholder="输入任务描述（brief）…"
                        rows="3"
                      />
                      <textarea
                        v-model="taskInputJson"
                        class="dg-dispatch-input dg-dispatch-input--mono"
                        placeholder='input_data JSON（对象），默认 {}'
                        rows="3"
                      />
                      <p v-if="selectedCapability?.handlers?.length" class="dg-dispatch-hint">
                        将触发 handlers：{{ selectedCapability.handlers.join(', ') }}
                      </p>
                      <label
                        v-if="selectedCapability?.risk?.high_risk"
                        class="dg-dispatch-confirm"
                      >
                        <input v-model="dispatchConfirmHighRisk" type="checkbox" />
                        <span>包含高风险动作，我已确认本次真实执行</span>
                      </label>
                      <div class="dg-dispatch-actions">
                        <button
                          class="dg-btn dg-btn--dispatch"
                          :disabled="taskRunning || !taskBrief.trim()"
                          @click="dispatchTask"
                        >
                          {{ taskRunning ? '执行中…' : '派发执行' }}
                        </button>
                        <button
                          class="dg-btn dg-btn--outline dg-btn--dispatch-secondary"
                          :disabled="taskRunning || !taskBrief.trim()"
                          @click="publishTaskToButler"
                        >
                          发布给管家
                        </button>
                      </div>
                      <div v-if="taskError" class="dg-dispatch-err">{{ taskError }}</div>
                      <pre v-if="taskResult" class="dg-dispatch-result">{{ taskResult }}</pre>
                    </div>
                  </transition>

                  <button class="dg-btn dg-btn--ghost" style="margin-top:4px" @click="selectedEmp = null">收起</button>
                </div>
              </transition>
</template>

<style scoped src="../AdminDutyEmployeeGraph.css"></style>
