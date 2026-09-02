<script setup lang="ts">
import { watch } from 'vue'
import { api } from '../../api'
import { orchStepColor, orchStepEmployee } from '../../utils/orchestrationSteps'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 1028–1364 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  handoffPanelRef, pendingHandoff, makeCompletionResult, makeCompletionRef, finalizeLoading, finalizeError,
  orchestrationSession, workflowLinkOffer, linkMods, linkModId, linkBusy, linkError,
  isCanvasSkillIntent, handoffDescLabel, orchestrationButtonLabel, orchestrationButtonPendingLabel, orchestrationProgress, orchQualityReport,
  orchQualityMeta, orchVibecodingMeta, formatWallClockSec, orchestrationEtaDisplay, orchestrationTimingTooltip, orchestrationElapsedDisplay,
  canRunOrchestration, handoffFootNote, handoffAssetNote, hasWorkflow, placeholder, retryOrchStep,
  orchStepRunningSec, orchStepSlowHint, stepMsgSummary, stepMsgCurrentTool, stepMsgTodos, stepMsgSlowHint,
  resetMakeComposer, dismissWorkflowLinkOffer, openWorkflowCanvasOnly, confirmWorkflowModLink, dismissPendingHandoff, openMakeCompletionPrimary,
  openMakeCompletionSecondary, runOrchestration,
} = props.wb
</script>

<template>
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
            :key="String(st.id || st.label || '')"
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
</template>
