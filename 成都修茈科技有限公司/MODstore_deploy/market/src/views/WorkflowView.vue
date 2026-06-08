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
            :data-node-id="String(node.id)"
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
      <div v-if="sandboxReport" class="sandbox-report">
        <div class="sandbox-report-row">
          <span :class="['sandbox-pill', sandboxReport.ok ? 'ok' : 'err']">{{ sandboxReport.ok ? '通过' : '未通过' }}</span>
          <span v-if="sandboxReport.validate_only" class="muted">仅校验模式</span>
          <span v-if="lastRunMeta.mode === 'real'" class="sandbox-pill sm">Real</span>
          <span v-else-if="lastRunMeta.mode === 'mock'" class="sandbox-pill sm">Mock</span>
        </div>
        <div v-if="lastRunMeta.mode === 'real'" class="sandbox-block">
          <h4>真实测试前置检查</h4>
          <p class="muted">{{ realPrecheckSummary }}</p>
          <ul v-if="lastRunMeta.precheck?.issues?.length">
            <li v-for="(it, i) in lastRunMeta.precheck.issues" :key="'pc' + i">{{ it }}</li>
          </ul>
        </div>
        <div v-if="sandboxReport.errors?.length" class="sandbox-block">
          <h4>错误</h4>
          <ul><li v-for="(err, i) in sandboxReport.errors" :key="'e'+i">{{ err }}</li></ul>
        </div>
        <div v-if="sandboxReport.warnings?.length" class="sandbox-block">
          <h4>提示</h4>
          <ul><li v-for="(w, i) in sandboxReport.warnings" :key="'w'+i">{{ w }}</li></ul>
        </div>
        <div v-if="sandboxReport.steps?.length" class="sandbox-block">
          <h4>执行轨迹（{{ sandboxReport.steps.length }} 步）</h4>
          <div v-for="st in sandboxReport.steps" :key="st.order" class="sandbox-step">
            <div class="sandbox-step-h">
              <span class="mono">#{{ st.order }}</span>
              <span>{{ st.node_name }}</span>
              <span class="muted mono">{{ st.node_type }}</span>
              <span v-if="st.duration_ms != null" class="muted">{{ st.duration_ms }} ms</span>
              <span v-if="st.mock_employee" class="sandbox-pill sm">Mock</span>
            </div>
            <details class="sandbox-details">
              <summary>变量快照 / 输出</summary>
              <pre class="sandbox-pre">{{ JSON.stringify({ input: st.input_snapshot, output_delta: st.output_delta, edge: st.edge_taken, branches: st.condition_branches }, null, 2) }}</pre>
            </details>
          </div>
        </div>
        <div v-if="sandboxReport.output && Object.keys(sandboxReport.output).length" class="sandbox-block">
          <h4>最终上下文（可序列化摘要）</h4>
          <pre class="sandbox-pre">{{ JSON.stringify(sandboxReport.output, null, 2) }}</pre>
        </div>
      </div>
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
              :value="(selectedNodeForTemplate.config.collection_ids || []).join(',')"
              class="input"
              placeholder="例如：12,18"
              @input="(e: any) => selectedNodeForTemplate.config.collection_ids = String(e?.target?.value || '').split(',').map((x: string) => Number(x.trim())).filter((n: number) => !isNaN(n) && n > 0)"
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { filterOutPlannedDutyEmployees } from '../utils/workbenchEmployeeFilter'
import { computeGraphSummary, buildMermaidFlowchart } from '../workflowMermaid'
import { WORKFLOW_SANDBOX_PRESETS } from '../workflowSandboxPresets'
import { errMessage } from '../utils/errMessage'

const route = useRoute()
const router = useRouter()

interface WorkflowRow {
  id: number
  name?: string
  description?: string
  is_active?: boolean
  created_at?: string
  updated_at?: string
}

interface EmployeeRow {
  id: number | string
  name?: string
  [key: string]: unknown
}

interface WorkflowNodeRow {
  id: number
  workflow_id?: number
  name?: string
  node_type?: string
  config?: Record<string, any>
  position_x: number
  position_y: number
}

interface WorkflowEdgeRow {
  id: number
  source_node_id?: number
  target_node_id?: number
  condition?: string | null
}

interface ExecutionRow {
  id: number
  workflow_id?: number
  status?: string
  started_at?: string
  completed_at?: string
  error_message?: string
  output_data?: unknown
}

interface TriggerRow {
  id: number
  workflow_id?: number
  trigger_type?: string
  trigger_key?: string
  is_active?: boolean
  config?: Record<string, any>
}

interface WorkflowSandboxReport {
  ok?: boolean
  validate_only?: boolean
  issues?: unknown[]
  errors?: unknown[]
  warnings?: unknown[]
  steps?: Array<Record<string, any>>
  output?: Record<string, unknown>
}

interface RealPrecheck {
  ok?: boolean
  checkedCount?: number
  missingConfigCount?: number
  statusErrorCount?: number
  issues?: unknown[]
  nodeIds?: number[]
}

// 状态管理
const activeTab = ref('list')
const loading = ref(false)
const bulkDeleteInactiveBusy = ref(false)
/** 一键清理：删除全部任务进行中 */
const purgeAutomationBusy = ref(false)
const message = ref('')
const messageOk = ref(true)
const workflows = ref<WorkflowRow[]>([])
const employees = ref<EmployeeRow[]>([])
const executions = ref<ExecutionRow[]>([])

const triggersWorkflowId = ref(0)
const triggerRows = ref<TriggerRow[]>([])
const triggersLoading = ref(false)
const triggersMsg = ref('')
const triggersMsgOk = ref(true)
const triggersCronExpr = ref('0 9 * * *')
const triggersWebhookJson = ref('{\n  "source": "webhook"\n}')

// 沙盒
const sandboxEmployeeId = ref('')
const sandboxWorkflowCandidates = ref<Array<{ id: number; name?: string; source?: string }>>([])
const sandboxMappingLoading = ref(false)
const sandboxMappingError = ref('')
const sandboxMappingNodeHits = ref(0)
const sandboxMappingManifestHits = ref(0)
const sandboxWorkflowId = ref(0)
const sandboxInputJson = ref('{\n  "topic": "示例主题"\n}')
const sandboxLoading = ref(false)
const sandboxAutoCreateBusy = ref(false)
const sandboxReport = ref<WorkflowSandboxReport | null>(null)
const sandboxError = ref('')
const lastRunMeta = ref<{ mode: string; startedAt: string; precheck: RealPrecheck | null }>({ mode: '', startedAt: '', precheck: null })
/** 沙盒页展示用的服务端图快照（与画布未保存修改可能不一致） */
const decomposeNodes = ref<WorkflowNodeRow[]>([])
const decomposeEdges = ref<WorkflowEdgeRow[]>([])
const decomposeLoading = ref(false)
const sandboxPresetId = ref('topic')

// 编辑器状态
const currentWorkflow = ref<WorkflowRow | null>(null)
const nodes = ref<WorkflowNodeRow[]>([])
const edges = ref<WorkflowEdgeRow[]>([])
const focusedNodeId = ref(0)

// 拖拽状态
const dragging = ref(false)
const dragNode = ref<WorkflowNodeRow | null>(null)
const dragOffset = ref({ x: 0, y: 0 })

// 连接状态
const connecting = ref(false)
const connectStart = ref<number | null>(null)
const connectStartPort = ref('')

// 弹窗状态
const showCreateModal = ref(false)
const showNodeConfigModal = ref(false)
const selectedNode = ref<WorkflowNodeRow | null>(null)
const selectedNodeForTemplate = computed(() => {
  const n = selectedNode.value
  if (n) {
    if (!n.config) n.config = {}
    return n as WorkflowNodeRow & { config: Record<string, any> }
  }
  return { id: 0, name: '', node_type: '', config: {}, position_x: 0, position_y: 0 } as WorkflowNodeRow & {
    config: Record<string, any>
  }
})

// 新工作流表单
const newWorkflow = ref({
  name: '',
  description: '',
})

/** 从工作台首页带入的默认模型说明 */
const homeLlmHint = ref('')
/** 从工作台首页带入的制作类型（mod / employee / workflow） */
const homeIntentHint = ref('')

const INTENT_FROM_HOME: Record<string, string> = {
  mod: '从首页带入：做 Mod（仓库 + 行业 JSON + 员工命名）',
  employee: '从首页带入：做员工',
  workflow: '从首页带入：生成 Skill 组',
}

// 画布引用
const canvas = ref<HTMLElement | null>(null)
const connections = ref<HTMLElement | null>(null)
const workflowDetailCache = new Map<number, any>()

