<script setup lang="ts">
import type { ApprovalFlowManagementCtx } from './assemble'

// 拆分自 ApprovalFlowManagementView.vue 模板（原第 65–200 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ApprovalFlowManagementCtx }>()

const {
  showCreateModal, closeModal, editingFlow, formData,
  addNode, removeNode, saveFlow, canSave,
} = props.tm
</script>

<template>
    <!-- 创建/编辑流程弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click="closeModal">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>{{ editingFlow ? '编辑流程' : '新建流程' }}</h3>
          <button class="btn-close" @click="closeModal">
            <i class="fa fa-times"></i>
          </button>
        </div>
        <div class="modal-body">
          <!-- 基本信息 -->
          <div class="form-section">
            <h4>基本信息</h4>
            <div class="form-grid">
              <div class="form-group">
                <label>流程名称 *</label>
                <input
                  v-model="formData.flow_name"
                  type="text"
                  placeholder="如：出货单审批流程"
                />
              </div>
              <div class="form-group">
                <label>流程 KEY *</label>
                <input
                  v-model="formData.flow_key"
                  type="text"
                  placeholder="如：shipment_approval"
                />
              </div>
              <div class="form-group">
                <label>业务类型 *</label>
                <select v-model="formData.business_type">
                  <option value="">选择业务类型</option>
                  <option value="shipment">出货单</option>
                  <option value="purchase">采购</option>
                  <option value="expense">费用报销</option>
                  <option value="contract">合同</option>
                  <option value="general">通用</option>
                </select>
              </div>
              <div class="form-group">
                <label>启用状态</label>
                <div class="checkbox-group">
                  <label class="checkbox-label">
                    <input type="checkbox" v-model="formData.is_active" />
                    <span>立即启用此流程</span>
                  </label>
                </div>
              </div>
              <div class="form-group full-width">
                <label>流程描述</label>
                <textarea
                  v-model="formData.description"
                  rows="3"
                  placeholder="描述此流程的用途和规则"
                ></textarea>
              </div>
            </div>
          </div>

          <!-- 审批节点 -->
          <div class="form-section">
            <div class="section-header">
              <h4>审批节点</h4>
              <button class="btn btn-sm" @click="addNode">
                <i class="fa fa-plus"></i> 添加节点
              </button>
            </div>
            <div class="nodes-list">
              <div
                v-for="(node, index) in formData.nodes"
                :key="index"
                class="node-item"
              >
                <div class="node-header">
                  <span class="node-order">第 {{ index + 1 }} 级审批</span>
                  <button class="btn-icon btn-sm" @click="removeNode(index)" title="删除">
                    <i class="fa fa-trash"></i>
                  </button>
                </div>
                <div class="node-form">
                  <div class="form-row">
                    <div class="form-group">
                      <label>节点名称</label>
                      <input
                        v-model="node.node_name"
                        type="text"
                        placeholder="如：部门经理审批"
                      />
                    </div>
                    <div class="form-group">
                      <label>节点类型</label>
                      <select v-model="node.node_type">
                        <option value="serial">串行审批</option>
                        <option value="parallel">并行审批</option>
                      </select>
                    </div>
                  </div>
                  <div class="form-row">
                    <div class="form-group">
                      <label>审批人类型</label>
                      <select v-model="node.approver_type">
                        <option value="user">指定用户</option>
                        <option value="role">指定角色</option>
                        <option value="position">指定职位</option>
                        <option value="dynamic">动态审批人</option>
                      </select>
                    </div>
                    <div class="form-group">
                      <label>审批人 ID 列表</label>
                      <input
                        v-model="node.approver_ids_text"
                        type="text"
                        placeholder="多个 ID 用逗号分隔，如：1,2,3"
                      />
                      <small class="help-text">用户 ID/角色 ID/职位 ID，多个用逗号分隔</small>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="formData.nodes.length === 0" class="empty-node">
                <i class="fa fa-sitemap"></i>
                <p>暂无审批节点，点击"添加节点"按钮添加</p>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="closeModal">取消</button>
          <button class="btn btn-primary" @click="saveFlow" :disabled="!canSave">
            <i class="fa fa-save"></i> {{ editingFlow ? '保存修改' : '创建流程' }}
          </button>
        </div>
      </div>
    </div>
</template>

<style scoped src="./approval-flow-management.css"></style>
