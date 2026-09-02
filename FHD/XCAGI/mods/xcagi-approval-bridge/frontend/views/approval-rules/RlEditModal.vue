<script setup>
import Modal from '@/components/Modal.vue'
import { defineProps } from 'vue'

// 拆分自 ApprovalRulesView.vue 模板（原第 108–130 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const { editingIndex, closeEdit, editForm, saveEdit } = props.tm
</script>

<template>
    <Modal
      :model-value="editingIndex !== null"
      title="编辑规则"
      max-width="420px"
      @close="closeEdit"
    >
      <div class="form-group">
        <label>描述</label>
        <input type="text" v-model="editForm.description" />
      </div>
      <div class="form-group">
        <label>触发方式</label>
        <select v-model="editForm.trigger">
          <option value="always">始终审批</option>
          <option value="conditional">条件审批</option>
          <option value="never">从不审批</option>
        </select>
      </div>
      <template #footer>
        <button class="btn-cancel" @click="closeEdit">取消</button>
        <button class="btn-save" @click="saveEdit">保存</button>
      </template>
    </Modal>
</template>

<style scoped src="./approval-rules.css"></style>
