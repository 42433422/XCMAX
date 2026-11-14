<template>
  <div class="traditional-mode page-view active" id="view-traditional-mode">
    <TmAddressBar :tm="tm" />
    <TmToolbar :tm="tm" />
    <TmFileList :tm="tm" />

    <div
      v-if="contextMenu.visible && contextMenu.file"
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      @click.stop
    >
      <div class="context-menu-item" @click="openFile(contextMenu.file!)">打开（读取）</div>
      <div class="context-menu-item" @click="startRename(contextMenu.file!)">重命名</div>
      <div class="context-menu-item context-menu-danger" @click="confirmDelete(contextMenu.file!)">删除</div>
    </div>

    <div v-if="showMkdirDialog" class="modal-overlay" @click.self="showMkdirDialog = false">
      <div class="modal-box">
        <div class="modal-header">新建文件夹</div>
        <div class="modal-body">
          <input v-model="newFolderName" type="text" placeholder="请输入文件夹名称" @keydown.enter="createFolder" ref="mkdirInputRef">
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showMkdirDialog = false">取消</button>
          <button class="btn btn-primary" @click="createFolder" :disabled="!newFolderName.trim()">创建</button>
        </div>
      </div>
    </div>

    <div v-if="renameDialog.show" class="modal-overlay" @click.self="renameDialog.show = false">
      <div class="modal-box">
        <div class="modal-header">重命名</div>
        <div class="modal-body">
          <input v-model="renameDialog.newName" type="text" @keydown.enter="doRename" ref="renameInputRef">
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="renameDialog.show = false">取消</button>
          <button class="btn btn-primary" @click="doRename" :disabled="!renameDialog.newName.trim()">确定</button>
        </div>
      </div>
    </div>

    <div v-if="previewImage.visible" class="modal-overlay image-preview-overlay" @click="closeImagePreview">
      <img :src="previewImage.url" :alt="previewImage.name" class="preview-image">
      <button class="close-preview-btn" @click="closeImagePreview">&times;</button>
    </div>

    <TmExcelPanel :tm="tm" />
    <TmInductMissingModal :tm="tm" />

    <div v-if="toastMessage" class="toast" :class="toastType">{{ toastMessage }}</div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./traditional-mode/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import TmAddressBar from './traditional-mode/TmAddressBar.vue'
import TmToolbar from './traditional-mode/TmToolbar.vue'
import TmFileList from './traditional-mode/TmFileList.vue'
import TmExcelPanel from './traditional-mode/TmExcelPanel.vue'
import TmInductMissingModal from './traditional-mode/TmInductMissingModal.vue'
import { assembleTmTraditionalMode } from './traditional-mode/assemble'

const tm = assembleTmTraditionalMode()

const {
  contextMenu, openFile, startRename, confirmDelete,
  showMkdirDialog, newFolderName, createFolder, mkdirInputRef,
  renameDialog, doRename, renameInputRef,
  previewImage, closeImagePreview,
  toastMessage, toastType,
} = tm
</script>

<style scoped src="./traditional-mode/traditional-mode.css"></style>
