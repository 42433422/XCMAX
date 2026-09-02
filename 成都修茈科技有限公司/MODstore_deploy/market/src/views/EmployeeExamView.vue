<template>
  <div class="employee-exam-page">
    <div class="exam-grid">
      <section class="exam-panel exam-panel--control">
        <header class="exam-panel-head">
          <h1 class="exam-page-title">考试试跑</h1>
          <p class="exam-page-sub">Word 全量读取 → 自动生成 HTML 量化报告</p>
        </header>

        <div class="exam-config">
          <label class="exam-label" for="exam-employee-select">员工包</label>
          <select id="exam-employee-select" v-model="selectedEmployeeId" class="exam-select" :disabled="loadingEmployees || pipelineBusy">
            <option v-if="!employeeOptions.length" value="">暂无可用员工包</option>
            <option v-for="opt in employeeOptions" :key="opt.id" :value="opt.id">
              {{ opt.name }}
            </option>
          </select>
          <button type="button" class="btn btn-ghost btn-sm" :disabled="loadingEmployees" @click="loadEmployees">刷新</button>
        </div>

        <div
          class="exam-dropzone"
          :class="{ 'exam-dropzone--active': dragOver, 'exam-dropzone--has-file': !!selectedFile }"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >
          <input ref="fileInputRef" type="file" class="exam-file-input" :accept="acceptAttr" @change="onFileInput" />
          <template v-if="selectedFile">
            <div class="exam-file-chip">
              <span class="exam-file-chip-name" :title="selectedFile.name">{{ selectedFile.name }}</span>
              <span class="exam-file-chip-meta">{{ formatBytes(selectedFile.size) }}</span>
            </div>
            <button type="button" class="btn btn-ghost btn-sm" :disabled="pipelineBusy" @click="clearFile">更换</button>
          </template>
          <template v-else>
            <p class="exam-drop-title">拖入或选择文件</p>
            <p class="exam-drop-sub">{{ dropZoneSubtext }}</p>
            <button type="button" class="btn btn-connect btn-sm" :disabled="pipelineBusy" @click="fileInputRef?.click()">选择文件</button>
          </template>
        </div>

        <p v-if="employeesError" class="exam-alert exam-alert--err">{{ employeesError }}</p>
        <p v-if="jsonReportUploadHint" class="exam-alert">{{ jsonReportUploadHint }}</p>
        <p v-if="employeeAutoSwitchNote" class="exam-alert exam-alert--ok">
          {{ employeeAutoSwitchNote }}
        </p>
        <p v-if="legacyDocHint" class="exam-alert exam-alert--warn">{{ legacyDocHint }}</p>
        <p v-if="fileHint" class="exam-alert exam-alert--warn">{{ fileHint }}</p>

        <div v-if="pipelineComplete && !pipelineBusy" class="exam-done-chip">流程已完成</div>
        <p v-if="lastRunStatusLine" class="exam-run-status">{{ lastRunStatusLine }}</p>

        <section v-else-if="showPipelinePanel" class="exam-pipeline" aria-live="polite" :aria-busy="pipelineBusy">
          <div class="exam-pipeline-bar-wrap">
            <div class="exam-pipeline-bar" role="progressbar" :aria-valuenow="pipelinePercent" aria-valuemin="0" aria-valuemax="100">
              <div class="exam-pipeline-bar-fill" :style="{ width: `${pipelinePercent}%` }" />
            </div>
            <span class="exam-pipeline-pct">{{ pipelinePercent }}%</span>
          </div>
          <p v-if="pipelineMessage" class="exam-pipeline-message">{{ pipelineMessage }}</p>
          <ol class="exam-pipeline-steps">
            <li v-for="step in pipelineStepViews" :key="step.id" class="exam-pipeline-step" :class="`exam-pipeline-step--${step.status}`">
              <span class="exam-pipeline-step-icon" aria-hidden="true">{{ step.icon }}</span>
              <span class="exam-pipeline-step-label">{{ step.label }}</span>
            </li>
          </ol>
        </section>

        <button type="button" class="btn btn-action btn-block" :disabled="!canRun" @click="runExam">
          {{ examPrimaryLabel }}
        </button>

        <p v-if="runError" class="exam-alert exam-alert--err">{{ runError }}</p>
        <p v-if="reportError && !pipelineBusy" class="exam-alert exam-alert--err">
          {{ reportError }}
        </p>
      </section>

      <section class="exam-panel exam-panel--output">
        <div v-if="!htmlReportPreviewUrl && !pipelineBusy" class="exam-output-empty">
          <p class="exam-output-empty-title">报告预览区</p>
          <p class="exam-output-empty-sub">完成左侧试跑后，HTML 量化报告将显示在此处</p>
        </div>

        <div v-else-if="pipelineBusy" class="exam-output-empty exam-output-empty--busy">
          <p class="exam-output-empty-title">正在生成报告…</p>
          <p class="exam-output-empty-sub">{{ pipelineMessage || '请稍候' }}</p>
        </div>

        <article v-else ref="reportHeroRef" class="exam-report-card">
          <header class="exam-report-card-head">
            <div>
              <h2 class="exam-report-card-title">量化报告</h2>
              <p v-if="lastReadSourceFile" class="exam-report-card-sub">{{ lastReadSourceFile }}</p>
            </div>
            <div class="exam-report-card-actions">
              <button type="button" class="btn btn-ghost btn-sm" @click="openHtmlReportInNewTab">新窗口</button>
              <button
                v-if="htmlReportDownload"
                type="button"
                class="btn btn-connect btn-sm"
                :disabled="downloadingKey === htmlReportDownloadKey"
                @click="downloadHtmlReport"
              >
                {{ downloadingKey === htmlReportDownloadKey ? '…' : '下载' }}
              </button>
            </div>
          </header>
          <iframe class="exam-report-card-frame" :src="htmlReportPreviewUrl" title="量化报告预览" sandbox="allow-same-origin" />
        </article>

        <details v-if="showMoreDrawer" class="exam-more">
          <summary>更多：摘要与下载</summary>
          <div v-if="resultSummary" class="exam-more-summary" v-html="resultSummaryHtml" />
          <div v-if="showManualReportButton" class="exam-more-actions">
            <button type="button" class="btn btn-action btn-sm" :disabled="pipelineBusy" @click="generateReportFromRead">
              {{ manualReportButtonLabel }}
            </button>
          </div>
          <ul v-if="downloads.length" class="exam-more-files">
            <li v-for="d in downloads" :key="`${d.jobId}:${d.filename}`">
              <button
                type="button"
                class="exam-more-file-btn"
                :disabled="downloadingKey === `${d.jobId}:${d.filename}`"
                @click="downloadOutput(d)"
              >
                {{ downloadingKey === `${d.jobId}:${d.filename}` ? '下载中…' : d.label || d.filename }}
              </button>
            </li>
          </ul>
          <details v-if="rawJsonPreview" class="exam-raw">
            <summary>原始 JSON</summary>
            <pre class="exam-raw-pre">{{ rawJsonPreview }}</pre>
          </details>
        </details>

        <section v-if="showFailurePanel" class="exam-failure">
          <h2 class="exam-failure-title">试跑失败</h2>
          <div v-if="resultSummary" class="exam-failure-body" v-html="resultSummaryHtml" />
        </section>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./employee-exam/，样式在 ./employee-exam/employee-exam.css。
