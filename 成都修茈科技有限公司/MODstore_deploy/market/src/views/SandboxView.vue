<template>
  <div class="sandbox-page">
    <div class="sandbox-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-label">自动匹配</span>
        <input v-model="hostUrl" class="toolbar-input" placeholder="可留空；将扫本机常见 API 端口" @keydown.enter="discoverAndConnect" />
        <button class="btn btn-connect" :disabled="connecting" @click="discoverAndConnect">
          {{ connecting ? '扫端口中…' : '重新扫描' }}
        </button>
        <span v-if="statusText" class="status-chip" :class="statusClass">{{ statusText }}</span>
        <span v-if="connectError" class="status-chip status-err" role="alert">{{ connectError }}</span>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-action" :disabled="!connected || pushing || !effectiveModId" @click="pushAndTest">
          {{ pushing ? '推送中...' : '推送当前 Mod 并测试' }}
        </button>
        <button class="btn btn-action" :disabled="!connected" @click="openHostInNewTab">打开宿主测试页</button>
      </div>
    </div>

    <div v-if="connected" class="sandbox-helper">
      <div class="helper-copy">
        <strong>沙箱已匹配</strong>
        <p>在独立页面中打开宿主，登录后继续测试已推送的 Mod。</p>
        <p v-if="!effectiveModId">输入一个测试 Mod ID 后可推送到宿主。</p>
        <p v-if="pushMessage" class="helper-message">{{ pushMessage }}</p>
      </div>
      <div class="helper-actions">
        <input
          v-model="manualModId"
          class="toolbar-input helper-input"
          placeholder="测试 Mod ID，例如 example-mod"
          @keydown.enter="pushAndTest"
        />
        <button class="btn btn-action" :disabled="pushing || !effectiveModId" @click="pushAndTest">
          {{ pushing ? '推送中...' : '推送测试 Mod' }}
        </button>
        <button class="btn" :disabled="!hostUrl" @click="openHostInNewTab">打开宿主测试页</button>
      </div>
    </div>

    <div v-if="!connected" class="sandbox-placeholder">
      <div class="placeholder-icon">
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      </div>
      <p class="placeholder-text">正在本机与局域网自动扫描常见 API 端口并匹配 XCAGI / FHD</p>
      <p class="placeholder-hint">
        依次探测多端口（如 5000–5002、5173–5176、8000 等）；命中后写入上方；也可手动填根地址后回车或点「重新扫描」
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：宿主发现/连接/推送逻辑在 ./sandbox/，样式在 ./sandbox/sandboxView.css。
import { useSandboxHost } from './sandbox/useSandboxHost'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  hostUrl, connected, connecting, connectError, probeProgress, pushing,
  hostInfo, manualModId, pushMessage,
  effectiveModId, statusText, statusClass, hostPageUrl,
  normalizeHostOrigin, isLoopbackHost, isLoopbackOrigin,
  shouldProbeFromBrowser, buildDiscoveryCandidates,
  discoverAndConnect, pushAndTest, openHostInNewTab, shouldAutoPush,
} = useSandboxHost()
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./sandbox/sandboxView.css"></style>
