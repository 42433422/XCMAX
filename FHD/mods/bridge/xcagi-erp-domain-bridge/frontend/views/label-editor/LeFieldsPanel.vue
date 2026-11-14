<script setup lang="ts">
import type { LabelEditorCtx } from './assemble'

// 拆分自 LabelEditorView.vue 模板（原第 62–127 行 fields-panel 块）；模板逐字迁移，行为不变。
const props = defineProps<{ tp: LabelEditorCtx }>()

const {
  fields, selectedFieldId, selectField, deleteField,
  addField, selectedField, onFieldChange,
} = props.tp
</script>

<template>
  <div class="fields-panel">
    <div class="panel-header">
      <h3><i class="fa fa-list-alt" aria-hidden="true"></i> 字段列表</h3>
      <button class="btn btn-sm btn-primary" @click="addField"><i class="fa fa-plus" aria-hidden="true"></i> 添加字段</button>
    </div>

    <div class="fields-list">
      <div
        v-for="(field, index) in fields"
        :key="field.id"
        :class="['field-item', { selected: selectedFieldId === field.id }]"
        @click="selectField(field)"
      >
        <div class="field-info">
          <span class="field-label">{{ field.label }}</span>
          <span class="field-value">{{ field.value || '(空)' }}</span>
          <span class="field-type" :class="field.type">{{ field.type === 'fixed' ? '固定' : '可变' }}</span>
        </div>
        <div class="field-actions">
          <button class="btn-icon" @click.stop="deleteField(index)" title="删除">
            <i class="fa fa-trash-o" aria-hidden="true"></i>
          </button>
        </div>
      </div>
    </div>

    <div v-if="fields.length === 0" class="empty-fields">
      <p>暂无字段</p>
      <p class="hint">上传标签图片自动识别或手动添加</p>
    </div>

    <div class="panel-section" v-if="selectedField">
      <h4><i class="fa fa-cog" aria-hidden="true"></i> 选中字段属性</h4>

      <div class="property-form">
        <div class="form-group">
          <label>字段名</label>
          <input type="text" v-model="selectedField.label" @input="onFieldChange" />
        </div>
        <div class="form-group">
          <label>字段值</label>
          <input type="text" v-model="selectedField.value" @input="onFieldChange" />
        </div>
        <div class="form-group">
          <label>类型</label>
          <div class="type-buttons">
            <button
              :class="['type-btn', selectedField.type === 'fixed' ? 'active' : '']"
              @click="selectedField.type = 'fixed'; onFieldChange()"
            >固定</button>
            <button
              :class="['type-btn', selectedField.type === 'dynamic' ? 'active' : '']"
              @click="selectedField.type = 'dynamic'; onFieldChange()"
            >可变</button>
          </div>
        </div>
        <div class="form-group">
          <label>位置</label>
          <div class="position-inputs">
            <input type="number" v-model.number="selectedField.position.left" @input="onFieldChange" placeholder="X" />
            <input type="number" v-model.number="selectedField.position.top" @input="onFieldChange" placeholder="Y" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./label-editor.css"></style>