import { formatBytes } from './employee-exam/employeeExamTypes'
import { useEmployeeExamEmployees } from './employee-exam/useEmployeeExamEmployees'
import { useEmployeeExam } from './employee-exam/useEmployeeExam'

const {
  employeeOptions,
  selectedEmployeeId,
  loadingEmployees,
  employeesError,
  loadEmployees,
} = useEmployeeExamEmployees()

const {
  selectedFile,
  fileInputRef,
  dragOver,
  onFileInput,
  onDrop,
  clearFile,
  acceptAttr,
  dropZoneSubtext,
  jsonReportUploadHint,
  pipelineBusy,
  showPipelinePanel,
  pipelineStepViews,
  pipelinePercent,
  pipelineMessage,
  pipelineComplete,
  runExam,
  canRun,
  examPrimaryLabel,
  runError,
  reportError,
  employeeAutoSwitchNote,
  legacyDocHint,
  fileHint,
  lastRunStatusLine,
  showMoreDrawer,
  // 以下三个为测试兼容面：EmployeeExamView.test.ts 经 wrapper.vm 访问
  lastRunKind,
  canGenerateReportFromRead,
  showManualReportButton,
  manualReportButtonLabel,
  resultSummary,
  resultSummaryHtml,
  rawJsonPreview,
  downloads,
  downloadingKey,
  downloadOutput,
  showFailurePanel,
  htmlReportPreviewUrl,
  htmlReportDownload,
  htmlReportDownloadKey,
  reportHeroRef,
  lastReadSourceFile,
  generateReportFromRead,
  downloadHtmlReport,
  openHtmlReportInNewTab,
  revokeHtmlPreview,
} = useEmployeeExam({ selectedEmployeeId, employeeOptions, loadingEmployees, loadEmployees })
</script>

<style scoped src="./employee-exam/employee-exam.css"></style>
