<template>
  <div class="aiopen-shell">
    <header class="aiopen-header">
      <button class="aiopen-back" type="button" @click="$emit('back')">← 返回</button>
      <div class="aiopen-header-brand">AIOPEN 开放智控</div>
      <span class="aiopen-header-spacer" aria-hidden="true"></span>
    </header>

    <div class="aiopen-scroll">
    <div class="aiopen-stage">

    <div class="aiopen-hero" :class="`aiopen-hero--${readyStatus}`">
      <div class="aiopen-hero-top">
        <div class="aiopen-hero-badge">AI 工具 · 开放智控</div>
        <div class="aiopen-hero-icon-wrap">
          <div class="aiopen-hero-icon" aria-hidden="true">
            <svg v-if="readyStatus === 'ready'" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 13l4 4L19 7"/></svg>
            <svg v-else viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="4"/><path d="M8 8l2 2M14 14l2 2M14 8l2-2M8 14l2 2"/></svg>
          </div>
          <span v-if="readyStatus === 'ready'" class="aiopen-live-dot"></span>
        </div>
        <h1 class="aiopen-hero-title">AIOPEN</h1>
        <p class="aiopen-hero-tagline">让外部 AI 像助手一样，帮你操作本软件</p>
      </div>

      <ul class="aiopen-features">
        <li v-for="f in featureIntro" :key="f.title">
          <span class="aiopen-feature-icon" aria-hidden="true">{{ f.icon }}</span>
          <div>
            <strong>{{ f.title }}</strong>
            <span>{{ f.desc }}</span>
          </div>
        </li>
      </ul>

      <div class="aiopen-flow">
        <span v-for="(step, i) in flowSteps" :key="step" class="aiopen-flow-item" :class="{ done: flowDone[i] }">
          <em>{{ i + 1 }}</em>{{ step }}
        </span>
      </div>

      <p class="aiopen-hero-status">{{ statusText }}</p>
      <p v-if="mcpHealthText" class="aiopen-mcp-health" :class="{ ok: mcpHealthy }">{{ mcpHealthText }}</p>
      <p v-if="panelError" class="aiopen-hero-warn">{{ panelError }}</p>

      <button
        class="aiopen-primary-btn"
        type="button"
        :disabled="setupRunning || shutdownRunning"
        @click="handlePrimaryAction"
      >
        {{ setupRunning ? '开启中…' : shutdownRunning ? '关闭中…' : primaryBtnLabel }}
      </button>

      <div class="aiopen-oneline">
        <p class="aiopen-oneline-label">发给其他 AI 助手</p>
        <p class="aiopen-oneline-preview">{{ oneLinerPreview }}</p>
        <div class="aiopen-oneline-actions">
          <button class="aiopen-oneline-btn" type="button" @click="copyOneLiner">
            复制一句话
          </button>
          <button class="aiopen-oneline-btn aiopen-oneline-btn--ghost" type="button" @click="copyAiAssistantPrompt">
            完整配置
          </button>
        </div>
      </div>

      <div class="aiopen-client-section">
        <p class="aiopen-client-title">选择 AI 软件接入 <span class="aiopen-client-sub">可同时配置多个</span></p>
        <div class="aiopen-client-grid">
          <button
            v-for="client in aiClients"
            :key="client.id"
            type="button"
            class="aiopen-client-btn"
            :class="{ done: installedClientIds.includes(client.id) }"
            @click="handleClientClick(client)"
          >
            <span class="aiopen-client-icon" aria-hidden="true">{{ client.icon }}</span>
            <span class="aiopen-client-name">{{ client.name }}</span>
            <span class="aiopen-client-action">{{ clientActionLabel(client) }}</span>
          </button>
        </div>
      </div>

      <details v-if="friendlyTools.length" class="aiopen-tools-preview">
        <summary>MCP 工具 · {{ friendlyTools.length }} 个</summary>
        <ul>
          <li v-for="tool in friendlyTools" :key="tool.name">
            <strong>{{ tool.label }}</strong>
            <span>{{ tool.desc }}</span>
          </li>
        </ul>
      </details>

      <p v-if="accessResult" class="aiopen-toast">{{ accessResult }}</p>
    </div>

    <details class="aiopen-more">
      <summary>更多设置</summary>
      <div class="aiopen-more-body">
        <button class="aiopen-link-btn" type="button" @click="loadPanel">刷新状态</button>
        <p v-if="!panelAvailable" class="aiopen-offline-hint">离线模式：可先配置 AI 软件；开启远程操控需后端在线</p>

        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="remoteControlEnabled" @change="toggleRemoteControl($event)">
          <span>允许 AI 远程操控</span>
        </label>
        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="cursorEnabled" @change="toggleScreenSession($event)">
          <span>本页待命{{ cursorConnected ? ' · 已连接' : '' }}</span>
        </label>

        <div class="aiopen-more-actions">
          <button class="btn btn-secondary btn-sm" type="button" @click="copyClientConfig(selectedClientId)">复制 MCP JSON</button>
          <button class="btn btn-secondary btn-sm" type="button" @click="copyGuideUrl">复制说明链接</button>
          <button v-if="!activeKey" class="btn btn-secondary btn-sm" type="button" @click="createKey">获取口令</button>
        </div>

        <div class="aiopen-client-picker">
          <span class="aiopen-client-picker-label">配置预览</span>
          <select v-model="selectedClientId" class="aiopen-select aiopen-client-select">
            <option v-for="client in aiClients" :key="client.id" :value="client.id">{{ client.name }}</option>
          </select>
          <p class="aiopen-client-picker-hint">{{ selectedClient?.configPath }} · {{ selectedClient?.hint }}</p>
        </div>

        <details class="aiopen-nested">
          <summary>开发者 / 高级</summary>
          <div class="aiopen-advanced-body">
            <pre class="aiopen-pre">{{ selectedClientConfigSnippet }}</pre>
            <div class="aiopen-endpoint-row">
              <code class="aiopen-endpoint-code">{{ mcpUrl }}</code>
              <button class="btn btn-secondary btn-sm" type="button" @click="copyText(mcpUrl)">MCP</button>
            </div>
            <div class="aiopen-tools">
              <div v-for="tool in friendlyTools" :key="tool.name" class="aiopen-tool-item">
                <span>{{ tool.label }}</span>
                <span>{{ tool.desc }}</span>
              </div>
            </div>
            <div class="aiopen-route-list">
              <div class="aiopen-row" style="margin-bottom:8px;gap:8px;flex-wrap:wrap;">
                <button class="btn btn-secondary btn-sm" type="button" :disabled="seedRunning" @click="seedFullWhitelist">
                  {{ seedRunning ? '写入中…' : '开启全业务白名单' }}
                </button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="loopRunning" @click="verifyCapabilityLoop">
                  {{ loopRunning ? '检测中…' : '验证全调用闭环' }}
                </button>
              </div>
              <p v-if="loopResultText" class="aiopen-offline-hint">{{ loopResultText }}</p>
              <label v-for="route in routes" :key="route.path" class="aiopen-route-item">
                <input type="checkbox" :checked="route.enabled" @change="toggleWhitelist(route.path, $event)">
                <code>{{ route.path }}</code>
              </label>
            </div>
            <label class="aiopen-switch-row">
              <input type="checkbox" :checked="wechatOpen" @change="toggleWechat($event)">
              <span>微信开放权限</span>
            </label>
            <div class="aiopen-row">
              <input v-model="openclawBase" class="aiopen-input" placeholder="OpenClaw 地址">
              <button class="btn btn-secondary btn-sm" type="button" @click="saveOpenclawBase">保存</button>
            </div>
            <div class="aiopen-row">
              <input v-model="openclawMessage" class="aiopen-input" placeholder="测试消息">
              <button class="btn btn-primary btn-sm" type="button" :disabled="openclawSending" @click="sendToOpenclaw">发送</button>
            </div>
            <div class="aiopen-result">{{ openclawResult }}</div>
            <div class="aiopen-row aiopen-row-auth">
              <select v-model="openclawWsAuthMode" class="aiopen-select">
                <option value="token">token</option>
                <option value="password">password</option>
              </select>
              <input v-model="openclawGatewayToken" class="aiopen-input" placeholder="Token/密码">
            </div>
            <div class="aiopen-row">
              <input v-model="openclawWsUrl" class="aiopen-input" placeholder="ws://localhost:28789/ws">
              <button class="btn btn-secondary btn-sm" type="button" :disabled="wsConnected || wsConnecting" @click="connectOpenclawWs">WS</button>
            </div>
            <div class="aiopen-result">{{ wsStatusText }}</div>
          </div>
        </details>
      </div>
    </details>
    </div>
    </div>
  </div>
