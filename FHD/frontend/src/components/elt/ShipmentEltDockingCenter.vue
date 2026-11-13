<template>
  <div class="page-view elt-docking" id="view-elt-docking">
    <div class="page-content">
      <div class="page-header">
        <h2>送货单 ETL 对接</h2>
        <p class="muted">上传送货单 / 发货单 Excel，识别抬头与明细后确认，自动写入客户、产品与发货单。</p>
      </div>

      <div class="elt-card dock-card">
        <div class="dock-card-title">选择文件</div>
        <div class="elt-actions">
          <button type="button" class="btn btn-primary elt-upload-btn" :disabled="processing" @click="triggerOfficeDocking">
            <i class="fa fa-upload" aria-hidden="true"></i>
            {{ processing ? '识别中...' : '选择并上传文件' }}
          </button>
          <span class="muted elt-hint">支持 .xlsx / .xls / .csv / .pdf / .docx / .pptx</span>
        </div>
        <p class="muted elt-lead">上传后用数据对接 ELT 解析。工作表模板可选，保存后提交入库审批，通过后才写入。</p>
      </div>

      <input
        ref="officeDockingInputRef"
        type="file"
        multiple
        accept=".xlsx,.xlsm,.xls,.csv,.docx,.doc,.pdf,.pptx,.ppt"
        style="display: none"
        @change="onOfficeDockingFileChange"
      />

      <ChatOfficeDockingReview
        v-if="officeDockingPanelOpen || officeDockingReviewItems.length"
        :items="officeDockingReviewItems"
        :processing="processing"
        @toggle-target="toggleOfficeDockingTarget"
        @pick-template="pickOfficeWorksheetTemplate"
        @confirm="confirmOfficeDockingReview"
        @close="clearOfficeDockingReview"
      />

      <div v-if="!officeDockingPanelOpen && !officeDockingReviewItems.length" class="elt-empty muted">
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
  officeDockingProcessing,
  officeDockingPanelOpen,
  officeDockingReviewItems,
  triggerOfficeDocking,
  onOfficeDockingFileChange,
  toggleOfficeDockingTarget,
  pickOfficeWorksheetTemplate,
  confirmOfficeDockingReview,
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
.elt-docking {
  padding: 12px;
}

.elt-card {
  margin-bottom: 16px;
}

.elt-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.elt-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.elt-hint {
  font-size: 12px;
}

.elt-lead {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.5;
}

.elt-empty {
  padding: 16px;
  border: 1px dashed #c5d4dc;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
