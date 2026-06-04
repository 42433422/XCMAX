<template>
  <div class="chat-view page-view active" id="view-ai-ecosystem">
    <div v-if="!inAnalyzer" class="ecosystem-home">
      <div class="ecosystem-home-title">AI生态应用</div>
      <div class="launcher-grid">
        <button class="app-launcher" type="button" @click="enterAnalyzer('kitten')">
          <span class="app-launcher-icon" aria-hidden="true">🐱</span>
          <span class="app-launcher-name">小猫分析</span>
          <span class="app-launcher-desc">上传数据，智能分析并生成图表</span>
        </button>
        <button class="app-launcher" type="button" @click="enterAnalyzer('qclaw')">
          <span class="app-launcher-icon" aria-hidden="true">🦞</span>
          <span class="app-launcher-name">Qclaw龙虾生态</span>
          <span class="app-launcher-desc">龙虾业务数据洞察与经营分析</span>
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

    <template v-else>
      <div class="qclaw-shell">
        <div class="qclaw-header">
          <button class="qclaw-back" type="button" @click="exitAnalyzer">返回应用列表</button>
          <div class="qclaw-title">Qclaw龙虾生态 · 路由调度面板</div>
          <button class="qclaw-refresh" type="button" @click="loadQclawPanel">刷新</button>
        </div>

        <div class="qclaw-grid">
          <section class="qclaw-card">
            <h3>微信开放权限开关</h3>
            <label class="qclaw-switch-row">
              <input type="checkbox" :checked="qclawWechatOpen" @change="toggleQclawWechat($event)">
              <span>{{ qclawWechatOpen ? '已开放' : '已关闭' }}</span>
            </label>
          </section>

          <section class="qclaw-card">
            <h3>路由白名单可视化</h3>
            <div class="qclaw-route-list">
              <label v-for="route in qclawRoutes" :key="route.path" class="qclaw-route-item">
                <input type="checkbox" :checked="route.enabled" @change="toggleWhitelistRoute(route.path, $event)">
                <code>{{ route.path }}</code>
              </label>
            </div>
          </section>

          <section class="qclaw-card">
            <h3>一键测试各路由</h3>
            <div class="qclaw-actions">
              <button class="btn btn-primary btn-sm" type="button" :disabled="qclawTesting" @click="testAllRoutes">
                {{ qclawTesting ? '测试中...' : '测试全部已启用路由' }}
              </button>
            </div>
            <div class="qclaw-test-list">
              <div v-for="item in qclawTestResults" :key="item.path + item.method" class="qclaw-test-item">
                <span class="route-text">{{ item.path }}</span>
                <span :class="item.result === 'ok' ? 'ok' : 'fail'">{{ item.result }} ({{ item.status_code }})</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import KittenAnalyzerView from './KittenAnalyzerView.vue'

const router = useRouter()

const inAnalyzer = ref(false)
const activeApp = ref<'kitten' | 'qclaw' | null>(null)

const qclawWechatOpen = ref(false)
const qclawRoutes = ref<{path: string, enabled: boolean}[]>([])
const qclawTesting = ref(false)
const qclawTestResults = ref<{path: string, method: string, result: string, status_code: number}[]>([])

function enterAnalyzer(app: 'kitten' | 'qclaw') {
  inAnalyzer.value = true
  activeApp.value = app
}

function exitAnalyzer() {
  inAnalyzer.value = false
  activeApp.value = null
}

function goShellPage(page: string) {
  router.push({ name: page })
}

function loadQclawPanel() {
  // 加载Qclaw面板数据
}

function toggleQclawWechat(event: Event) {
  qclawWechatOpen.value = (event.target as HTMLInputElement).checked
}

function toggleWhitelistRoute(path: string, event: Event) {
  const route = qclawRoutes.value.find(r => r.path === path)
  if (route) {
    route.enabled = (event.target as HTMLInputElement).checked
  }
}

function testAllRoutes() {
  qclawTesting.value = true
  // 测试路由逻辑
  setTimeout(() => {
    qclawTesting.value = false
  }, 2000)
}

onMounted(() => {
  // 初始化
})
</script>

<style scoped>
.ecosystem-home {
  padding: 24px;
}

.ecosystem-home-title {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 20px;
  color: #1e293b;
}

.launcher-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.app-launcher {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 24px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
}

.app-launcher:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.15);
}

.app-launcher-icon {
  font-size: 48px;
}

.app-launcher-name {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.app-launcher-desc {
  font-size: 12px;
  color: #64748b;
  text-align: center;
}

.qclaw-shell {
  padding: 20px;
}

.qclaw-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.qclaw-back {
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}

.qclaw-title {
  flex: 1;
  font-size: 18px;
  font-weight: 600;
}

.qclaw-refresh {
  padding: 8px 16px;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  background: #3b82f6;
  color: #fff;
  cursor: pointer;
}

.qclaw-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.qclaw-card {
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.qclaw-card h3 {
  margin: 0 0 12px 0;
  font-size: 16px;
}

.qclaw-switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.qclaw-route-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qclaw-route-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.qclaw-route-item code {
  font-size: 12px;
  color: #475569;
}

.qclaw-actions {
  margin-bottom: 12px;
}

.qclaw-test-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.qclaw-test-item {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
}

.qclaw-test-item .ok {
  color: #10b981;
}

.qclaw-test-item .fail {
  color: #ef4444;
}

.route-text {
  color: #475569;
}
</style>