const realRunDisabledReason = computed(() => {
  if (sandboxLoading.value) return '当前正在运行，请等待完成后再发起真实测试。'
  if (sandboxMappingLoading.value) return '正在构建员工到工作流映射，请稍候。'
  if (!sandboxEmployeeId.value) return '请先选择 AI 员工。'
  if (!sandboxWorkflowId.value) return '请先选择关联工作流。'
  return ''
})

const canRunReal = computed(() => !realRunDisabledReason.value)

const realPrecheckSummary = computed(() => {
  const p = lastRunMeta.value?.precheck
  if (!p || lastRunMeta.value?.mode !== 'real') return ''
  if (!p.checkedCount) return '未检测到员工节点；真实测试将按图继续执行。'
  const okPart = p.ok ? '通过' : '未通过'
  return `检查${okPart}：员工节点 ${p.checkedCount} 个，缺失配置 ${p.missingConfigCount}，状态异常 ${p.statusErrorCount}。`
})

// 消息提示
function flash(msg: string, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 5000)
}

/** 仅重置本页 UI / 沙盒 / 触发器 / 画布内存态，不请求删除工作流 */
function resetAutomationWorkbenchLocalState() {
  message.value = ''
  triggersMsg.value = ''
  triggersCronExpr.value = '0 9 * * *'
  triggersWebhookJson.value = '{\n  "source": "webhook"\n}'

  sandboxEmployeeId.value = ''
  sandboxWorkflowCandidates.value = []
  sandboxMappingLoading.value = false
  sandboxMappingError.value = ''
  sandboxMappingNodeHits.value = 0
  sandboxMappingManifestHits.value = 0
  sandboxWorkflowId.value = 0
  sandboxLoading.value = false
  sandboxAutoCreateBusy.value = false
  sandboxReport.value = null
  sandboxError.value = ''
  lastRunMeta.value = { mode: '', startedAt: '', precheck: null }
  decomposeNodes.value = []
  decomposeEdges.value = []
  decomposeLoading.value = false

  sandboxPresetId.value = 'topic'
  applySandboxPreset('topic')

  workflowDetailCache.clear()
  homeLlmHint.value = ''
  homeIntentHint.value = ''
  newWorkflow.value = { name: '', description: '' }
  showCreateModal.value = false
  showNodeConfigModal.value = false

  activeTab.value = 'list'
  currentWorkflow.value = null
  nodes.value = []
  edges.value = []
  focusedNodeId.value = 0
  dragging.value = false
  connecting.value = false
  connectStart.value = null
  connectStartPort.value = ''
  selectedNode.value = null

  triggersWorkflowId.value = 0
  triggerRows.value = []
  executions.value = []
}

/** 一键清理：删光账号下全部自动化任务 + 重置本页本地状态（与「workflow-page 全删」语义一致） */
async function purgeAutomationWorkbenchFull() {
  if (purgeAutomationBusy.value) return

  const list = Array.isArray(workflows.value) ? workflows.value : []
  const ids = list.map((w) => (w && w.id != null ? Number(w.id) : 0)).filter((n) => Number.isFinite(n) && n > 0)

  if (!ids.length) {
    if (
      !window.confirm(
        '当前没有任何已保存的自动化任务。将仅清空：本页提示、沙盒与触发器表单、运行记录列表缓存、以及未提交的创建弹窗等本地状态。是否继续？',
      )
    ) {
      return
    }
    resetAutomationWorkbenchLocalState()
    flash('已清理本页本地状态', true)
    await loadWorkflows()
    if (activeTab.value === 'executions') await loadExecutions()
    return
  }

  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录后再使用一键清理（将删除全部自动化任务）', false)
    return
  }

  const activeCount = list.filter((w) => w && w.is_active).length
  const activeHint =
    activeCount > 0 ? `\n\n其中有 ${activeCount} 个为「激活」状态，将一并永久删除。` : ''

  if (
    !window.confirm(
      `确定删除当前账号下全部 ${ids.length} 个自动化任务？\n含节点、边、运行记录、触发器与版本快照等，不可恢复。${activeHint}\n\n同时将清空本页沙盒、触发器表单与画布状态。是否继续？`,
    )
  ) {
    return
  }

  purgeAutomationBusy.value = true
  resetAutomationWorkbenchLocalState()
  const failed: Array<{ id: number; err: string }> = []
  try {
    for (const id of ids) {
      try {
        await api.deleteWorkflow(id)
      } catch (e) {
        failed.push({ id, err: (e as Error)?.message || String(e) })
      }
    }
    if (failed.length) {
      flash(
        `已删除 ${ids.length - failed.length} 个，失败 ${failed.length} 个：${failed.map((f) => f.id).join(', ')}`,
        false,
      )
    } else {
      flash(`已清空自动化任务（共删除 ${ids.length} 个）`, true)
    }
  } finally {
    purgeAutomationBusy.value = false
    workflowDetailCache.clear()
    await loadWorkflows()
    if (activeTab.value === 'executions') await loadExecutions()
    if (activeTab.value === 'triggers') await loadTriggersPanel()
  }
}

// 日期格式化
function formatDate(iso: string | undefined) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

// 获取节点类型标签
function getNodeTypeLabel(type: string | undefined) {
  const labels: Record<string, string> = {
    start: '开始节点',
    end: '结束节点',
    employee: '员工节点',
    condition: '条件节点',
    knowledge_search: '知识检索节点'
  }
  return (type && labels[type]) || type || '未知节点'
}

// 获取状态标签
function getStatusLabel(status: string | undefined) {
  const labels: Record<string, string> = {
    pending: '待执行',
    running: '执行中',
    completed: '已完成',
    failed: '失败'
  }
  return (status && labels[status]) || status || '未知'
}

// 获取工作流名称
function getWorkflowName(workflowId: number | undefined) {
  if (workflowId == null || !Number.isFinite(Number(workflowId))) return '未知工作流'
  const workflow = workflows.value.find((w) => w.id === workflowId)
  return workflow ? workflow.name : '未知工作流'
}

// 加载工作流列表
async function loadWorkflows() {
  loading.value = true
  try {
    const res = await api.listWorkflows()
    workflows.value = Array.isArray(res) ? (res as WorkflowRow[]) : []
  } catch (e) {
    flash('加载工作流失败: ' + ((e as Error)?.message || String(e)), false)
    workflows.value = []
  } finally {
    loading.value = false
  }
}

function parsePositiveInt(v: unknown): number {
  const n = parseInt(String(v ?? ''), 10)
  return Number.isFinite(n) && n > 0 ? n : 0
}

function pickEmployeeNameById(empId: unknown): string {
  const e = (employees.value || []).find((x) => String(x?.id) === String(empId))
  const name = e?.name
  return typeof name === 'string' ? name.trim() : ''
}

function workflowEmployeesFromModRow(modRow: any): any[] {
  const arr = modRow?.workflow_employees
  return Array.isArray(arr) ? arr : []
}

function employeeMatchesManifestEntry(entry: any, employeeId: unknown, employeeName: string): boolean {
  if (!entry || typeof entry !== 'object') return false
  const eid = String(entry.id || '').trim()
  if (eid && employeeIdMatches(eid, employeeId)) return true
  if (!employeeName) return false
  const label = String(entry.label || '').trim()
  const title = String(entry.panel_title || '').trim()
  return (
    label === employeeName ||
    title === employeeName ||
    employeeIdMatches(label, employeeId) ||
    employeeIdMatches(title, employeeId)
  )
}

async function getWorkflowDetailCached(workflowId: number): Promise<any> {
  if (workflowDetailCache.has(workflowId)) return workflowDetailCache.get(workflowId)
  const detail = await api.getWorkflow(workflowId)
  workflowDetailCache.set(workflowId, detail)
  return detail
}

function employeeIdMatches(a: unknown, b: unknown): boolean {
  const x = String(a || '').trim()
  const y = String(b || '').trim()
  if (!x || !y) return false
  if (x === y) return true
  return x.endsWith(`-${y}`) || x.endsWith(`_${y}`) || y.endsWith(`-${x}`) || y.endsWith(`_${x}`)
}

