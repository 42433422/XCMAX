<template>
  <div class="chat-view page-view active" id="view-ai-ecosystem">
    <div v-if="!inAnalyzer" class="ecosystem-home">
      <div class="ecosystem-home-title">AI生态应用</div>
      <div class="launcher-grid">
        <button class="app-launcher" type="button" @click="enterAnalyzer('kitten')">
          <span class="app-launcher-icon" aria-hidden="true">🐱</span>
          <span class="app-launcher-name">小猫分析</span>
          <span class="app-launcher-desc">上传表格、对话分析、生成丰富图表，并按需导出报告</span>
        </button>
        <button class="app-launcher" type="button" @click="enterAnalyzer('aiopen')">
          <span class="app-launcher-icon" aria-hidden="true">🤖</span>
          <span class="app-launcher-name">AIOPEN 开放智控</span>
          <span class="app-launcher-desc">我是 AI 的工具 — MCP / API 开放平台与虚拟光标操控</span>
        </button>
        <button class="app-launcher" type="button" @click="goShellPage('brain')">
          <span class="app-launcher-icon" aria-hidden="true">🧠</span>
          <span class="app-launcher-name">AI智脑集成</span>
          <span class="app-launcher-desc">Agent 控制台，同源 Planner 与 unified_chat 联调</span>
        </button>
        <button class="app-launcher" type="button" @click="goShellPage('mod-store')">
          <span class="app-launcher-icon" aria-hidden="true">🧩</span>
          <span class="app-launcher-name">员工商店</span>
          <span class="app-launcher-desc">MOD 扩展浏览、安装与本机 .xcmod 目录</span>
        </button>
      </div>
    </div>

    <KittenAnalyzerView v-else-if="activeApp === 'kitten'" @back="exitAnalyzer" />

    <AIOpenPanel v-else @back="exitAnalyzer" />
  </div>
</template>

<script setup>
import { ref, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { resolvePlannerPageRedirectForRouteName } from '@/utils/plannerPagePaths'

const router = useRouter()

const KittenAnalyzerView = defineAsyncComponent(() => import('@/components/kitten/KittenAnalyzerView.vue'))
const AIOpenPanel = defineAsyncComponent(() => import('@/components/aiopen/AIOpenPanel.vue'))

const inAnalyzer = ref(false)
const activeApp = ref('kitten')

const goShellPage = (name) => {
  const modPath = resolvePlannerPageRedirectForRouteName(name)
  if (modPath) {
    router.push(modPath)
    return
  }
  router.push({ name })
}

const enterAnalyzer = (appKey = 'kitten') => {
  // 'qclaw' 为旧入口键，等价于 'aiopen'（Qclaw龙虾生态已升级为 AIOPEN）
  activeApp.value = appKey === 'qclaw' ? 'aiopen' : appKey
  inAnalyzer.value = true
}

const exitAnalyzer = () => {
  inAnalyzer.value = false
}
</script>

<style scoped>
.chat-view { height: 100%; display: flex; flex-direction: column; }
.ecosystem-home {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: #f8fafc;
}
.ecosystem-home-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}
.launcher-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 240px));
  gap: 18px;
}
.app-launcher {
  width: 240px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  border-radius: 16px;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(30, 64, 175, 0.08);
}
.app-launcher:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 28px rgba(30, 64, 175, 0.12);
}
.app-launcher-icon {
  width: 88px;
  height: 88px;
  border-radius: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42px;
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
}
.app-launcher-name {
  font-size: 18px;
  font-weight: 700;
  color: #1e3a8a;
}
.app-launcher-desc {
  font-size: 13px;
  color: #64748b;
}
</style>
