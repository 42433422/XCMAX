<template>
  <div class="page-view" id="view-brain">
    <div class="page-content brain-page">
      <div class="page-header brain-agent-header">
        <div class="brain-agent-title-row">
          <h2>生产员工</h2>
          <span class="brain-agent-badge" title="编排与观测控制台">Agent</span>
        </div>
        <p class="muted brain-sub">
          下方为 <strong>Agent 控制台</strong>（对话走 <code class="brain-mono">/api/ai/unified_chat</code>，与主助手同源 Planner）。
          P1 / P2 与口令说明见状态条；架构、OpenAPI、code-editor 联调仍在页内分区。
        </p>
      </div>

      <div class="brain-status-bar" role="region" aria-label="Agent 状态">
        <div class="brain-status-chips">
          <span
            class="brain-chip"
            :class="clientTier === 'p2' ? 'brain-chip--p2' : 'brain-chip--p1'"
          >
            本机意图：{{ clientTier === 'p2' ? 'P2' : 'P1' }}
          </span>
          <span v-if="tierStatusLoading" class="brain-chip brain-chip--muted">同步服务端…</span>
          <template v-else>
            <span
              class="brain-chip brain-chip--muted"
              title="服务端是否配置 FHD_AI_ELEVATED_TOKEN"
            >
              提升口令：{{ tierStatus?.elevated_token_configured ? '已配置' : '未配置' }}
            </span>
            <span v-if="tierStatus?.tier_strict" class="brain-chip brain-chip--warn">严格模式</span>
          </template>
        </div>
        <div class="brain-status-actions">
          <span v-if="openapiLoadedAt" class="brain-status-meta">
            OpenAPI：{{ openapiLoadedAt }}
          </span>
          <router-link to="/settings" class="brain-link-settings">系统设置</router-link>
        </div>
      </div>

      <!-- Claude Code 风格：主对话壳（深色控制台 + 底部输入） -->
      <BnAgentConsole :tm="tm" />

      <div class="brain-layout" :style="brainPaneStyle">
        <div class="brain-main">
          <div class="brain-tabs" role="tablist" aria-label="智脑分区">
            <button
              v-for="t in tabs"
              :key="t.id"
              type="button"
              class="brain-tab"
              :class="{ active: activeTab === t.id }"
              role="tab"
              :aria-selected="activeTab === t.id"
              @click="activeTab = t.id"
            >
              {{ t.label }}
            </button>
          </div>

          <div v-show="activeTab === 'architecture'" class="brain-panel card brain-card">
            <div class="card-header">Level 3 · 页面层（Vue3）</div>
            <p class="muted">
              主交互与路由；下列组件为<strong>规划清单</strong>，待接入独立路由与侧栏入口。
            </p>
            <ul class="brain-list">
              <li><code>CodeEditorView.vue</code> — 主编辑区</li>
              <li><code>DiffViewer.vue</code> — Diff 对比</li>
              <li><code>FileTree.vue</code> — 文件树</li>
            </ul>
            <details class="brain-details">
              <summary>整体关系（示意）</summary>
              <pre class="brain-diagram" aria-label="三层架构示意">{{ architectureDiagram }}</pre>
            </details>
          </div>

          <BnApiPanel :tm="tm" />
          <BnSkillPanel :tm="tm" />
          <PaneResizeHandle
            v-if="isBrainPaneResizable"
            orientation="vertical"
            label="调整观测面板宽度"
            @resize-start="onBrainPaneResizeStart"
            @reset="resetBrainPaneWidth"
          />
        </div>

        <BnObservationAside :tm="tm" />
      </div>
    </div>
  </div>
</template>

<script setup>
// 原超大 SFC 已拆分至 ./brain/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import BnAgentConsole from './brain/BnAgentConsole.vue'
import BnApiPanel from './brain/BnApiPanel.vue'
import BnSkillPanel from './brain/BnSkillPanel.vue'
import BnObservationAside from './brain/BnObservationAside.vue'
import { assembleBrainView } from './brain/assemble'

const tm = assembleBrainView()

const {
  clientTier, tierStatus, tierStatusLoading, openapiLoadedAt,
  brainPaneStyle, tabs, activeTab, architectureDiagram,
  isBrainPaneResizable, onBrainPaneResizeStart, resetBrainPaneWidth,
} = tm
</script>

<style scoped src="./brain/brain.css"></style>