async function rebuildSandboxWorkflowCandidatesFallback(employeeId: string) {
  const byId = new Map<number, { id: number; name: string; source: string }>()
  const nodeHitIds = new Set<number>()
  const manifestHitIds = new Set<number>()
  const employeeName = pickEmployeeNameById(employeeId)
  for (const w of workflows.value || []) {
    let detail = null
    try {
      detail = await getWorkflowDetailCached(w.id)
    } catch {
      continue
    }
    const wsNodes = Array.isArray(detail?.nodes) ? detail.nodes : []
    const hit = wsNodes.some((n: any) => {
      if (!n || typeof n !== 'object') return false
      if (n.node_type !== 'employee') return false
      const cfg = n.config && typeof n.config === 'object' ? n.config : {}
      return employeeIdMatches(String(cfg.employee_id || '').trim(), employeeId)
    })
    if (hit) {
      nodeHitIds.add(w.id)
      byId.set(w.id, { id: w.id, name: w.name || `工作流 ${w.id}`, source: 'node' })
    }
  }

  // 前端本地兜底：/api/mods 返回 workflow_employees 摘要，不保证携带 workflow_id。
  try {
    const modsRes = await api.listMods()
    const mods = Array.isArray(modsRes?.data) ? modsRes.data : []
    for (const mod of mods) {
      for (const entry of workflowEmployeesFromModRow(mod)) {
        if (!employeeMatchesManifestEntry(entry, employeeId, employeeName)) continue
        const wid = parsePositiveInt(entry.workflow_id ?? entry.workflowId)
        if (!wid || nodeHitIds.has(wid) || manifestHitIds.has(wid)) continue
        const wf = (workflows.value || []).find((x) => x.id === wid)
        if (wf) {
          manifestHitIds.add(wid)
          byId.set(wid, { id: wf.id, name: wf.name || `工作流 ${wf.id}`, source: 'manifest' })
        }
      }
    }
  } catch {
    /* ignore */
  }

  const rows = [...byId.values()].sort((a, b) => a.id - b.id)
  return {
    rows,
    nodeHits: nodeHitIds.size,
    manifestHits: manifestHitIds.size,
  }
}

async function rebuildSandboxWorkflowCandidates() {
  sandboxWorkflowCandidates.value = []
  sandboxMappingError.value = ''
  sandboxMappingNodeHits.value = 0
  sandboxMappingManifestHits.value = 0
  sandboxWorkflowId.value = 0
  if (!sandboxEmployeeId.value) return
  const employeeId = String(sandboxEmployeeId.value).trim()
  sandboxMappingLoading.value = true
  try {
    let rows: Array<{ id: number; name: string; source: string }> = []
    let nodeHits = 0
    let manifestHits = 0
    try {
      const res = await api.listWorkflowsByEmployee(employeeId)
      const allRows = Array.isArray(res?.workflows) ? res.workflows : []
      rows = allRows
        .map((x: any) => ({
          id: parsePositiveInt(x?.id),
          name: String(x?.name || '').trim() || `工作流 ${x?.id}`,
          source: String(x?.source || ''),
        }))
        .filter((x: { id: number }) => x.id > 0)
      nodeHits = parsePositiveInt(res?.node_hits)
      manifestHits = parsePositiveInt(res?.manifest_hits)
    } catch (e) {
      const fallback = await rebuildSandboxWorkflowCandidatesFallback(employeeId)
      rows = fallback.rows
      nodeHits = fallback.nodeHits
      manifestHits = fallback.manifestHits
      sandboxMappingError.value = `映射服务不可用，已启用本地回退：${errMessage(e)}`
    }

    sandboxWorkflowCandidates.value = rows
    sandboxMappingNodeHits.value = nodeHits
    sandboxMappingManifestHits.value = manifestHits
    if (rows.length) {
      sandboxWorkflowId.value = rows[0].id
      await loadDecomposeGraph(rows[0].id)
    }
  } catch (e) {
    sandboxMappingError.value = errMessage(e)
  } finally {
    sandboxMappingLoading.value = false
  }
}

async function createSandboxWorkflowForEmployee() {
  const employeeId = String(sandboxEmployeeId.value || '').trim()
  if (!employeeId) {
    flash('请先选择 AI 员工', false)
    return
  }
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录工作台（右上角登录）后再自动生成工作流', false)
    return
  }
  const employeeName = pickEmployeeNameById(employeeId) || employeeId
  sandboxAutoCreateBusy.value = true
  try {
    const isWechatPhone = employeeId === 'wechat_phone'
      || employeeId.endsWith('-wechat_phone')
      || employeeId.endsWith('_wechat_phone')

    if (isWechatPhone) {
      const created = await api.createWorkflow(
        `${employeeName} · 沙盒测试流程`,
        '自动生成：微信电话对接业务员完整业务流程（来电监控→接听→ASR→意图→TTS回灌）。',
      )
      const wid = parsePositiveInt(created?.id)
      if (!wid) throw new Error('创建工作流失败：未返回有效 workflow id')

      const nStart = await api.addWorkflowNode(wid, 'start', '开始', {}, 120, 200)
      const nMonitor = await api.addWorkflowNode(
        wid, 'employee', '监控微信来电',
        { employee_id: employeeId, task: 'monitor_incoming_call' }, 340, 200,
      )
      const nCallCond = await api.addWorkflowNode(
        wid, 'condition', '来电状态判断', {}, 560, 200,
      )
      const nAnswer = await api.addWorkflowNode(
        wid, 'employee', '自动接听',
        { employee_id: employeeId, task: 'auto_answer' }, 780, 120,
      )
      const nAsr = await api.addWorkflowNode(
        wid, 'employee', '语音采集与ASR',
        { employee_id: employeeId, task: 'asr_transcribe' }, 1000, 120,
      )
      const nIntentCond = await api.addWorkflowNode(
        wid, 'condition', '意图识别判断', {}, 1220, 120,
      )
      const nTts = await api.addWorkflowNode(
        wid, 'employee', 'TTS语音合成与回灌',
        { employee_id: employeeId, task: 'tts_playback' }, 1440, 60,
      )
      const nEnd = await api.addWorkflowNode(wid, 'end', '结束', {}, 1660, 120)

      const sid = parsePositiveInt(nStart?.id)
      const mid = parsePositiveInt(nMonitor?.id)
      const ccid = parsePositiveInt(nCallCond?.id)
      const aid = parsePositiveInt(nAnswer?.id)
      const asrid = parsePositiveInt(nAsr?.id)
      const icid = parsePositiveInt(nIntentCond?.id)
      const tid2 = parsePositiveInt(nTts?.id)
      const eid = parsePositiveInt(nEnd?.id)
      if (!sid || !mid || !ccid || !aid || !asrid || !icid || !tid2 || !eid) {
        throw new Error('初始化节点失败，请重试')
      }

      await api.addWorkflowEdge(wid, sid, mid, '')
      await api.addWorkflowEdge(wid, mid, ccid, '')
      await api.addWorkflowEdge(wid, ccid, aid, "call_state == 'ringing'")
      await api.addWorkflowEdge(wid, ccid, eid, '')
      await api.addWorkflowEdge(wid, aid, asrid, '')
      await api.addWorkflowEdge(wid, asrid, icid, '')
      await api.addWorkflowEdge(wid, icid, tid2, "intent == 'answer'")
      await api.addWorkflowEdge(wid, icid, eid, '')
      await api.addWorkflowEdge(wid, tid2, eid, '')

      sandboxPresetId.value = 'phone_wechat'
      applySandboxPreset('phone_wechat')

      workflowDetailCache.delete(wid)
      await loadWorkflows()
      await rebuildSandboxWorkflowCandidates()
      if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) {
        sandboxWorkflowId.value = wid
        await loadDecomposeGraph(wid)
      }
      flash(`已生成微信电话对接业务员测试工作流（id=${wid}，7节点9边），预设已切换到 phone_wechat`, true)
    } else {
      const created = await api.createWorkflow(`${employeeName} · 沙盒测试流程`, `自动生成：员工 ${employeeId} 的最小可测流程。`)
      const wid = parsePositiveInt(created?.id)
      if (!wid) throw new Error('创建工作流失败：未返回有效 workflow id')
      const nStart = await api.addWorkflowNode(wid, 'start', '开始', {}, 120, 180)
      const nEmp = await api.addWorkflowNode(
        wid,
        'employee',
        `${employeeName} 节点`,
        { employee_id: employeeId, task: 'analyze_document' },
        360,
        180,
      )
      const nEnd = await api.addWorkflowNode(wid, 'end', '结束', {}, 620, 180)
      const sid = parsePositiveInt(nStart?.id)
      const eid = parsePositiveInt(nEmp?.id)
      const tid = parsePositiveInt(nEnd?.id)
      if (!sid || !eid || !tid) throw new Error('初始化节点失败，请重试')
      await api.addWorkflowEdge(wid, sid, eid, '')
      await api.addWorkflowEdge(wid, eid, tid, '')
      workflowDetailCache.delete(wid)
      await loadWorkflows()
      await rebuildSandboxWorkflowCandidates()
      if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) {
        sandboxWorkflowId.value = wid
        await loadDecomposeGraph(wid)
      }
      flash(`已生成测试工作流（id=${wid}），可直接进行 Mock / 真实测试`, true)
    }
  } catch (e) {
    const msg = errMessage(e)
    if (msg.includes('缺少认证凭证') || msg.includes('无效的认证凭证') || msg.includes('401')) {
      flash('自动生成工作流失败：登录已失效，请重新登录工作台后重试', false)
      return
    }
    flash(`自动生成工作流失败：${msg}`, false)
  } finally {
    sandboxAutoCreateBusy.value = false
  }
}

