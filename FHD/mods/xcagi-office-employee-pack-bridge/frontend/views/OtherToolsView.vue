<template>
  <div class="page-view" id="view-other-tools">
    <div class="page-content">
      <div class="page-header">
        <h2>员工工作流管理</h2>
      </div>

      <div class="card" style="margin-bottom: 12px;">
        <h3 style="margin: 0 0 8px;">流程与员工</h3>

        <p v-if="ctx.clientModsUiOff" style="margin: 0; color: #6b7280;">
          当前为<strong>原版模式</strong>（前端不加载扩展）：在此查看与管理副窗中的<strong>固定六类</strong>工作流；开关样式与侧栏「专业版」一致。扩展相关蓝图与说明由各扩展包自行提供。
        </p>
        <p v-else-if="ctx.modsDisabledByServer" style="margin: 0; color: #6b7280;">
          后端已关闭扩展（XCAGI_DISABLE_MODS）：仅<strong>固定六类</strong>工作流；副窗与「流程可视化」不展示扩展向内容。
        </p>
        <p v-else-if="!ctx.isModsListLoaded" style="margin: 0; color: #6b7280;">
          正在与后端同步扩展列表；当前说明以<strong>固定六类</strong>为主。若环境中存在带工作流员工的扩展，同步完成后本页描述会与副窗一致更新。
        </p>
        <p v-else-if="modWorkflowEmployeesActive" style="margin: 0; color: #6b7280;">
          在此查看与管理副窗中的<strong>固定六类</strong>与当前 manifest 已声明的<strong>扩展工作流员工</strong>；开关样式与侧栏「专业版」一致。各扩展的蓝图、API 与专有步骤以扩展包文档为准。
        </p>
        <p v-else style="margin: 0; color: #6b7280;">
          当前副窗仅<strong>固定六类</strong>（未加载带工作流员工的扩展，或扩展未声明 workflow_employees）。扩展蓝图与对接说明由各扩展包维护。
        </p>

        <p v-if="modWorkflowEmployeesActive" style="margin: 12px 0 0; color: #6b7280;">
          「流程可视化」以图解说明固定六类与已出现的扩展工作流执行逻辑；扩展专有细节仍以各扩展为准。
        </p>
        <p v-else style="margin: 12px 0 0; color: #6b7280;">
          「流程可视化」以图解说明<strong>固定六类</strong>执行逻辑与任务面板对应关系；扩展相关内容仅在扩展实际启用工作流员工后才会在总览中体现。
        </p>

        <div style="margin-top: 12px;">
          <router-link
            :to="{ name: 'workflow-visualization' }"
            class="btn btn-primary"
            :title="workflowPanoramaTitle"
          >流程可视化</router-link>
        </div>
        <p v-if="!ctx.clientModsUiOff && !ctx.modsDisabledByServer" style="margin: 12px 0 0; color: #6b7280;">
          「微信联系人」侧栏入口与副窗「微信触点管家」工作流员工由可选扩展 Mod<strong> wechat-contacts-ai-employee</strong>（微信触点 AI 员工）提供；源码见公司仓库 <code>mods/wechat-contacts-ai-employee/</code>，可打包上架 MODstore。
        </p>
      </div>

      <div class="card" style="margin-bottom: 12px;">
        <h3 style="margin: 0 0 8px;">员工空间</h3>
        <p style="margin: 0; color: #6b7280;">
          像素风入口与工位实况展示（与副窗「一键托管」工作流员工、智能对话任务快照同步）。不在本页直接展开工位网格；进入独立页查看。
        </p>
        <div style="margin-top: 12px;">
          <router-link
            :to="{ name: 'workflow-employee-space' }"
            class="btn btn-primary"
            :title="employeeSpaceTitle"
          >进入员工空间</router-link>
        </div>
      </div>

      <div class="card card--entry" style="margin-bottom: 12px;">
        <h3 style="margin: 0 0 8px;">六部门编制图</h3>
        <p style="margin: 0; color: #6b7280;">
          按<strong>六线六部门</strong>（O-A 获客、O-B 伙伴、P-W 网站、P-S 软件等）分组展示 52 岗 AI 员工，支持<strong>员工大会汇报</strong>与任务下达。默认打开「六部门」视图（非 MODstore 中心依赖图）。
        </p>
        <div class="card-entry-actions">
          <router-link
            :to="dutyRosterGraphLocation"
            class="btn btn-primary"
            title="进入六部门编制图"
          >进入六部门编制图</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowModsRuntimeContext } from '@/composables/useWorkflowModsRuntimeContext'

const { ctx, modWorkflowEmployeesActive } = useWorkflowModsRuntimeContext()

const workflowPanoramaTitle = computed(() =>
  modWorkflowEmployeesActive.value
    ? '查看固定六类与扩展工作流的执行逻辑与过程'
    : '查看固定六类工作流的执行逻辑与过程'
)

const employeeSpaceTitle = computed(() =>
  modWorkflowEmployeesActive.value
    ? '打开员工空间：像素入口与扩展工作流工位实况'
    : '打开员工空间：像素入口与固定六类工位实况'
)

const dutyRosterGraphLocation = { name: 'duty-roster-graph' as const, query: { view: 'department' } }
</script>

<style scoped>
.card-entry-actions {
  margin-top: 12px;
  padding-top: 4px;
}
</style>
