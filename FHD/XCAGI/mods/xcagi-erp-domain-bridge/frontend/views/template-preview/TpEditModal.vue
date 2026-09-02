<script setup lang="ts">
import type { TemplatePreviewCtx } from './assemble'

// 拆分自 TemplatePreviewView.vue 模板（原第 333–358 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: TemplatePreviewCtx }>()

const {
  showEditModal, closeEditModal, editingTemplate, saveTemplateEdit,
} = props.tp
</script>

<template>
    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-content">
        <div class="modal-header">
          <h3>编辑模板</h3>
          <button type="button" class="modal-close" @click="closeEditModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>模板名称</label>
            <input type="text" v-model="editingTemplate.name" class="form-control" />
          </div>
          <div class="form-group">
            <label>分类</label>
            <select v-model="editingTemplate.category" class="form-control">
              <option value="excel">Excel</option>
              <option value="word">Word</option>
              <option value="label">标签打印</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeEditModal">取消</button>
          <button type="button" class="btn btn-primary" @click="saveTemplateEdit">保存</button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./template-preview.css"></style>