// 加载员工列表
async function loadEmployees() {
  try {
    const [sqlRows, v1Rows] = await Promise.all([
      api.listEmployees().catch(() => []),
      api.listV1Packages('employee_pack', '', 120, 0).catch(() => ({ packages: [] })),
    ])
    const merged = new Map()
    for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
      const id = String(e?.id || '').trim()
      if (!id) continue
      merged.set(id, {
        id,
        name: String(e?.name || id).trim() || id,
        version: String(e?.version || '').trim(),
        description: typeof e?.description === 'string' ? e.description : '',
        industry: String(e?.industry || '').trim(),
        sourceLabel: '执行器目录',
      })
    }
    for (const p of v1Rows?.packages || []) {
      const id = String(p?.id || '').trim()
      if (!id) continue
      if (merged.has(id)) continue
      merged.set(id, {
        id,
        name: String(p?.name || id).trim() || id,
        version: String(p?.version || '').trim(),
        description: typeof p?.description === 'string' ? p.description : '',
        industry: String(p?.industry || '').trim(),
        sourceLabel: '本地包目录',
      })
    }
    employees.value = filterOutPlannedDutyEmployees([...merged.values()]).sort((a, b) =>
      String(a.name).localeCompare(String(b.name), 'zh-CN'),
    )
  } catch (e) {
    flash('加载员工失败: ' + errMessage(e), false)
    employees.value = []
  }
}

// 加载执行记录（聚合所有工作流）
async function loadExecutions() {
  loading.value = true
  try {
    if (!workflows.value.length) {
      await loadWorkflows()
    }
    const parts = []
    for (const w of workflows.value) {
      try {
        const rows = await api.listWorkflowExecutions(w.id)
        for (const r of rows || []) {
          parts.push({ ...r, workflow_id: w.id })
        }
      } catch {
        /* 单个失败跳过 */
      }
    }
    parts.sort((a, b) => new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime())
    executions.value = parts
  } catch (e) {
    flash('加载执行记录失败: ' + errMessage(e), false)
    executions.value = []
  } finally {
    loading.value = false
  }
}

async function loadTriggersPanel() {
  triggersLoading.value = true
  triggersMsg.value = ''
  try {
    if (!workflows.value.length) await loadWorkflows()
    if (!triggersWorkflowId.value && workflows.value.length) {
      triggersWorkflowId.value = workflows.value[0].id
    }
    await refreshTriggersList()
  } catch (e) {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  } finally {
    triggersLoading.value = false
  }
}

async function refreshTriggersList() {
  const wid = Number(triggersWorkflowId.value)
  if (!wid) {
    triggerRows.value = []
    return
  }
  const rows = await api.listWorkflowTriggers(wid)
  triggerRows.value = Array.isArray(rows) ? rows : []
}

function onTriggersWorkflowChange() {
  refreshTriggersList().catch((e) => {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  })
}

async function addCronTrigger() {
  const wid = Number(triggersWorkflowId.value)
  if (!wid) return
  triggersMsg.value = ''
  try {
    await api.createWorkflowTrigger(wid, {
      trigger_type: 'cron',
      trigger_key: '',
      config: { cron: triggersCronExpr.value.trim() || '0 0 * * *' },
      is_active: true,
    })
    triggersMsgOk.value = true
    triggersMsg.value = '已添加 Cron 触发器'
    await refreshTriggersList()
  } catch (e) {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  }
}

async function addWebhookTrigger() {
  const wid = Number(triggersWorkflowId.value)
  if (!wid) return
  triggersMsg.value = ''
  try {
    await api.createWorkflowTrigger(wid, {
      trigger_type: 'webhook',
      trigger_key: 'default',
      config: {},
      is_active: true,
    })
    triggersMsgOk.value = true
    triggersMsg.value = '已添加 Webhook 触发器'
    await refreshTriggersList()
  } catch (e) {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  }
}

async function removeTriggerRow(triggerId: number) {
  const wid = Number(triggersWorkflowId.value)
  if (!wid || !triggerId) return
  try {
    await api.deleteWorkflowTrigger(wid, triggerId)
    triggersMsgOk.value = true
    triggersMsg.value = '已停用触发器'
    await refreshTriggersList()
  } catch (e) {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  }
}

async function testWebhookTrigger() {
  const wid = Number(triggersWorkflowId.value)
  if (!wid) return
  triggersMsg.value = ''
  try {
    let payload = {}
    try {
      payload = JSON.parse(triggersWebhookJson.value || '{}')
    } catch {
      throw new Error('Webhook 测试 JSON 无效')
    }
    const res = await api.workflowWebhookRun(wid, payload)
    triggersMsgOk.value = true
    triggersMsg.value = `Webhook 测试成功：${JSON.stringify(res).slice(0, 500)}`
  } catch (e) {
    triggersMsgOk.value = false
    triggersMsg.value = errMessage(e)
  }
}

async function loadDecomposeGraph(workflowId: number) {
  if (!workflowId) {
    decomposeNodes.value = []
    decomposeEdges.value = []
    return
  }
  decomposeLoading.value = true
  try {
    const res = await api.getWorkflow(workflowId)
    decomposeNodes.value = res.nodes || []
    decomposeEdges.value = res.edges || []
  } catch {
    decomposeNodes.value = []
    decomposeEdges.value = []
  } finally {
    decomposeLoading.value = false
  }
}

function applySandboxPreset(id: string) {
  const p = WORKFLOW_SANDBOX_PRESETS.find((x) => x.id === id)
  if (!p) return
  sandboxInputJson.value = JSON.stringify(p.input_data, null, 2)
}

function onSandboxPresetChange(ev: Event) {
  const t = ev.target as HTMLSelectElement | null
  const v = t?.value
  if (typeof v !== 'string') return
  sandboxPresetId.value = v
  applySandboxPreset(v)
}

async function openSandboxFor(workflowId: number) {
  const wid = parsePositiveInt(workflowId)
  if (wid > 0) {
    try {
      const detail = await getWorkflowDetailCached(wid)
      const nodes: WorkflowNodeRow[] = Array.isArray(detail?.nodes) ? (detail.nodes as WorkflowNodeRow[]) : []
      const eNode = nodes.find((n) => n?.node_type === 'employee' && n?.config?.employee_id)
      if (eNode) sandboxEmployeeId.value = String(eNode.config?.employee_id ?? '').trim()
    } catch {
      /* ignore */
    }
  }
  if (sandboxEmployeeId.value) {
    await rebuildSandboxWorkflowCandidates()
    if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) sandboxWorkflowId.value = wid
  } else {
    sandboxWorkflowId.value = wid
  }
  sandboxReport.value = null
  sandboxError.value = ''
  activeTab.value = 'sandbox'
  await loadDecomposeGraph(sandboxWorkflowId.value)
}

const graphForDecompose = computed(() => {
  if (activeTab.value === 'editor' && currentWorkflow.value) {
    return { nodes: nodes.value, edges: edges.value }
  }
  if (activeTab.value === 'sandbox' && sandboxWorkflowId.value) {
    return { nodes: decomposeNodes.value, edges: decomposeEdges.value }
  }
  return { nodes: [], edges: [] }
})

const graphSummary = computed(() =>
  computeGraphSummary(graphForDecompose.value.nodes, graphForDecompose.value.edges),
)

const mermaidSource = computed(() =>
  buildMermaidFlowchart(graphForDecompose.value.nodes, graphForDecompose.value.edges),
)

async function copyMermaidToClipboard() {
  const t = mermaidSource.value
  try {
    await navigator.clipboard.writeText(t)
    flash('已复制 Mermaid 到剪贴板', true)
  } catch {
    flash('复制失败，请手动全选复制', false)
  }
}