</template>

<script setup>
// 入口 façade：状态/行为拆分至 ./aiopen-panel/，此处仅装配（对外 vm 表面与拆分前一致）
import { onBeforeUnmount, onMounted } from 'vue'
import { useAiOpenCursor } from '@/composables/useAiOpenCursor'
import { useAiOpenPanelState } from './aiopen-panel/useAiOpenPanelState'
import { useAiOpenPanelActions } from './aiopen-panel/useAiOpenPanelActions'
import { useAiOpenOpenclaw } from './aiopen-panel/useAiOpenOpenclaw'

defineEmits(['back'])

const {
  enabled: cursorEnabled,
  connected: cursorConnected,
  setEnabled: setCursorEnabled,
} = useAiOpenCursor()

const state = useAiOpenPanelState({ cursorEnabled, cursorConnected })
const actions = useAiOpenPanelActions(state, { setCursorEnabled })
const openclaw = useAiOpenOpenclaw(state)

// 顶层解耦保留全部同名绑定：模板渲染与测试 vm 访问面与拆分前一致
const {
  wechatOpen,
  routes,
  remoteControlEnabled,
  keys,
  newKey,
  accessResult,
  panelError,
  panelAvailable,
  manifestTools,
  setupRunning,
  shutdownRunning,
  seedRunning,
  loopRunning,
  loopResultText,
  installBundle,
  mcpHealthy,
  mcpHealthText,
  installedClientIds,
  selectedClientId,
  stdioScriptPath,
  oneLinerCopied,
  openclawBase,
  openclawMessage,
  openclawSending,
  openclawResult,
  mcpUrl,
  guideUrl,
  activeKey,
  hasConnectConfig,
  aiAssistantPrompt,
  oneLinerText,
  oneLinerPreview,
  readyStatus,
  aiOpenActive,
  featureIntro,
  flowSteps,
  flowDone,
  statusText,
  primaryBtnLabel,
  friendlyTools,
  aiClients,
  selectedClient,
  selectedClientConfigSnippet,
} = state

const {
  refreshInstalledClients,
  clientActionLabel,
  handleClientClick,
  copyClientConfig,
  formatPanelError,
  loadPanel,
  copyText,
  copyOneLiner,
  copyAiAssistantPrompt,
  copyCursorConfig,
  copyGuideUrl,
  copyGuidePrompt,
  createKey,
  handlePrimaryAction,
  toggleWhitelist,
  seedFullWhitelist,
  verifyCapabilityLoop,
  toggleWechat,
  toggleRemoteControl,
  toggleScreenSession,
} = actions

const {
  openclawWsUrl,
  openclawWsAuthMode,
  openclawGatewayToken,
  wsConnected,
  wsConnecting,
  wsStatusText,
  connectOpenclawWs,
  saveOpenclawBase,
  sendToOpenclaw,
  closeOpenclawWs,
} = openclaw

onMounted(() => {
  try { oneLinerCopied.value = localStorage.getItem('aiopen_oneliner_copied') === '1' } catch { /* ignore */ }
  refreshInstalledClients()
  loadPanel()
})
onBeforeUnmount(() => { closeOpenclawWs() })
</script>

<style scoped src="./aiopen-panel/aiopen-panel.css"></style>
