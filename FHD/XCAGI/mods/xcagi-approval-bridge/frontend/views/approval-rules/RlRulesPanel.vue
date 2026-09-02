<script setup>
import { defineProps } from 'vue'

// 拆分自 ApprovalRulesView.vue 模板（原第 8–86 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  enabled, toggleEnabled, rules,
  editRule, deleteRule, newRule, canAddRule, addRule,
  getActionLabel, getTriggerLabel,
} = props.tm
</script>

<template>
    <div class="rules-container">
      <div class="rules-header">
        <div class="enable-toggle">
          <label class="toggle-label">
            <span>启用审批功能</span>
            <div class="toggle-switch" :class="{ active: enabled }" @click="toggleEnabled">
              <div class="toggle-slider"></div>
            </div>
          </label>
        </div>
      </div>

      <div class="rules-list" v-if="enabled">
        <div class="rule-item" v-for="(rule, index) in rules" :key="index">
          <div class="rule-info">
            <div class="rule-main">
              <span class="rule-action">{{ getActionLabel(rule.tool_id, rule.action) }}</span>
              <span class="rule-trigger" :class="rule.trigger">{{ getTriggerLabel(rule.trigger) }}</span>
            </div>
            <div class="rule-description">{{ rule.description || '无描述' }}</div>
            <div class="rule-path">{{ rule.tool_id }} / {{ rule.action }}</div>
          </div>
          <div class="rule-actions">
            <button class="btn-edit" @click="editRule(index)" title="编辑">
              <i class="fa fa-pencil"></i>
            </button>
            <button class="btn-delete" @click="deleteRule(index)" title="删除">
              <i class="fa fa-trash"></i>
            </button>
          </div>
        </div>

        <div class="add-rule-section">
          <h3>添加新规则</h3>
          <div class="add-form">
            <div class="form-group">
              <label>工具 ID</label>
              <select v-model="newRule.tool_id">
                <option value="">选择工具</option>
                <option value="shipment_generate">发货单生成</option>
                <option value="print">打印</option>
                <option value="products">产品管理</option>
                <option value="customers">客户管理</option>
              </select>
            </div>
            <div class="form-group">
              <label>操作</label>
              <select v-model="newRule.action">
                <option value="">选择操作</option>
                <option value="execute">执行</option>
                <option value="create">创建</option>
                <option value="update">更新</option>
                <option value="delete">删除</option>
              </select>
            </div>
            <div class="form-group">
              <label>触发方式</label>
              <select v-model="newRule.trigger">
                <option value="always">始终审批</option>
                <option value="conditional">条件审批</option>
                <option value="never">从不审批</option>
              </select>
            </div>
            <div class="form-group full-width">
              <label>描述</label>
              <input type="text" v-model="newRule.description" placeholder="规则描述" />
            </div>
            <button class="btn-add" @click="addRule" :disabled="!canAddRule">
              <i class="fa fa-plus"></i> 添加规则
            </button>
          </div>
        </div>
      </div>

      <div class="no-rules" v-else>
        <i class="fa fa-check-circle-o"></i>
        <p>审批功能已禁用，所有操作将直接执行，无需审批。</p>
      </div>
    </div>
</template>

<style scoped src="./approval-rules.css"></style>
