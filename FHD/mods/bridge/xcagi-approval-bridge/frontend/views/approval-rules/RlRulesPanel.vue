<script setup>

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
        <div class="rules-header__text">
          <h3>审批规则</h3>
          <p>共 {{ rules.length }} 条规则，命中后需人工审批</p>
        </div>
        <label class="toggle-label">
          <span>启用审批功能</span>
          <span
            class="toggle-switch"
            :class="{ active: enabled }"
            role="switch"
            :aria-checked="enabled"
            @click="toggleEnabled"
          >
            <span class="toggle-slider"></span>
          </span>
        </label>
      </div>

      <div class="rules-layout" v-if="enabled">
        <section class="rules-list-wrap">
          <div class="rules-table-head">
            <span>业务操作</span>
            <span>触发方式</span>
            <span>说明</span>
            <span class="align-right">操作</span>
          </div>
          <div class="rules-list">
            <div class="rule-item" v-for="(rule, index) in rules" :key="index">
              <div class="rule-cell rule-action-cell">
                <span class="rule-action">{{ getActionLabel(rule.tool_id, rule.action) }}</span>
                <span class="rule-path">{{ rule.tool_id }} / {{ rule.action }}</span>
              </div>
              <div class="rule-cell">
                <span class="rule-trigger" :class="rule.trigger">{{ getTriggerLabel(rule.trigger) }}</span>
              </div>
              <div class="rule-cell rule-description">{{ rule.description || '无描述' }}</div>
              <div class="rule-cell rule-actions">
                <button class="btn-edit" @click="editRule(index)" title="编辑">
                  <i class="fa fa-pencil"></i>
                </button>
                <button class="btn-delete" @click="deleteRule(index)" title="删除">
                  <i class="fa fa-trash"></i>
                </button>
              </div>
            </div>
            <div v-if="rules.length === 0" class="rules-empty">暂无规则，请在右侧添加。</div>
          </div>
        </section>

        <aside class="add-rule-section">
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
            <div class="form-group">
              <label>描述</label>
              <input type="text" v-model="newRule.description" placeholder="规则描述" />
            </div>
            <button class="btn-add" @click="addRule" :disabled="!canAddRule">
              <i class="fa fa-plus"></i> 添加规则
            </button>
          </div>
        </aside>
      </div>

      <div class="no-rules" v-else>
        <i class="fa fa-check-circle-o"></i>
        <p>审批功能已禁用，所有操作将直接执行，无需审批。</p>
      </div>
    </div>
</template>

<style scoped src="./approval-rules.css"></style>