/** ?edit=id&tab=sandbox|editor|list|executions — 进入后清除 query，避免刷新重复进入 */
async function applyWorkflowRouteQuery() {
  const rawEdit = route.query.edit
  const tabRaw = String(route.query.tab || '')
    .toLowerCase()
    .trim()
  const allowed = new Set(['list', 'editor', 'sandbox', 'executions'])
  const tab = allowed.has(tabRaw) ? tabRaw : ''

  if (rawEdit != null && String(rawEdit).trim() !== '') {
    const id = parseInt(String(rawEdit), 10)
    if (!Number.isNaN(id) && id > 0) {
      showCreateModal.value = false
      await loadWorkflows()
      if (tab === 'sandbox') {
        sandboxWorkflowId.value = id
        sandboxReport.value = null
        sandboxError.value = ''
        activeTab.value = 'sandbox'
        await loadDecomposeGraph(id)
      } else if (tab === 'executions') {
        activeTab.value = 'executions'
        await loadExecutions()
      } else if (tab === 'list') {
        activeTab.value = 'list'
        currentWorkflow.value = null
        decomposeNodes.value = []
        decomposeEdges.value = []
      } else {
        await editWorkflow(id)
      }
      try {
        await router.replace({ name: 'workbench-workflow', query: {} })
      } catch {
        /* ignore */
      }
      return
    }
  }

  if (tab && allowed.has(tab)) {
    activeTab.value = tab
    try {
      await router.replace({ name: 'workbench-workflow', query: {} })
    } catch {
      /* ignore */
    }
  }
}

function parseSandboxInput() {
  const raw = (sandboxInputJson.value || '').trim()
  if (!raw) return {}
  try {
    const o = JSON.parse(raw)
    return typeof o === 'object' && o !== null && !Array.isArray(o) ? o : {}
  } catch (e: unknown) {
    throw new Error('运行变量须为合法 JSON 对象: ' + errMessage(e))
  }
}

async function runSandboxValidate() {
  await runSandbox('validate')
}

async function runSandbox(mode: 'validate' | 'mock' | 'real') {
  if (!sandboxWorkflowId.value) {
    flash('请先选择员工和关联工作流', false)
    return
  }
  sandboxLoading.value = true
  sandboxError.value = ''
  sandboxReport.value = null
  lastRunMeta.value = {
    mode,
    startedAt: new Date().toISOString(),
    precheck: mode === 'real' ? (lastRunMeta.value?.precheck || null) : null,
  }
  try {
    const input = parseSandboxInput()
    const validateOnly = mode === 'validate'
    const mockEmployees = mode !== 'real'
    sandboxReport.value = await api.workflowSandboxRun(sandboxWorkflowId.value, {
      input_data: input,
      mock_employees: mockEmployees,
      validate_only: validateOnly,
    })
    if (validateOnly) {
      flash(sandboxReport.value.ok ? '校验通过' : '校验未通过', sandboxReport.value.ok)
    } else if (mode === 'real') {
      flash('真实测试完成', true)
    } else {
      flash('Mock 测试完成', true)
    }
  } catch (e: unknown) {
    sandboxError.value = errMessage(e)
    flash(sandboxError.value, false)
    if (mode === 'real') {
      await autoLocateLikelyEmployeeNode()
    }
  } finally {
    sandboxLoading.value = false
  }
}

async function runSandboxMock() {
  await runSandbox('mock')
}

async function runSandboxReal() {
  if (!canRunReal.value) {
    if (realRunDisabledReason.value) flash(realRunDisabledReason.value, false)
    return
  }
  const pre = await runRealPrecheck(sandboxWorkflowId.value)
  lastRunMeta.value = {
    mode: 'real',
    startedAt: new Date().toISOString(),
    precheck: pre,
  }
  if (!pre.ok) {
    const first = pre.issues[0] || '真实测试前置检查未通过'
    sandboxError.value = first
    flash(`真实测试已阻断：${first}`, false)
    await autoLocateLikelyEmployeeNode(pre.nodeIds || [])
    return
  }
  await runSandbox('real')
}

async function runRealPrecheck(workflowId: number) {
  const detail = await getWorkflowDetailCached(workflowId)
  const wsNodes: WorkflowNodeRow[] = Array.isArray(detail?.nodes) ? (detail.nodes as WorkflowNodeRow[]) : []
  const empNodes = wsNodes.filter((n) => n && n.node_type === 'employee')
  const issues: string[] = []
  const missingConfig: string[] = []
  const statusErrors: string[] = []
  const issueNodeIds: number[] = []
  for (const n of empNodes) {
    const cfg = n && typeof n.config === 'object' ? n.config : {}
    const eid = String(cfg.employee_id || '').trim()
    if (!eid) {
      missingConfig.push(`节点「${n.name || n.id}」缺少 employee_id`)
      issueNodeIds.push(parsePositiveInt(n.id))
      continue
    }
    try {
      const st = await api.getEmployeeStatus(eid)
      if (!st || st.status === 'not_found') {
        statusErrors.push(`员工 ${eid} 不存在或未加载到执行器目录`)
        issueNodeIds.push(parsePositiveInt(n.id))
      } else if (typeof st.status === 'string' && st.status.toLowerCase() !== 'active') {
        statusErrors.push(`员工 ${eid} 状态异常：${st.status}`)
        issueNodeIds.push(parsePositiveInt(n.id))
      }
    } catch (e: unknown) {
      statusErrors.push(`员工 ${eid} 状态检查失败：${errMessage(e)}`)
      issueNodeIds.push(parsePositiveInt(n.id))
    }
  }
  issues.push(...missingConfig, ...statusErrors)
  return {
    ok: issues.length === 0,
    checkedCount: empNodes.length,
    missingConfigCount: missingConfig.length,
    statusErrorCount: statusErrors.length,
    nodeIds: issueNodeIds.filter((x) => x > 0),
    issues,
  }
}

async function autoLocateLikelyEmployeeNode(preferredNodeIds: number[] = []) {
  const targetWorkflowId = parsePositiveInt(sandboxWorkflowId.value)
  if (!targetWorkflowId) return
  let targetNodeId = parsePositiveInt(preferredNodeIds[0])
  if (!targetNodeId) {
    const graphNodes = Array.isArray(decomposeNodes.value) ? decomposeNodes.value : []
    const emp = graphNodes.find((n) => n && n.node_type === 'employee')
    targetNodeId = parsePositiveInt(emp?.id)
  }
  if (!targetNodeId) return
  if (!currentWorkflow.value || parsePositiveInt(currentWorkflow.value.id) !== targetWorkflowId) {
    await editWorkflow(targetWorkflowId)
  } else {
    activeTab.value = 'editor'
  }
  await nextTick()
  focusedNodeId.value = targetNodeId
  const el = document.querySelector(`.workflow-node[data-node-id="${targetNodeId}"]`)
  if (el && typeof el.scrollIntoView === 'function') {
    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
    } catch {
      /* ignore */
    }
  }
  setTimeout(() => {
    if (focusedNodeId.value === targetNodeId) focusedNodeId.value = 0
  }, 3200)
}

// 创建工作流
async function createWorkflow() {
  if (!newWorkflow.value.name) {
    flash('请输入工作流名称', false)
    return
  }

  try {
    const res = await api.createWorkflow(newWorkflow.value.name, newWorkflow.value.description)
    flash('工作流创建成功')
    showCreateModal.value = false
    newWorkflow.value = { name: '', description: '' }
    homeLlmHint.value = ''
    homeIntentHint.value = ''
    await loadWorkflows()
  } catch (e: unknown) {
    flash('创建工作流失败: ' + errMessage(e), false)
  }
}

watch(showCreateModal, (open) => {
  if (!open) {
    homeLlmHint.value = ''
    homeIntentHint.value = ''
  }
})

// 编辑工作流
function openV2Editor(workflowId: number) {
  router.push({ name: 'workflow-v2-editor', params: { id: String(workflowId) } })
}

async function editWorkflow(workflowId: number) {
  loading.value = true
  try {
    const res = await api.getWorkflow(workflowId)
    currentWorkflow.value = res
    nodes.value = res.nodes
    edges.value = res.edges
    activeTab.value = 'editor'
    await loadDecomposeGraph(workflowId)
  } catch (e: unknown) {
    flash('加载工作流失败: ' + errMessage(e), false)
  } finally {
    loading.value = false
  }
}

// 将画布节点/边同步到服务端（沙盒与生产执行均读服务端图）
async function saveWorkflow() {
  if (!currentWorkflow.value) {
    flash('请先选择工作流', false)
    return
  }
  const wid = currentWorkflow.value.id
  loading.value = true
  try {
    const cur = await api.getWorkflow(wid)
    for (const n of cur.nodes || []) {
      await api.deleteWorkflowNode(n.id)
    }
    const idMap = new Map()
    for (const n of nodes.value) {
      const created = await api.addWorkflowNode(
        wid,
        String(n.node_type ?? 'start'),
        String(n.name ?? ''),
        n.config || {},
        n.position_x ?? 0,
        n.position_y ?? 0,
      )
      idMap.set(n.id, created.id)
    }
    for (const e of edges.value) {
      const s = idMap.get(e.source_node_id)
      const t = idMap.get(e.target_node_id)
      if (s && t) {
        await api.addWorkflowEdge(wid, s, t, e.condition || '')
      }
    }
    await editWorkflow(wid)
    flash('已同步到服务端，可进行沙盒测试或生产执行')
  } catch (e: unknown) {
    flash('保存失败: ' + errMessage(e), false)
  } finally {
    loading.value = false
  }
}

