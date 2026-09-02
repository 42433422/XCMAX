<script setup lang="ts">
import type { TemplatePreviewCtx } from './assemble'

// 拆分自 TemplatePreviewView.vue 模板（原第 359–387 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: TemplatePreviewCtx }>()

const {
  showReplaceModal, closeReplaceModal, replaceSourceTemplate, replaceTargetTemplateId,
  getTemplateTypeLabel, replacingTemplate, confirmReplaceTemplate,
} = props.tp

// 原 Options API 组件并未定义 replaceCandidates（模板 v-for 引用恒为 undefined，选项列表渲染为空）。
// 为保持行为零变更，这里保留同名 undefined 绑定，不"顺手修复"。
const replaceCandidates: any = undefined
</script>

<template>
    <div v-if="showReplaceModal" class="modal-overlay" @click.self="closeReplaceModal">
      <div class="modal-content" style="max-width:680px;">
        <div class="modal-header">
          <h3>基础模板替代</h3>
          <button type="button" class="modal-close" @click="closeReplaceModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="muted" style="font-size:13px;margin-bottom:12px;">
            源模板：{{ replaceSourceTemplate?.name }}<br>
            仅可选择同业务范围模板作为替代目标。
          </div>
          <div class="form-group">
            <label>目标模板</label>
            <select v-model="replaceTargetTemplateId" class="form-control">
              <option value="" disabled>请选择目标模板</option>
              <option v-for="tpl in replaceCandidates" :key="tpl.id" :value="tpl.id">
                {{ tpl.name }}（{{ getTemplateTypeLabel(tpl) }}）
              </option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeReplaceModal">取消</button>
          <button type="button" class="btn btn-primary" :disabled="!replaceTargetTemplateId || replacingTemplate" @click="confirmReplaceTemplate">
            {{ replacingTemplate ? '替代中...' : '确认替代' }}
          </button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./template-preview.css"></style>
