<template>
  <div class="page-view etl-docking" id="view-etl-docking">
    <div class="page-content">
      <div class="page-header">
        <h2>送货单 ETL 对接</h2>
        <p class="muted">上传送货单 / 发货单 Excel，识别抬头与明细后确认，自动写入客户、产品与发货单。</p>
      </div>

      <div class="etl-card dock-card">
        <div class="dock-card-title">选择文件</div>
        <div class="etl-actions">
          <button type="button" class="btn btn-primary etl-upload-btn" :disabled="processing" @click="triggerOfficeDockingFolder">
            <i class="fa fa-folder-open-o" aria-hidden="true"></i>
            {{ processing ? '识别中...' : '选择文件夹' }}
          </button>
          <button type="button" class="btn btn-secondary etl-upload-btn" :disabled="processing" @click="triggerOfficeDocking">
            <i class="fa fa-file-o" aria-hidden="true"></i>
            选择文件
          </button>
          <span class="muted etl-hint">支持 .xlsx / .xls / .csv / .pdf / .docx / .pptx</span>
        </div>
        <p class="muted etl-lead">上传后系统会调用办公读取员工识别内容，检出「送货单 / 发货单」意图后，可在下方确认并写入数据库。</p>
      </div>

      <input
        ref="officeDockingInputRef"
        type="file"
        multiple
        accept=".xlsx,.xlsm,.xls,.csv,.docx,.doc,.pdf,.pptx,.ppt"
        style="display: none"
        @change="onOfficeDockingFileChange"
      />
      <input
        ref="officeDockingFolderInputRef"
        type="file"
        multiple
        webkitdirectory
        directory
        accept=".xlsx,.xlsm,.xls,.csv,.docx,.doc,.pdf,.pptx,.ppt"
        style="display: none"
        @change="onOfficeDockingFileChange"
      />

      <ChatOfficeDockingReview
        v-if="officeDockingPanelOpen || officeDockingReviewItems.length"
        :items="officeDockingReviewItems"
        :processing="processing"
        @toggle-target="toggleOfficeDockingTarget"
        @update-template-name="updateOfficeDockingTemplateName"
        @confirm="confirmOfficeDockingReview"
        @skip="skipCurrentOfficeDockingReview"
        @close="clearOfficeDockingReview"
      />

      <div v-if="!officeDockingPanelOpen && !officeDockingReviewItems.length" class="etl-empty muted">
        尚未上传文件。选择并上传后，此处将出现「送货单识别审核」区块。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ChatOfficeDockingReview from '@/components/chat/ChatOfficeDockingReview.vue'
import { useChatOfficeDocking } from '@/composables/useChatOfficeDocking'

const {
  officeDockingInputRef,
  officeDockingFolderInputRef,
  officeDockingProcessing,
  officeDockingPanelOpen,
  officeDockingReviewItems,
  triggerOfficeDocking,
  triggerOfficeDockingFolder,
  onOfficeDockingFileChange,
  toggleOfficeDockingTarget,
  updateOfficeDockingTemplateName,
  confirmOfficeDockingReview,
  skipCurrentOfficeDockingReview,
  clearOfficeDockingReview,
} = useChatOfficeDocking({
  // 独立页无聊天上下文：写库结果以审核面板摘要呈现，聊天相关回调置空。
  addAndSaveMessage: async () => {},
  stageExcelAnalysisContext: () => {},
  sendDatabaseImportMessage: async () => {},
})

const processing = officeDockingProcessing
</script>

<style scoped>
.etl-docking {
  padding: 12px;
}

.etl-card {
  margin-bottom: 16px;
}

.etl-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.etl-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.etl-hint {
  font-size: 12px;
}

.etl-lead {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.5;
}

.etl-empty {
  padding: 16px;
  border: 1px dashed #c5d4dc;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