// 切换工作流状态
async function toggleWorkflowStatus(workflowId: number, isActive: boolean) {
  try {
    await api.updateWorkflow(workflowId, null, null, isActive)
    flash(`工作流已${isActive ? '激活' : '停用'}`)
    await loadWorkflows()
  } catch (e: unknown) {
    flash('更新工作流状态失败: ' + errMessage(e), false)
  }
}

// 删除工作流
async function deleteWorkflow(workflowId: number) {
  if (!confirm('确定要删除这个工作流吗？')) {
    return
  }

  try {
    await api.deleteWorkflow(workflowId)
    flash('工作流删除成功')
    await loadWorkflows()
  } catch (e: unknown) {
    flash('删除工作流失败: ' + errMessage(e), false)
  }
}

/** 批量删除列表中所有未激活（is_active === false）的工作流 */
async function bulkDeleteInactiveWorkflows() {
  const targets = (workflows.value || []).filter((w) => w && !w.is_active)
  if (!targets.length) {
    flash('当前没有「未激活」的自动化任务可删', false)
    return
  }
  if (
    !window.confirm(
      `将永久删除 ${targets.length} 个未激活任务（含节点、边、运行记录、触发器与版本快照）。不可恢复。\n\n任务名预览：${targets
        .slice(0, 5)
        .map((w) => w.name || `#${w.id}`)
        .join('、')}${targets.length > 5 ? '…' : ''}\n\n确定继续？`,
    )
  ) {
    return
  }
  bulkDeleteInactiveBusy.value = true
  let okCount = 0
  try {
    for (const w of targets) {
      await api.deleteWorkflow(w.id)
      okCount += 1
    }
    flash(`已删除 ${okCount} 个未激活任务`, true)
    await loadWorkflows()
    if (activeTab.value === 'executions') {
      await loadExecutions()
    }
    if (activeTab.value === 'triggers' && triggersWorkflowId.value) {
      await onTriggersWorkflowChange()
    }
  } catch (e: unknown) {
    flash(`批量删除中断（已删 ${okCount} 个）：${errMessage(e)}`, false)
    await loadWorkflows()
  } finally {
    bulkDeleteInactiveBusy.value = false
  }
}

// 执行工作流（生产路径，写入执行记录）
async function executeWorkflow(workflowId: number) {
  try {
    await api.executeWorkflow(workflowId, {})
    flash('工作流执行成功')
    activeTab.value = 'executions'
    await loadExecutions()
  } catch (e: unknown) {
    flash('执行工作流失败: ' + errMessage(e), false)
  }
}

// 添加节点
function addNode(type: string) {
  const node = {
    id: Date.now(),
    node_type: type,
    name: getNodeTypeLabel(type),
    config: {},
    position_x: 100,
    position_y: 100
  }
  nodes.value.push(node)
}

// 添加员工节点
function addEmployeeNode(employeeId: string | number, employeeName: string) {
  const node = {
    id: Date.now(),
    node_type: 'employee',
    name: employeeName,
    config: {
      employee_id: employeeId,
      task: 'analyze_document'
    },
    position_x: 100,
    position_y: 100
  }
  nodes.value.push(node)
}

// 添加知识检索节点（默认配置可在选中节点后编辑）
function addKnowledgeSearchNode() {
  const node = {
    id: Date.now(),
    node_type: 'knowledge_search',
    name: '知识检索',
    config: {
      query: '',
      collection_ids: [],
      top_k: 6,
      min_score: 0,
      output_var: 'knowledge'
    },
    position_x: 100,
    position_y: 100
  }
  nodes.value.push(node)
}

// 删除节点
function deleteNode(nodeId: number) {
  // 删除节点
  nodes.value = nodes.value.filter(node => node.id !== nodeId)
  // 删除相关的边
  edges.value = edges.value.filter(edge => 
    edge.source_node_id !== nodeId && edge.target_node_id !== nodeId
  )
}

// 显示节点配置
function showNodeConfig(nodeId: number) {
  const node = nodes.value.find(n => n.id === nodeId)
  if (node) {
    selectedNode.value = JSON.parse(JSON.stringify(node))
    showNodeConfigModal.value = true
  }
}

// 保存节点配置
function saveNodeConfig() {
  const sel = selectedNode.value
  if (sel) {
    const index = nodes.value.findIndex((n) => n.id === sel.id)
    if (index !== -1) {
      nodes.value[index] = JSON.parse(JSON.stringify(sel))
    }
    showNodeConfigModal.value = false
  }
}

// 开始拖拽
function startDrag(event: MouseEvent, node: WorkflowNodeRow) {
  dragging.value = true
  dragNode.value = node
  const el = event.target as HTMLElement
  const rect = el.getBoundingClientRect()
  dragOffset.value = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  }
}

// 开始连接
function startConnect(event: MouseEvent, nodeId: number, port: string) {
  connecting.value = true
  connectStart.value = nodeId
  connectStartPort.value = port
}

// 获取边的路径
function getEdgePath(edge: WorkflowEdgeRow) {
  const sourceNode = nodes.value.find(n => n.id === edge.source_node_id)
  const targetNode = nodes.value.find(n => n.id === edge.target_node_id)
  if (!sourceNode || !targetNode) return ''
  
  return `M ${sourceNode.position_x + 100} ${sourceNode.position_y + 25} L ${targetNode.position_x} ${targetNode.position_y + 25}`
}

// 选择边
function selectEdge(edgeId: number) {
  // 这里可以添加边的编辑逻辑
  console.log('Selected edge:', edgeId)
}

// 监听鼠标移动
function onMouseMove(event: MouseEvent) {
  if (!canvas.value) return
  if (dragging.value && dragNode.value) {
    const canvasRect = canvas.value.getBoundingClientRect()
    dragNode.value.position_x = event.clientX - canvasRect.left - dragOffset.value.x
    dragNode.value.position_y = event.clientY - canvasRect.top - dragOffset.value.y
  }
}

// 监听鼠标释放
function onMouseUp() {
  dragging.value = false
  dragNode.value = null
  connecting.value = false
  connectStart.value = null
  connectStartPort.value = ''
}

// 监听点击
function onCanvasClick(event: MouseEvent) {
  const t = event.target as HTMLElement | null
  if (!t?.closest('.workflow-node') && !t?.closest('.connection-line')) {
    // 点击空白处，取消选择
  }
}

// 初始化事件监听器
onMounted(async () => {
  await Promise.all([loadWorkflows(), loadEmployees()])

  try {
    const fromHome = sessionStorage.getItem('workbench_home_draft')
    const fromIntent = sessionStorage.getItem('workbench_home_intent')
    const fromLlm = sessionStorage.getItem('workbench_home_llm')
    const fromLlmMode = sessionStorage.getItem('workbench_home_llm_mode')
    if (fromIntent) {
      sessionStorage.removeItem('workbench_home_intent')
      if (fromHome) {
        const key = typeof fromIntent === 'string' ? fromIntent.trim() : ''
        homeIntentHint.value = INTENT_FROM_HOME[key] || ''
      }
    }
    if (fromLlm) {
      sessionStorage.removeItem('workbench_home_llm')
      if (fromLlmMode) sessionStorage.removeItem('workbench_home_llm_mode')
      try {
        const o = JSON.parse(fromLlm)
        const prov = typeof o.provider === 'string' ? o.provider.trim() : ''
        const mod = typeof o.model === 'string' ? o.model.trim() : ''
        if (prov && mod) {
          if (fromLlmMode === 'auto') {
            homeLlmHint.value = `Auto · 账户默认模型：${prov} · ${mod}`
          } else {
            homeLlmHint.value = `自选模型（已写入账户默认）：${prov} · ${mod}`
          }
        }
      } catch {
        homeLlmHint.value = ''
      }
    }
    const skipHomeModal = route.query.edit != null && String(route.query.edit).trim() !== ''
    if (fromHome && !skipHomeModal) {
      sessionStorage.removeItem('workbench_home_draft')
      newWorkflow.value.description = fromHome
      showCreateModal.value = true
      flash('已从工作台首页带入描述，请填写工作流名称后创建。', true)
    }
  } catch {
    /* ignore */
  }

  await applyWorkflowRouteQuery()

  // 添加全局鼠标事件监听器
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  
  // 添加画布点击事件监听器
  if (canvas.value) {
    canvas.value.addEventListener('click', onCanvasClick)
  }
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  if (canvas.value) {
    canvas.value.removeEventListener('click', onCanvasClick)
  }
})

watch(activeTab, async (newTab) => {
  if (newTab === 'executions') {
    await loadExecutions()
  }
  if (newTab === 'triggers') {
    await loadTriggersPanel()
  }
  if (newTab === 'sandbox') {
    if (!workflows.value.length) {
      await loadWorkflows()
    }
    if (!employees.value.length) {
      await loadEmployees()
    }
    if (!sandboxEmployeeId.value && employees.value.length) {
      sandboxEmployeeId.value = String(employees.value[0].id || '')
      return
    }
    if (sandboxEmployeeId.value) {
      await rebuildSandboxWorkflowCandidates()
    } else if (sandboxWorkflowId.value) {
      await loadDecomposeGraph(sandboxWorkflowId.value)
    }
  }
})

watch(sandboxEmployeeId, async (id) => {
  if (activeTab.value !== 'sandbox') return
  sandboxReport.value = null
  sandboxError.value = ''
  if (!id) {
    sandboxWorkflowCandidates.value = []
    sandboxWorkflowId.value = 0
    decomposeNodes.value = []
    decomposeEdges.value = []
    return
  }
  await rebuildSandboxWorkflowCandidates()
})

watch(
  () => route.fullPath,
  async () => {
    if (route.name !== 'workbench-workflow') return
    if (route.query.edit == null && String(route.query.tab || '').trim() === '') return
    await applyWorkflowRouteQuery()
  },
)

watch(sandboxWorkflowId, async (id) => {
  if (activeTab.value !== 'sandbox') return
  if (id) await loadDecomposeGraph(id)
})
</script>

<style scoped>
.workflow-page {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: var(--page-pad-y) var(--layout-pad-x);
  box-sizing: border-box;
}

.page-header {
  margin-bottom: 2rem;
}

.page-title {
  font-size: 1.75rem;
  margin: 0 0 0.5rem;
  color: #ffffff;
}

.page-desc {
  font-size: 0.9rem;
  color: rgba(255,255,255,0.4);
  margin: 0 0 1.25rem;
}

.flash {
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.flash-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.flash-err {
  background: rgba(255,80,80,0.1);
  color: #ff6b6b;
}

.loading {
  text-align: center;
  padding: 3rem;
  color: rgba(255,255,255,0.3);
}

.workflows-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 17rem), 1fr));
  gap: 1rem;
}

.workflow-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
  transition: all 0.2s;
}

.workflow-card:hover {
  border-color: rgba(255,255,255,0.2);
  transform: translateY(-2px);
}

.workflow-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 0.75rem;
}

.workflow-card-title {
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
}

.workflow-card-status {
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.workflow-card-status.active {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.workflow-card-status.inactive {
  background: rgba(255,193,7,0.1);
  color: #ffc107;
}

.workflow-card-desc {
  font-size: 0.875rem;
  color: rgba(255,255,255,0.5);
  line-height: 1.5;
  margin: 0 0 1rem;
}

.workflow-card-meta {
  font-size: 0.75rem;
  color: rgba(255,255,255,0.3);
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.workflow-card-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.empty-state {
  text-align: center;
  padding: 4rem 1rem;
  color: rgba(255,255,255,0.3);
}

.empty-state p {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
}

.empty-hint {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.2);
}

.btn {
  padding: 0.5rem 1rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255,255,255,0.7);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  background: rgba(255,255,255,0.06);
  color: #ffffff;
}

.btn-primary {
  background: #60a5fa;
  color: #0a0a0a;
  border: none;
}

.btn-primary:hover {
  background: #3b82f6;
  color: #0a0a0a;
}

.btn-danger {
  background: rgba(239,68,68,0.1);
  color: #ef4444;
  border-color: rgba(239,68,68,0.3);
}

.btn-danger:hover {
  background: rgba(239,68,68,0.2);
  color: #ef4444;
}

.btn-success {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
  border-color: rgba(74,222,128,0.3);
}

.btn-success:hover {
  background: rgba(74,222,128,0.2);
  color: #4ade80;
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

/* 编辑器样式 */
.workflow-editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 0.5px solid rgba(255,255,255,0.1);
}

.editor-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
}

.editor-actions {
  display: flex;
  gap: 0.5rem;
}

.workflow-editor {
  display: flex;
  flex-direction: row;
  gap: clamp(1rem, 3vw, 2rem);
  min-height: clamp(280px, 42vh, 720px);
  min-width: 0;
}

.node-library {
  flex: 0 0 min(200px, 32vw);
  width: min(200px, 32vw);
  max-width: 100%;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1rem;
  overflow-y: auto;
  min-width: 0;
}

.node-library h3 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 1rem;
}

.node-category {
  margin-bottom: 1.5rem;
}

.node-category h4 {
  font-size: 0.8rem;
  font-weight: 500;
  color: rgba(255,255,255,0.5);
  margin: 0 0 0.5rem;
}

.node-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 0.5rem;
}

.node-item:hover {
  background: rgba(255,255,255,0.06);
}

.node-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 600;
}

.start-node {
  background: rgba(74,222,128,0.2);
  color: #4ade80;
}

.end-node {
  background: rgba(239,68,68,0.2);
  color: #ef4444;
}

.employee-node {
  background: rgba(96,165,250,0.2);
  color: #60a5fa;
}

.condition-node {
  background: rgba(251,191,36,0.2);
  color: #fbbf24;
}

.workflow-canvas {
  flex: 1 1 auto;
  min-width: 0;
  background: #0a0a0a;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  position: relative;
  overflow: auto;
  min-height: clamp(280px, 42vh, 720px);
}

.workflow-node {
  position: absolute;
  width: min(200px, 92%);
  max-width: 200px;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  cursor: move;
  z-index: 10;
}

.workflow-node--focus {
  border-color: rgba(251, 191, 36, 0.92);
  box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.42), 0 0 20px rgba(251, 191, 36, 0.35);
  animation: wfFocusPulse 1s ease-in-out 2;
}

@keyframes wfFocusPulse {
  0% { transform: translateY(0); }
  50% { transform: translateY(-2px); }
  100% { transform: translateY(0); }
}

@media (max-width: 768px) {
  .workflow-editor {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }

  .node-library {
    flex: 0 0 auto;
    width: 100%;
    max-height: min(40vh, 320px);
  }

  .workflow-canvas {
    min-height: clamp(220px, 48vh, 600px);
  }
}

.node-header {
  padding: 0.5rem;
  border-bottom: 0.5px solid rgba(255,255,255,0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.start-node-header {
  background: rgba(74,222,128,0.1);
}

.end-node-header {
  background: rgba(239,68,68,0.1);
}

.employee-node-header {
  background: rgba(96,165,250,0.1);
}

.condition-node-header {
  background: rgba(251,191,36,0.1);
}

.node-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: #ffffff;
}

.node-delete {
  background: none;
  border: none;
  color: rgba(255,255,255,0.5);
  cursor: pointer;
  font-size: 1.2rem;
  line-height: 1;
  padding: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.node-delete:hover {
  background: rgba(255,255,255,0.1);
  color: #ffffff;
}

.node-body {
  padding: 0.5rem;
}

.node-type {
  font-size: 0.75rem;
  color: rgba(255,255,255,0.5);
  margin-bottom: 0.5rem;
}

.node-config {
  background: rgba(255,255,255,0.06);
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.7);
  cursor: pointer;
  transition: all 0.2s;
}

.node-config:hover {
  background: rgba(255,255,255,0.1);
  color: #ffffff;
}

.node-ports {
  display: flex;
  justify-content: space-between;
  padding: 0 0.5rem 0.5rem;
}

.port {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(255,255,255,0.3);
  cursor: crosshair;
}

.port-input {
  background: rgba(96,165,250,0.5);
}

.port-output {
  background: rgba(74,222,128,0.5);
}

.workflow-connections {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: all;
  z-index: 5;
}

.connection-line {
  fill: none;
  stroke: rgba(96,165,250,0.6);
  stroke-width: 2;
  cursor: pointer;
}

.connection-line:hover {
  stroke: rgba(96,165,250,1);
}

/* 执行记录样式 */
.executions-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 0.5px solid rgba(255,255,255,0.1);
}

.executions-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
}

.executions-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.execution-item {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
}

.execution-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.execution-id {
  font-size: 0.875rem;
  color: rgba(255,255,255,0.5);
}

.execution-status {
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.execution-status.pending {
  background: rgba(251,191,36,0.1);
  color: #fbbf24;
}

.execution-status.running {
  background: rgba(96,165,250,0.1);
  color: #60a5fa;
}

.execution-status.completed {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.execution-status.failed {
  background: rgba(239,68,68,0.1);
  color: #ef4444;
}

.execution-info {
  font-size: 0.875rem;
  color: rgba(255,255,255,0.5);
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.execution-error {
  background: rgba(239,68,68,0.1);
  border: 0.5px solid rgba(239,68,68,0.3);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
  color: #ef4444;
  font-size: 0.875rem;
}

.execution-output {
  background: rgba(96,165,250,0.1);
  border: 0.5px solid rgba(96,165,250,0.3);
  border-radius: 8px;
  padding: 1rem;
  font-size: 0.875rem;
}

.execution-output pre {
  margin: 0.5rem 0 0;
  padding: 0.5rem;
  background: rgba(0,0,0,0.3);
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.8);
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.modal {
  width: 100%;
  max-width: min(420px, 100%);
  box-sizing: border-box;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  padding: 1.5rem;
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0 0 1.25rem;
  color: #ffffff;
}

.form-group {
  margin-bottom: 1rem;
}

.modal-intent-hint {
  margin: 0 0 0.65rem;
  font-size: 0.8rem;
  line-height: 1.45;
  color: rgba(253, 230, 138, 0.95);
  padding: 0.5rem 0.65rem;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.28);
}

.modal-llm-hint {
  margin: 0 0 1rem;
  font-size: 0.8rem;
  line-height: 1.45;
  color: rgba(199, 210, 254, 0.95);
  padding: 0.5rem 0.65rem;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(129, 140, 248, 0.25);
}

.label {
  display: block;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.5);
  margin-bottom: 0.4rem;
}

.input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
  color: #ffffff;
  font-size: 0.9rem;
  outline: none;
}

.input:focus {
  border-color: rgba(255,255,255,0.3);
}

.input[type="textarea"] {
  resize: vertical;
  min-height: 80px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}

.page-header-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.page-header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.wf-subtabs {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.wf-subtab {
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.03);
  color: rgba(255, 255, 255, 0.55);
  font-size: 0.875rem;
  cursor: pointer;
}

.wf-subtab:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.2);
}

.wf-subtab--active {
  color: #fff;
  background: rgba(96, 165, 250, 0.15);
  border-color: rgba(96, 165, 250, 0.35);
}

.btn-sandbox {
  border-color: rgba(129, 140, 248, 0.35);
  color: #a5b4fc;
}

.btn-sandbox:hover {
  background: rgba(129, 140, 248, 0.12);
  color: #e0e7ff;
}

.sandbox-panel {
  max-width: 920px;
}

.sandbox-head {
  margin-bottom: 1.25rem;
}

.sandbox-title {
  margin: 0 0 0.5rem;
  font-size: 1.2rem;
  color: #fff;
}

.sandbox-lead {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.5);
}

.sandbox-controls {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  margin-bottom: 1rem;
}

.sandbox-preset-block {
  margin-bottom: 1rem;
}

.sandbox-preset-hint {
  margin: 0.45rem 0 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.45);
}

.wf-decompose-sandbox {
  margin-bottom: 1.25rem;
  padding: 1rem 1.1rem;
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.2);
}

.wf-decompose-h3 {
  margin: 0 0 0.65rem;
  font-size: 1rem;
  color: #e5e7eb;
}

.wf-decompose-drawer {
  margin-top: 1.25rem;
  padding: 0.75rem 1rem;
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.2);
}

.wf-decompose-summary {
  cursor: pointer;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}

.wf-decompose-body {
  margin-top: 0.75rem;
}

.wf-decompose-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0 0 0.5rem;
}

.wf-count-pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 6px;
  background: rgba(96, 165, 250, 0.12);
  color: rgba(191, 219, 254, 0.95);
}

.wf-decompose-warn {
  margin: 0 0 0.5rem 1rem;
  padding: 0;
  font-size: 0.82rem;
  color: rgba(251, 191, 36, 0.95);
}

.wf-mermaid-actions {
  margin-bottom: 0.5rem;
}

.wf-mermaid-pre {
  max-height: 220px;
  overflow: auto;
  margin: 0;
}

.sandbox-select {
  width: min(100%, 420px);
  max-width: 420px;
  min-height: 46px;
  padding: 0.65rem 2.35rem 0.65rem 0.85rem;
  border: 1px solid rgba(56, 189, 248, 0.42);
  border-radius: 10px;
  background-color: rgba(2, 6, 23, 0.9);
  color: rgba(248, 250, 252, 0.96);
  font-size: 0.98rem;
  line-height: 1.3;
  appearance: none;
  background-image:
    linear-gradient(45deg, transparent 50%, rgba(186, 230, 253, 0.95) 50%),
    linear-gradient(135deg, rgba(186, 230, 253, 0.95) 50%, transparent 50%);
  background-position:
    calc(100% - 18px) calc(50% - 3px),
    calc(100% - 12px) calc(50% - 3px);
  background-size: 6px 6px, 6px 6px;
  background-repeat: no-repeat;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.sandbox-controls .sandbox-select:hover {
  border-color: rgba(56, 189, 248, 0.75);
  background-color: rgba(3, 10, 27, 0.98);
}

.sandbox-controls .sandbox-select:focus,
.sandbox-controls .sandbox-select:focus-visible {
  outline: none;
  border-color: rgba(56, 189, 248, 0.92);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.2);
}

.sandbox-controls .sandbox-select:disabled {
  border-color: rgba(148, 163, 184, 0.28);
  color: rgba(148, 163, 184, 0.82);
  background-color: rgba(15, 23, 42, 0.5);
  cursor: not-allowed;
}

.sandbox-controls .sandbox-select option {
  color: #0f172a;
}

.sandbox-select--error {
  border-color: rgba(248, 113, 113, 0.9) !important;
  box-shadow: 0 0 0 2px rgba(248, 113, 113, 0.18);
}

@media (max-width: 768px) {
  .sandbox-select {
    width: 100%;
    max-width: 100%;
    min-height: 48px;
  }
}

.checkbox-inline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
}

.sandbox-json-block {
  margin-bottom: 1rem;
}

.sandbox-json {
  min-height: 140px;
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  resize: vertical;
}

.sandbox-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.sandbox-real-hint {
  margin: -0.5rem 0 1rem;
  font-size: 0.8rem;
  line-height: 1.45;
}

.sandbox-real-disabled {
  margin: -0.35rem 0 0.65rem;
  font-size: 0.78rem;
  color: rgba(251, 191, 36, 0.95);
}

.sandbox-flash {
  margin-bottom: 1rem;
}

.sandbox-report {
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 1rem 1.15rem;
  background: rgba(0, 0, 0, 0.25);
}

.sandbox-report-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.sandbox-pill {
  display: inline-flex;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
}

.sandbox-pill.ok {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
}

.sandbox-pill.err {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

.sandbox-pill.sm {
  font-size: 0.65rem;
  font-weight: 500;
}

.muted {
  color: rgba(255, 255, 255, 0.38);
  font-size: 0.82rem;
}

.sandbox-block {
  margin-top: 0.85rem;
}

.sandbox-block h4 {
  margin: 0 0 0.35rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.75);
}

.sandbox-block ul {
  margin: 0;
  padding-left: 1.1rem;
  color: rgba(255, 255, 255, 0.55);
  font-size: 0.85rem;
}

.sandbox-step {
  border: 0.5px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 0.5rem 0.65rem;
  margin-bottom: 0.5rem;
  background: rgba(255, 255, 255, 0.02);
}

.sandbox-step-h {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.65rem;
  align-items: center;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.85);
}

.sandbox-details {
  margin-top: 0.35rem;
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.45);
}

.sandbox-pre {
  margin: 0.35rem 0 0;
  padding: 0.5rem;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.35);
  overflow: auto;
  max-height: 220px;
  font-size: 0.72rem;
  line-height: 1.35;
  color: rgba(200, 220, 255, 0.9);
}

.mono {
  font-family: ui-monospace, monospace;
}

.triggers-panel {
  margin-top: 0.5rem;
}
.triggers-card {
  max-width: 640px;
  padding: 1.25rem;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.triggers-h3 {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
  color: rgba(255, 255, 255, 0.88);
}
.triggers-gap {
  margin-top: 0.5rem;
}
.trigger-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.trigger-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.65rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.mini-pre {
  margin: 0.35rem 0 0;
  font-size: 0.72rem;
  color: rgba(200, 220, 255, 0.85);
  white-space: pre-wrap;
  word-break: break-all;
}
.muted.small {
  font-size: 0.8rem;
}
</style>
