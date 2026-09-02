<template>
  <div class="workflow-page">
    <div class="page-header">
      <h1 class="page-title">自动化任务</h1>
      <p class="page-desc">
        把常做的文件处理、数据同步和协作流程保存成任务。你可以直接运行，也可以进入高级调试查看流程细节。
      </p>
      <div class="page-header-row">
        <nav class="wf-subtabs" aria-label="工作流子页面">
          <button type="button" class="wf-subtab" :class="{ 'wf-subtab--active': activeTab === 'list' }" @click="activeTab = 'list'">我的任务</button>
          <button type="button" class="wf-subtab" :class="{ 'wf-subtab--active': activeTab === 'executions' }" @click="activeTab = 'executions'">运行记录</button>
          <button type="button" class="wf-subtab" :class="{ 'wf-subtab--active': activeTab === 'sandbox' }" @click="activeTab = 'sandbox'">高级调试</button>
          <button type="button" class="wf-subtab" :class="{ 'wf-subtab--active': activeTab === 'triggers' }" @click="activeTab = 'triggers'">自动触发</button>
        </nav>
        <div class="page-header-actions">
          <button
            type="button"
            class="btn btn-sm btn-danger"
            :disabled="purgeAutomationBusy || loading"
            title="删除当前账号下全部自动化任务（含激活与未激活）、节点、边、运行记录、触发器与版本快照；并清空本页沙盒、触发器表单与画布状态。不可恢复"
            @click="purgeAutomationWorkbenchFull"
          >{{ purgeAutomationBusy ? '清空中…' : '一键清理' }}</button>
          <button
            type="button"
            class="btn btn-sm btn-danger"
            title="永久删除当前列表中所有「未激活」任务及其节点、边、运行记录、触发器与版本快照；不可恢复"
            :disabled="bulkDeleteInactiveBusy || loading || purgeAutomationBusy"
            @click="bulkDeleteInactiveWorkflows"
          >
            {{ bulkDeleteInactiveBusy ? '删除中…' : '一键删除未激活' }}
          </button>
          <button class="btn btn-primary" @click="showCreateModal = true">创建自动化任务</button>
        </div>
      </div>
    </div>

    <div v-if="message" :class="['flash', messageOk ? 'flash-ok' : 'flash-err']">{{ message }}</div>

    <!-- 工作流列表 -->
    <div v-if="activeTab === 'list'">
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="workflows.length" class="workflows-grid">
        <div v-for="workflow in workflows" :key="workflow.id" class="workflow-card">
          <div class="workflow-card-header">
            <h3 class="workflow-card-title">{{ workflow.name }}</h3>
            <span class="workflow-card-status" :class="workflow.is_active ? 'active' : 'inactive'">
              {{ workflow.is_active ? '激活' : '未激活' }}
            </span>
          </div>
          <p class="workflow-card-desc">{{ workflow.description }}</p>
          <div class="workflow-card-meta">
            <span>创建于: {{ formatDate(workflow.created_at) }}</span>
            <span>更新于: {{ formatDate(workflow.updated_at) }}</span>
          </div>
          <div class="workflow-card-actions">
            <button class="btn btn-sm" @click="executeWorkflow(workflow.id)">运行</button>
            <button class="btn btn-sm" @click="openV2Editor(workflow.id)" title="可视化编辑器">编辑</button>
            <button class="btn btn-sm" @click="editWorkflow(workflow.id)" title="旧版自绘画布（高级）">高级编辑</button>
            <button class="btn btn-sm" @click="toggleWorkflowStatus(workflow.id, !workflow.is_active)">
              {{ workflow.is_active ? '停用' : '激活' }}
            </button>
            <button class="btn btn-sm btn-danger" @click="deleteWorkflow(workflow.id)">删除</button>
            <button class="btn btn-sm btn-sandbox" @click="openSandboxFor(workflow.id)">调试</button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <p>还没有自动化任务</p>
        <p class="empty-hint">可以从二档用 AI 创建，或点击上方「创建自动化任务」。</p>
      </div>
    </div>

    <!-- 工作流编辑器 -->
    <div v-else-if="activeTab === 'editor'">
      <div class="workflow-editor-header">
        <h2 class="editor-title">{{ currentWorkflow ? currentWorkflow.name : '工作流编辑器' }}</h2>
        <div class="editor-actions">
          <button class="btn btn-sm" @click="activeTab = 'list'">返回列表</button>
          <button class="btn btn-sm btn-primary" @click="saveWorkflow">保存</button>
        </div>
      </div>
      
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else class="workflow-editor">
        <!-- 左侧节点库 -->
        <div class="node-library">
          <h3>节点库</h3>
          <div class="node-category">
            <h4>基础节点</h4>
            <div class="node-item" @click="addNode('start')">
              <div class="node-icon start-node">开始</div>
              <span>开始</span>
            </div>
            <div class="node-item" @click="addNode('end')">
              <div class="node-icon end-node">结束</div>
              <span>结束</span>
            </div>
            <div class="node-item" @click="addNode('condition')">
              <div class="node-icon condition-node">条件</div>
              <span>条件</span>
            </div>
            <div class="node-item" @click="addKnowledgeSearchNode()">
              <div class="node-icon knowledge-node">检索</div>
              <span>知识检索</span>
            </div>
          </div>
          <div class="node-category">
            <h4>AI员工</h4>
            <div v-for="employee in employees" :key="employee.id" class="node-item" @click="addEmployeeNode(employee.id, employee.name ?? '')">
              <div class="node-icon employee-node">员工</div>
              <span>{{ employee.name }}</span>
            </div>
          </div>
        </div>

        <!-- 右侧画布 -->
        <div class="workflow-canvas" ref="canvas">
          <div
            v-for="node in nodes"
            :key="node.id"
            class="workflow-node"
            :class="{ 'workflow-node--focus': Number(node.id) === focusedNodeId }"
            :id="`workflow-node-${node.id}`"
               :style="{ left: node.position_x + 'px', top: node.position_y + 'px' }"
               @mousedown="startDrag($event, node)"
          >
            <div class="node-header" :class="node.node_type + '-node-header'">
              <span class="node-title">{{ node.name }}</span>
              <button class="node-delete" @click.stop="deleteNode(node.id)">×</button>
            </div>
            <div class="node-body">
              <div class="node-type">{{ getNodeTypeLabel(node.node_type) }}</div>
              <button class="node-config" @click.stop="showNodeConfig(node.id)">配置</button>
            </div>
            <div class="node-ports">
              <div class="port port-input" @click.stop="startConnect($event, node.id, 'input')"></div>
              <div class="port port-output" @click.stop="startConnect($event, node.id, 'output')"></div>
            </div>
          </div>
          
          <!-- 连接线 -->
          <svg class="workflow-connections" ref="connections">
            <path v-for="edge in edges" :key="edge.id" 
                  :d="getEdgePath(edge)" 
                  class="connection-line" 
                  @click="selectEdge(edge.id)"/>
          </svg>
        </div>
      </div>
      <details v-if="!loading && currentWorkflow" class="wf-decompose-drawer">
        <summary class="wf-decompose-summary">图结构摘要与 Mermaid（当前画布；未保存请先点「保存」）</summary>
        <div class="wf-decompose-body">
          <p class="wf-decompose-counts">
            <span v-for="(c, typ) in graphSummary.counts" :key="typ" class="wf-count-pill">
              {{ typ }}: {{ c }}
            </span>
          </p>
          <ul v-if="graphSummary.warnings.length" class="wf-decompose-warn">
            <li v-for="(w, wi) in graphSummary.warnings" :key="'ew' + wi">{{ w }}</li>
          </ul>
          <div class="wf-mermaid-actions">
            <button type="button" class="btn btn-sm" @click="copyMermaidToClipboard">复制 Mermaid</button>
          </div>
          <pre class="sandbox-pre wf-mermaid-pre">{{ mermaidSource }}</pre>
        </div>
      </details>
    </div>

    <!-- 沙盒实验室 -->
    <div v-else-if="activeTab === 'sandbox'" class="sandbox-panel">
      <div class="sandbox-head">
        <h2 class="sandbox-title">工作流沙盒测试</h2>
        <p class="sandbox-lead">
          在<strong>已保存到服务端</strong>的图上运行。画布中修改后请先点编辑器右上角「保存」同步，再在此测试。
          相较仅「点运行」：可编辑入参 JSON、查看每步变量快照、条件分支命中与耗时；默认 Mock 员工节点以免调试时打真实接口。
        </p>
      </div>
      <div class="sandbox-controls">
        <label class="label">AI 员工</label>
        <select v-model="sandboxEmployeeId" class="input sandbox-select">
          <option value="">请选择员工</option>
          <option v-for="emp in employees" :key="emp.id" :value="String(emp.id)">{{ emp.name }} (id={{ emp.id }})</option>
        </select>
        <label class="label">关联工作流</label>
        <select
          v-model.number="sandboxWorkflowId"
          :class="['input', 'sandbox-select', { 'sandbox-select--error': !!sandboxMappingError }]"
          :disabled="!sandboxEmployeeId || sandboxMappingLoading"
        >
          <option :value="0" disabled>请选择</option>
          <option v-for="w in sandboxWorkflowCandidates" :key="w.id" :value="w.id">{{ w.name }} (id={{ w.id }})</option>
        </select>
        <p v-if="sandboxMappingLoading" class="muted">正在按员工筛选关联工作流…</p>
        <p v-else-if="sandboxMappingError" class="flash flash-err sandbox-flash">{{ sandboxMappingError }}</p>
        <p v-else-if="sandboxEmployeeId" class="muted">
          关联来源：节点命中 {{ sandboxMappingNodeHits }} 个，manifest 兜底 {{ sandboxMappingManifestHits }} 个。
        </p>
        <p v-if="sandboxEmployeeId && !sandboxMappingLoading && !sandboxWorkflowCandidates.length" class="muted">
          {{ sandboxMappingError
            ? '映射服务异常且本地回退未命中工作流。请检查后端日志，或先在图节点配置 employee_id。'
            : '当前员工未匹配到可测试工作流。请先在图节点配置 employee_id，或在 manifest.workflow_employees 写入 workflow_id。' }}
        </p>
        <button
          v-if="sandboxEmployeeId && !sandboxMappingLoading && !sandboxWorkflowCandidates.length"
          type="button"
          class="btn btn-sm"
          :disabled="sandboxAutoCreateBusy"
          @click="createSandboxWorkflowForEmployee"
        >
          {{ sandboxAutoCreateBusy ? '创建中…' : '一键生成该员工测试工作流' }}
        </button>
      </div>
      <div class="sandbox-preset-block">
        <label class="label">运行变量预设</label>
        <select class="input sandbox-select" :value="sandboxPresetId" @change="onSandboxPresetChange">
          <option v-for="p in WORKFLOW_SANDBOX_PRESETS" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <p class="sandbox-preset-hint muted">
          仅填充下方 JSON；条件边用到的 key 须与图中表达式一致，可按业务修改。
        </p>
      </div>
      <div v-if="sandboxWorkflowId" class="wf-decompose-sandbox">
        <h3 class="wf-decompose-h3">图结构拆解（服务端已保存图）</h3>
        <p v-if="decomposeLoading" class="muted">加载图结构…</p>
        <template v-else>
          <p class="wf-decompose-counts">
            <span v-for="(c, typ) in graphSummary.counts" :key="'s' + typ" class="wf-count-pill">
              {{ typ }}: {{ c }}
            </span>
          </p>
          <ul v-if="graphSummary.warnings.length" class="wf-decompose-warn">
            <li v-for="(w, wi) in graphSummary.warnings" :key="'sw' + wi">{{ w }}</li>
          </ul>
          <div class="wf-mermaid-actions">
            <button type="button" class="btn btn-sm" @click="copyMermaidToClipboard">复制 Mermaid</button>
          </div>
          <pre class="sandbox-pre wf-mermaid-pre">{{ mermaidSource }}</pre>
        </template>
      </div>
      <div class="sandbox-json-block">
        <label class="label">运行变量（JSON，会合并进流程上下文，可在条件表达式中引用键名）</label>
        <textarea v-model="sandboxInputJson" class="input sandbox-json" spellcheck="false" />
      </div>
      <div class="sandbox-actions">
        <button type="button" class="btn" :disabled="sandboxLoading || !sandboxWorkflowId" @click="runSandboxValidate">
          {{ sandboxLoading ? '…' : '仅校验图' }}
        </button>
        <button type="button" class="btn" :disabled="sandboxLoading || !sandboxWorkflowId" @click="runSandboxMock">
          {{ sandboxLoading ? '运行中…' : 'Mock 测试' }}
        </button>
        <button type="button" class="btn btn-primary" :disabled="!canRunReal" @click="runSandboxReal">
          {{ sandboxLoading ? '运行中…' : '真实测试' }}
        </button>
      </div>
      <p v-if="realRunDisabledReason" class="sandbox-real-disabled">{{ realRunDisabledReason }}</p>
      <p class="sandbox-real-hint muted">
        真实测试会调用员工执行器与可能的外部依赖，建议先运行 Mock 测试验证流程与分支。
      </p>
      <div v-if="sandboxError" class="flash flash-err sandbox-flash">{{ sandboxError }}</div>
      <WorkflowSandboxReport
        v-if="sandboxReport"
        :sandbox-report="sandboxReport"
        :last-run-meta="lastRunMeta"
        :real-precheck-summary="realPrecheckSummary"
      />
    </div>

    <!-- 执行记录 -->
    <div v-else-if="activeTab === 'executions'">
      <div class="executions-header">
        <h2 class="executions-title">执行记录</h2>
        <button class="btn btn-sm" @click="activeTab = 'list'">返回列表</button>
      </div>
      
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="executions.length" class="executions-list">
        <div v-for="execution in executions" :key="execution.id" class="execution-item">
          <div class="execution-header">
            <span class="execution-id">执行 ID: {{ execution.id }}</span>
            <span class="execution-status" :class="execution.status">
              {{ getStatusLabel(execution.status) }}
            </span>
          </div>
          <div class="execution-info">
            <span>工作流: {{ getWorkflowName(execution.workflow_id) }}</span>
            <span>开始时间: {{ formatDate(execution.started_at) }}</span>
            <span v-if="execution.completed_at">完成时间: {{ formatDate(execution.completed_at) }}</span>
          </div>
          <div v-if="execution.error_message" class="execution-error">
            <strong>错误信息:</strong> {{ execution.error_message }}
          </div>
          <div v-if="execution.output_data" class="execution-output">
            <strong>输出数据:</strong>
            <pre>{{ JSON.stringify(execution.output_data, null, 2) }}</pre>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <p>暂无执行记录</p>
      </div>
    </div>

    <!-- 触发器：Cron / Webhook -->
    <div v-else-if="activeTab === 'triggers'" class="triggers-panel">
      <div class="executions-header">
        <h2 class="executions-title">工作流触发器</h2>
        <button type="button" class="btn btn-sm" @click="activeTab = 'list'">返回列表</button>
      </div>
      <div v-if="triggersLoading" class="loading">加载中...</div>
      <div v-else-if="!workflows.length" class="empty-state">请先在「列表」中创建工作流，再配置触发器。</div>
      <div v-else class="card triggers-card">
        <p v-if="triggersMsg" :class="['flash', triggersMsgOk ? 'flash-ok' : 'flash-err']">{{ triggersMsg }}</p>
        <div class="form-group">
          <label class="label">工作流</label>
          <select v-model.number="triggersWorkflowId" class="input" @change="onTriggersWorkflowChange">
            <option v-for="w in workflows" :key="w.id" :value="w.id">{{ w.name }} (#{{ w.id }})</option>
          </select>
        </div>
        <h3 class="triggers-h3">当前触发器</h3>
        <ul v-if="triggerRows.length" class="trigger-list">
          <li v-for="t in triggerRows" :key="t.id" class="trigger-row">
            <div>
              <code>{{ t.trigger_type }}</code>
              <span v-if="t.trigger_key" class="muted"> / {{ t.trigger_key }}</span>
              <span v-if="t.is_active === false" class="muted">（未激活）</span>
              <pre v-if="t.config && Object.keys(t.config).length" class="mini-pre">{{ JSON.stringify(t.config) }}</pre>
            </div>
            <button type="button" class="btn btn-sm btn-danger" @click="removeTriggerRow(t.id)">停用</button>
          </li>
        </ul>
        <p v-else class="empty-state">暂无触发器</p>
        <h3 class="triggers-h3">新增 Cron</h3>
        <p class="muted small">五段式 Unix cron，例如 <code>0 9 * * *</code> 每天 9 点（服务端 APScheduler 注册）</p>
        <input v-model="triggersCronExpr" class="input" placeholder="0 9 * * *" />
        <button type="button" class="btn btn-primary triggers-gap" @click="addCronTrigger">添加 Cron</button>
        <h3 class="triggers-h3">新增 Webhook</h3>
        <p class="muted small">配置后使用下方「测试触发」；调用需登录态（Bearer）。</p>
        <button type="button" class="btn btn-primary triggers-gap" @click="addWebhookTrigger">添加 Webhook 触发器</button>
        <h3 class="triggers-h3">测试 Webhook 执行</h3>
        <textarea v-model="triggersWebhookJson" class="input mono" rows="5" />
        <button type="button" class="btn btn-sm triggers-gap" @click="testWebhookTrigger">测试触发</button>
      </div>
    </div>

    <!-- 创建工作流弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal">
        <h2 class="modal-title">创建工作流</h2>
        <div class="form-group">
          <label class="label">工作流名称</label>
          <input v-model="newWorkflow.name" class="input" placeholder="请输入工作流名称" />
        </div>
        <div class="form-group">
          <label class="label">工作流描述</label>
          <textarea v-model="newWorkflow.description" class="input" placeholder="请输入工作流描述"></textarea>
        </div>
        <p v-if="homeIntentHint" class="modal-intent-hint">{{ homeIntentHint }}</p>
        <p v-if="homeLlmHint" class="modal-llm-hint">{{ homeLlmHint }}</p>
        <div class="modal-actions">
          <button class="btn" @click="showCreateModal = false">取消</button>
          <button class="btn btn-primary" @click="createWorkflow">创建</button>
        </div>
      </div>
    </div>

    <!-- 节点配置弹窗 -->
    <div v-if="showNodeConfigModal" class="modal-overlay" @click.self="showNodeConfigModal = false">
      <div class="modal">
        <h2 class="modal-title">节点配置</h2>
        <div class="form-group">
          <label class="label">节点名称</label>
          <input v-model="selectedNodeForTemplate.name" class="input" />
        </div>
        <div v-if="selectedNodeForTemplate.node_type === 'employee'" class="form-group">
          <label class="label">员工 ID</label>
          <input v-model="selectedNodeForTemplate.config.employee_id" class="input" />
        </div>
        <div v-if="selectedNodeForTemplate.node_type === 'employee'" class="form-group">
          <label class="label">任务类型</label>
          <select v-model="selectedNodeForTemplate.config.task" class="input">
            <option value="analyze_document">分析文档</option>
            <option value="process_data">处理数据</option>
            <option value="generate_report">生成报告</option>
          </select>
        </div>
        <template v-if="selectedNodeForTemplate.node_type === 'knowledge_search'">
          <div class="form-group">
            <label class="label">检索文本（支持 ${'$'}{nodes.foo.bar} 模板）</label>
            <input
              v-model="selectedNodeForTemplate.config.query"
              class="input"
              placeholder="例如：${'$'}{nodes.start.user_query} 或固定文本"
            />
          </div>
          <div class="form-group">
            <label class="label">集合 ID 列表（逗号分隔；留空表示按身份自动可见）</label>
            <input
              :value="formatCollectionIds(selectedNodeForTemplate.config.collection_ids)"
              class="input"
              placeholder="例如：12,18"
              @input="onCollectionIdsInput"
            />
          </div>
          <div class="form-group">
            <label class="label">top_k</label>
            <input v-model.number="selectedNodeForTemplate.config.top_k" type="number" min="1" max="20" class="input" />
          </div>
          <div class="form-group">
            <label class="label">最低分数（0–1，越高越严）</label>
            <input v-model.number="selectedNodeForTemplate.config.min_score" type="number" min="0" max="1" step="0.05" class="input" />
          </div>
          <div class="form-group">
            <label class="label">输出变量名</label>
            <input v-model="selectedNodeForTemplate.config.output_var" class="input" placeholder="knowledge" />
          </div>
        </template>
        <div class="modal-actions">
          <button class="btn" @click="showNodeConfigModal = false">取消</button>
          <button class="btn btn-primary" @click="saveNodeConfig">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { WORKFLOW_SANDBOX_PRESETS } from '../workflowSandboxPresets'
import { useWorkflowPage } from '../composables/useWorkflowPage'
import WorkflowSandboxReport from './workflow/WorkflowSandboxReport.vue'
// 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定；
// <script setup> 的 setupState 仅包含顶层声明（不含未在模板使用的 import），
// 故以 namespace 导入后解构为顶层 const。
import * as workflowSandboxHelpers from './workflow/workflowSandboxHelpers'
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定 */
const {
  parsePositiveInt, employeeIdMatches, employeeMatchesManifestEntry, workflowEmployeesFromModRow,
} = workflowSandboxHelpers
/* eslint-enable @typescript-eslint/no-unused-vars */

// 全部状态与方法来自 useWorkflowPage（原 script 已按域迁移至 src/composables/useWorkflow*.ts）
const page = useWorkflowPage()
const {
  // 基础状态 / 列表 / 执行记录
  activeTab, loading, bulkDeleteInactiveBusy, purgeAutomationBusy,
  message, messageOk, workflows, executions, showCreateModal, newWorkflow,
  formatDate, getStatusLabel, getWorkflowName,
  executeWorkflow, openV2Editor, editWorkflow, toggleWorkflowStatus,
  deleteWorkflow, bulkDeleteInactiveWorkflows, purgeAutomationWorkbenchFull, createWorkflow,
  // 编辑器画布
  currentWorkflow, nodes, edges, focusedNodeId, canvas, connections, employees,
  addNode, addEmployeeNode, addKnowledgeSearchNode, deleteNode,
  showNodeConfig, saveNodeConfig, startDrag, startConnect,
  getNodeTypeLabel, getEdgePath, selectEdge, saveWorkflow,
  showNodeConfigModal, selectedNodeForTemplate, formatCollectionIds, onCollectionIdsInput,
  // 图摘要
  graphSummary, mermaidSource, copyMermaidToClipboard,
  // 沙盒
  sandboxEmployeeId, sandboxWorkflowId, sandboxWorkflowCandidates,
  sandboxMappingError, sandboxMappingLoading, sandboxMappingNodeHits, sandboxMappingManifestHits,
  sandboxAutoCreateBusy, createSandboxWorkflowForEmployee,
  sandboxPresetId, onSandboxPresetChange, sandboxInputJson,
  sandboxLoading, sandboxError, sandboxReport, lastRunMeta,
  realRunDisabledReason, canRunReal, realPrecheckSummary, decomposeLoading,
  runSandboxValidate, runSandboxMock, runSandboxReal, openSandboxFor,
  // 触发器
  triggersWorkflowId, triggerRows, triggersLoading, triggersMsg, triggersMsgOk,
  triggersCronExpr, triggersWebhookJson,
  onTriggersWorkflowChange, addCronTrigger, addWebhookTrigger, removeTriggerRow, testWebhookTrigger,
  homeIntentHint, homeLlmHint,
} = page

// 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定 */
const {
  applyWorkflowRouteQuery, resetAutomationWorkbenchLocalState, pickEmployeeNameById,
  selectedNode, onMouseMove, onMouseUp, onCanvasClick,
  rebuildSandboxWorkflowCandidates, parseSandboxInput, applySandboxPreset,
  loadTriggersPanel, refreshTriggersList,
} = page
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./WorkflowView.css"></style>
