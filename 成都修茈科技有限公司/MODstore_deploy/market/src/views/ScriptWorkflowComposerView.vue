<template>
  <div class="swc">
    <header class="swc-head">
      <button class="swc-back" type="button" @click="goList">← 返回列表</button>
      <h1>{{ headTitle }}</h1>
      <ol class="swc-steps">
        <li :class="{ done: stageRank >= 1, active: stage === 'brief' }">1 描述需求</li>
        <li :class="{ done: stageRank >= 2, active: stage === 'loop' }">2 AI 编码</li>
        <li :class="{ done: stageRank >= 3, active: stage === 'sandbox' }">3 沙箱试用</li>
        <li :class="{ done: stageRank >= 4 }">4 启用</li>
      </ol>
    </header>

    <!-- ===================== Brief 阶段 ===================== -->
    <section v-if="stage === 'brief'" class="swc-brief">
      <p class="swc-brief-tip">
        填写越详细，一次成功率越高。所有字段都会作为 AI 生成时的上下文，建议复述具体业务术语、字段名、阈值等。
      </p>

      <details class="swc-templates">
        <summary>从模板开始（可选）</summary>
        <div class="swc-templates-list">
          <button
            v-for="t in templates"
            :key="t.key"
            type="button"
            class="swc-template"
            @click="applyTemplate(t.key)"
          >
            <strong>{{ t.title }}</strong>
            <span>{{ t.desc }}</span>
          </button>
        </div>
      </details>

      <div class="swc-field">
        <label>任务目标 <span class="req">*</span></label>
        <textarea
          v-model="brief.goal"
          rows="3"
          placeholder="例：每天把多个销售明细 .xlsx 汇总成一张当日总览表，按门店分 sheet，按 SKU 排序"
        />
        <p v-if="briefHints.goal" class="swc-hint">{{ briefHints.goal }}</p>
      </div>

      <div class="swc-field">
        <label>输入数据 <span class="req">*</span></label>
        <input type="file" multiple @change="onFilesPicked" />
        <ul v-if="uploadedFiles.length" class="swc-file-list">
          <li v-for="(f, idx) in uploadedFiles" :key="idx">
            <span class="swc-file-name">{{ f.name }}</span>
            <span class="swc-file-size">{{ humanSize(f.size) }}</span>
            <input
              v-model="brief.inputs[idx].description"
              type="text"
              class="swc-file-desc"
              placeholder="文件含义（如：销售明细，列：日期/SKU/数量/金额）"
            />
            <button type="button" class="swc-file-x" @click="removeFile(idx)">×</button>
          </li>
        </ul>
        <p v-if="briefHints.inputs" class="swc-hint">{{ briefHints.inputs }}</p>
      </div>

      <div class="swc-field">
        <label>输出要求 <span class="req">*</span></label>
        <textarea
          v-model="brief.outputs"
          rows="3"
          placeholder="例：outputs/总览.xlsx，每行字段：门店 / SKU / 销量 / 销售额，按销售额倒序"
        />
        <p v-if="briefHints.outputs" class="swc-hint">{{ briefHints.outputs }}</p>
      </div>

      <div class="swc-field">
        <label>成功判定标准 <span class="req">*</span></label>
        <textarea
          v-model="brief.acceptance"
          rows="3"
          placeholder="例：outputs/总览.xlsx 存在；行数 = 输入文件 SKU 去重数；销售额合计与输入合计相等"
        />
        <p class="swc-hint">这条会作为 AI 验收官的依据，越具体越好。</p>
        <p v-if="briefHints.acceptance" class="swc-hint">{{ briefHints.acceptance }}</p>
      </div>

      <div class="swc-field">
        <label>失败兜底（可选）</label>
        <textarea
          v-model="brief.fallback"
          rows="2"
          placeholder="例：遇到金额为空的行用 ai('该行金额疑似缺失，请基于上下文推断') 兜底"
        />
      </div>

      <div class="swc-field swc-row">
        <label>触发方式</label>
        <select v-model="brief.trigger_type">
          <option value="manual">手动</option>
          <option value="cron">定时 (cron)</option>
          <option value="webhook">Webhook</option>
          <option value="employee">员工调用</option>
        </select>
      </div>

      <div class="swc-actions">
        <button type="button" class="swc-go" :disabled="busy" @click="startAgentLoop">
          {{ busy ? '启动中…' : '开始让 AI 写脚本' }}
        </button>
      </div>
    </section>

    <!-- ===================== Loop / Sandbox 阶段 ===================== -->
    <section v-else class="swc-runtime">
      <aside class="swc-chat">
        <header class="swc-chat-head">
          <h2>对话</h2>
          <span v-if="loopRunning" class="swc-running">运行中…</span>
          <span v-else-if="outcome?.ok" class="swc-ok">已通过自动验收</span>
          <span v-else-if="outcome" class="swc-bad">未通过</span>
        </header>
        <ol class="swc-events">
          <li v-for="(ev, idx) in events" :key="idx" :class="`ev-${ev.type}`">
            <strong>{{ eventLabel(ev) }}</strong>
            <template v-if="ev.type === 'plan'">
              <p class="swc-plan-summary">{{ formatPlanMdForDisplay(String(ev.payload?.plan_md || '')) }}</p>
              <details v-if="planMdHasMermaid(ev.payload?.plan_md)" class="swc-plan-mermaid">
                <summary>查看流程图原文</summary>
                <pre>{{ mermaidExcerpt(ev.payload?.plan_md) }}</pre>
              </details>
            </template>
            <pre v-else-if="['code', 'repair'].includes(ev.type)">{{ trimCode(ev.payload?.code) }}</pre>
            <p v-else-if="ev.type === 'check'">
              {{ ev.payload?.ok ? '静态检查通过' : '失败：' + (ev.payload?.errors || []).join('；') }}
            </p>
            <p v-else-if="ev.type === 'run'">
              {{ ev.payload?.ok ? `成功，产物 ${ev.payload?.outputs?.length || 0} 个` : '失败' }}
              <small v-if="ev.payload?.stderr_tail">{{ tail(ev.payload.stderr_tail, 240) }}</small>
            </p>
            <p v-else-if="ev.type === 'observe'">
              {{ ev.payload?.ok ? '验收通过' : '验收不通过：' + (ev.payload?.reason || '') }}
            </p>
            <p v-else-if="ev.type === 'error'">{{ ev.payload?.reason || '出错' }}</p>
            <p v-else-if="ev.type === 'context'">已收集上下文（输入摘要、SDK 文档）</p>
            <p v-else-if="ev.type === 'done'">已完成。你可以保存为工作流，并进入沙箱试用。</p>
          </li>
        </ol>
        <div v-if="!loopRunning" class="swc-feedback">
          <textarea
            v-model="feedback"
            rows="2"
            :placeholder="
              !sessionId && workflowId
                ? '描述需要改进的方向（AI 会基于现有脚本重新生成）…'
                : '对生成结果不满意？描述一下要改的点，AI 会再来一轮…'
            "
          />
          <button type="button" :disabled="!feedback.trim()" @click="submitFeedback">
            {{ !sessionId && workflowId ? '让 AI 改进此脚本' : '让 AI 再改' }}
          </button>
        </div>
      </aside>

      <main class="swc-main">
        <div class="swc-tabs">
          <button :class="{ active: tab === 'code' }" @click="tab = 'code'">脚本</button>
          <button :class="{ active: tab === 'output' }" @click="tab = 'output'">运行结果</button>
          <button v-if="stage === 'sandbox'" :class="{ active: tab === 'sandbox' }" @click="tab = 'sandbox'">
            沙箱试用
          </button>
        </div>

        <div v-if="tab === 'code'" class="swc-code-pane">
          <pre><code>{{ currentCode || '（暂无脚本）' }}</code></pre>
        </div>

        <div v-else-if="tab === 'output'" class="swc-output-pane">
          <h3>stdout 末段</h3>
          <pre>{{ runStdout || '(无)' }}</pre>
          <h3>stderr 末段</h3>
          <pre>{{ runStderr || '(无)' }}</pre>
          <h3>产物</h3>
          <ul v-if="runOutputs.length">
            <li v-for="o in runOutputs" :key="o.filename">{{ o.filename }} · {{ humanSize(o.size || 0) }}</li>
          </ul>
          <p v-else>暂无</p>
        </div>

        <div v-else-if="tab === 'sandbox'" class="swc-sandbox-pane">
          <p>用真实业务数据手动跑沙箱，确认无误后即可启用。</p>
          <input type="file" multiple @change="onSandboxFilesPicked" />
          <ul v-if="sandboxFiles.length" class="swc-file-list">
            <li v-for="(f, idx) in sandboxFiles" :key="idx">
              {{ f.name }} <span>{{ humanSize(f.size) }}</span>
              <button type="button" class="swc-file-x" @click="sandboxFiles.splice(idx, 1)">×</button>
            </li>
          </ul>
          <button :disabled="sandboxBusy" @click="runManualSandbox">
            {{ sandboxBusy ? '正在跑沙箱…' : '提交并运行' }}
          </button>
          <div v-if="lastSandboxRun" class="swc-sandbox-result">
            <p>
              本次结果：<strong :class="lastSandboxRun.status === 'success' ? 'ok' : 'bad'">{{
                lastSandboxRun.status
              }}</strong>
            </p>
            <pre>stdout: {{ tail(lastSandboxRun.stdout_tail, 1200) }}</pre>
            <pre v-if="lastSandboxRun.stderr_tail">stderr: {{ tail(lastSandboxRun.stderr_tail, 1200) }}</pre>
            <ul v-if="lastSandboxRun.outputs?.length">
              <li v-for="o in lastSandboxRun.outputs" :key="o.filename">
                {{ o.filename }}
                <button type="button" class="swc-download" @click="() => downloadSandboxOutput(o)">
                  下载
                </button>
              </li>
            </ul>
            <button v-if="canActivate" class="swc-activate" @click="activate">满意，启用此工作流</button>
          </div>
        </div>

        <footer v-if="stage === 'loop' && outcome?.ok && !committed" class="swc-commit-bar">
          <input v-model="workflowName" placeholder="给这个脚本工作流起个名字" />
          <button :disabled="!workflowName.trim()" @click="commitToWorkflow">保存为工作流 → 进入沙箱试用</button>
        </footer>
      </main>
    </section>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：Brief/Agent 循环/沙箱逻辑在 ./script-workflow-composer/，
// 样式在 ./script-workflow-composer/scriptWorkflowComposer.css。
import { useScriptWorkflowComposer } from './script-workflow-composer/useScriptWorkflowComposer'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  formatPlanMdForDisplay,
  stage, stageRank, brief, uploadedFiles, events, sessionId, outcome,
  loopRunning, busy, tab, committed, workflowId, workflowName, feedback,
  sandboxFiles, sandboxBusy, lastSandboxRun, canActivate, headTitle, briefHints, templates,
  applyTemplate, onFilesPicked, removeFile, onSandboxFilesPicked,
  planMdHasMermaid, mermaidExcerpt, humanSize, trimCode, tail, eventLabel,
  currentCode, lastRun, runStdout, runStderr, runOutputs,
  handleEvent, startAgentLoop, startEditWithAi, submitFeedback,
  commitToWorkflow, runManualSandbox, downloadSandboxOutput, activate, goList,
} = useScriptWorkflowComposer()
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./script-workflow-composer/scriptWorkflowComposer.css"></style>
