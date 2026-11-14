<template>
  <div class="batch-analyze-view page-view">
    <div class="page-header">
      <h2>批量分析</h2>
      <p class="muted">自动拆解、分组并匹配模板</p>
    </div>

    <div v-if="store.phase === 'idle' && store.extractedSheets.length === 0" class="empty-state-card">
      <div class="empty-icon">📊</div>
      <div class="empty-title">暂无分析数据</div>
      <div class="empty-desc">请从「业务对接」页面选择文件夹进行批量上传</div>
      <button class="btn btn-primary" @click="goToBusinessDocking">前往业务对接</button>
    </div>

    <template v-else>
      <div class="progress-section">
        <div class="progress-header">
          <span class="progress-phase">{{ store.phaseLabel }}</span>
          <span class="progress-percent">{{ store.progress }}%</span>
        </div>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :class="`phase-${store.phase}`"
            :style="{ width: store.progress + '%' }"
          ></div>
        </div>
        <div class="progress-detail muted">{{ store.progressText }}</div>
      </div>

      <div v-if="store.errorMessage" class="error-card">
        <span class="error-icon">❌</span>
        <span>{{ store.errorMessage }}</span>
        <button class="btn btn-sm btn-secondary" @click="retry">重试</button>
      </div>

      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-value">{{ store.extractedSheets.length }}</div>
          <div class="stat-label">已拆解工作表</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ store.groups.length }}</div>
          <div class="stat-label">分组数量</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ matchedTemplatesCount }}</div>
          <div class="stat-label">已匹配模板</div>
        </div>
        <div v-if="store.failedFiles.length > 0" class="stat-card stat-warning">
          <div class="stat-value">{{ store.failedFiles.length }}</div>
          <div class="stat-label">读取失败</div>
        </div>
      </div>

      <div v-if="store.failedFiles.length > 0" class="failed-files-card">
        <div class="failed-files-header">
          <span class="failed-icon">⚠️</span>
          <span class="failed-title">以下文件读取失败</span>
          <button class="btn btn-xs btn-outline" @click="showFailedFiles = !showFailedFiles">
            {{ showFailedFiles ? '收起' : '展开' }}
          </button>
        </div>
        <div v-if="showFailedFiles" class="failed-files-list">
          <div
            v-for="(file, idx) in store.failedFiles"
            :key="idx"
            class="failed-file-item"
          >
            <span class="failed-file-name">{{ file.fileName }}</span>
            <span class="failed-file-error muted">{{ file.error }}</span>
          </div>
        </div>
      </div>

      <div v-if="store.groups.length > 0" class="groups-section">
        <div class="section-header">
          <h3>分组结果</h3>
          <div class="section-actions">
            <button class="btn btn-sm btn-secondary" @click="showAllGroups = !showAllGroups">
              {{ showAllGroups ? '收起详情' : '展开全部' }}
            </button>
          </div>
        </div>

        <div class="groups-toolbar">
          <label class="select-all-label">
            <input
              type="checkbox"
              v-model="selectAllGroups"
              @change="toggleSelectAll"
            >
            全选
          </label>
          <span class="selected-count muted">{{ selectedGroupIds.length }} 个已选</span>

          <button
            class="btn btn-sm btn-outline"
            :disabled="selectedGroupIds.length < 2"
            @click="mergeSelectedGroups"
          >
            合并所选
          </button>
        </div>

        <div v-if="matchedGroups.length > 0" class="section-sub-header">
          <h4>已匹配分组 <span class="muted">({{ matchedGroups.length }})</span></h4>
        </div>
        <div class="groups-list matched-groups">
          <BaGroupCard
            v-for="group in matchedGroups"
            :key="group.id"
            :tp="ba"
            :group="group"
          />
        </div>

        <div v-if="unknownGroups.length > 0" class="section-sub-header unknown-section-header">
          <h4>通用分组 <span class="muted">({{ unknownGroups.length }})</span></h4>
        </div>
        <div v-if="unknownGroups.length > 0" class="groups-list unknown-groups">
          <BaGroupCard
            v-for="group in unknownGroups"
            :key="group.id"
            :tp="ba"
            :group="group"
            unknown
          />
        </div>
      </div>

      <div v-if="store.phase === 'done'" class="action-section">
        <button class="btn btn-primary btn-lg" @click="saveAllTemplates" :disabled="saveLoading">
          {{ saveLoading ? `保存中 (${saveProgress.current}/${saveProgress.total})` : '全部保存为模板' }}
        </button>
        <button class="btn btn-secondary btn-lg" @click="exportReport">
          导出分析报告
        </button>
        <button class="btn btn-secondary" @click="startNewAnalysis">
          新建分析
        </button>
      </div>
      <div v-if="saveLoading && saveProgress.total > 0" class="save-progress-card">
        <div class="save-progress-label">正在保存：{{ saveProgress.currentGroup }}</div>
        <div class="save-progress-bar">
          <div
            class="save-progress-fill"
            :style="{ width: (saveProgress.current / saveProgress.total * 100) + '%' }"
          ></div>
        </div>
      </div>
    </template>

    <InputDialog
      v-model="showNameInputDialog"
      :title="nameInputDialogConfig.title"
      :message="nameInputDialogConfig.message"
      :placeholder="nameInputDialogConfig.placeholder"
      confirm-text="确定"
      @confirm="handleNameInputConfirm"
    />

    <BaPreviewModal :tp="ba" />
    <BaMoveModal :tp="ba" />
  </div>
</template>

<script setup lang="ts">
import InputDialog from '@/components/InputDialog.vue'
import BaGroupCard from './batch-analyze/BaGroupCard.vue'
import BaPreviewModal from './batch-analyze/BaPreviewModal.vue'
import BaMoveModal from './batch-analyze/BaMoveModal.vue'
import { assembleBatchAnalyze } from './batch-analyze/assemble'

defineOptions({ name: 'BatchAnalyzeView' })

const ba = assembleBatchAnalyze()

const {
  store,
  showFailedFiles, showAllGroups,
  matchedTemplatesCount, matchedGroups, unknownGroups,
  goToBusinessDocking, retry,
  selectAllGroups, toggleSelectAll, selectedGroupIds, mergeSelectedGroups,
  saveLoading, saveProgress, saveAllTemplates, exportReport, startNewAnalysis,
  showNameInputDialog, nameInputDialogConfig, handleNameInputConfirm,
} = ba
</script>

<style scoped src="./batch-analyze/batch-analyze.css"></style>
