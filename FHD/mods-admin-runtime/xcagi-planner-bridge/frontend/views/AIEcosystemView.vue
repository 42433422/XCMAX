<template>
  <div class="chat-view page-view active" id="view-ai-ecosystem">
    <div v-if="!inAnalyzer" class="ecosystem-home">
      <div class="ecosystem-home-title">AI生态应用</div>
      <div class="launcher-grid">
        <button class="app-launcher" type="button" @click="enterAnalyzer('kitten')">
          <span class="app-launcher-icon" aria-hidden="true">🐱</span>
          <span class="app-launcher-name">智慧分析</span>
          <span class="app-launcher-desc">上传表格、对话分析、生成丰富图表，并按需导出报告</span>
        </button>
        <button class="app-launcher app-launcher--aiopen" type="button" @click="enterAnalyzer('aiopen')">
          <span class="app-launcher-icon app-launcher-icon--aiopen" aria-hidden="true">
            <AiOpenLauncherIcon />
          </span>
          <span class="app-launcher-name">AIOPEN 开放智控</span>
          <span class="app-launcher-desc">企业级 AI Agent 接入平台，基于 MCP/API 标准协议，提供远程 UI 操控与白名单业务接口开放</span>
        </button>
        <button class="app-launcher app-launcher--production" type="button" @click="goShellPage('brain')">
          <span class="app-launcher-icon app-launcher-icon--production" aria-hidden="true">
            <ProductionEmployeeLauncherIcon />
          </span>
          <span class="app-launcher-name">生产员工</span>
          <span class="app-launcher-desc">部署与调度生产 AI 员工，编排任务流、监控工位运行与自动化交付</span>
        </button>
        <button class="app-launcher app-launcher--modstore" type="button" @click="goShellPage('mod-store')">
          <span class="app-launcher-icon app-launcher-icon--modstore" aria-hidden="true">
            <ModStoreLauncherIcon />
          </span>
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
import AiOpenLauncherIcon from '@/components/aiopen/AiOpenLauncherIcon.vue'
import ProductionEmployeeLauncherIcon from '@/components/workflow/ProductionEmployeeLauncherIcon.vue'
import ModStoreLauncherIcon from '@/components/modStore/ModStoreLauncherIcon.vue'

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
.app-launcher-icon--aiopen {
  background: linear-gradient(145deg, #3b82f6 0%, #1d4ed8 100%);
  box-shadow:
    0 8px 20px rgba(37, 99, 235, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.app-launcher--aiopen:hover .app-launcher-icon--aiopen {
  box-shadow:
    0 10px 24px rgba(37, 99, 235, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
}
.app-launcher-icon--production {
  background: linear-gradient(145deg, #f59e0b 0%, #ea580c 100%);
  box-shadow:
    0 8px 20px rgba(234, 88, 12, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.app-launcher--production:hover .app-launcher-icon--production {
  box-shadow:
    0 10px 24px rgba(234, 88, 12, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
}
.app-launcher-icon--modstore {
  background: linear-gradient(145deg, #8b5cf6 0%, #6d28d9 100%);
  box-shadow:
    0 8px 20px rgba(109, 40, 217, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.app-launcher--modstore:hover .app-launcher-icon--modstore {
  box-shadow:
    0 10px 24px rgba(109, 40, 217, 0.42),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
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
