<template>
  <transition name="fade">
    <div v-if="visible" class="tts-banner" :class="{ 'is-downloading': downloading }">
      <div class="tts-banner-main">
        <div class="tts-banner-icon" aria-hidden="true">
          <span v-if="!downloading">🔊</span>
          <span v-else>⏬</span>
        </div>
        <div class="tts-banner-text">
          <template v-if="downloading">
            <div class="tts-banner-title">正在下载离线语音包…</div>
            <div class="tts-banner-sub">
              首次约 60MB，已完成 {{ Math.round(status.offlineProgress * 100) }}%，之后无需联网
            </div>
            <div class="tts-progress">
              <div class="tts-progress-bar" :style="{ width: `${Math.round(status.offlineProgress * 100)}%` }"></div>
            </div>
          </template>
          <template v-else-if="status.effectiveEngine === 'offline' && status.offlineReady">
            <div class="tts-banner-title">已启用离线语音（Xenova/MMS-TTS 中文）</div>
            <div class="tts-banner-sub">完全本地合成，无需联网。想换系统云希？</div>
          </template>
          <template v-else-if="status.effectiveEngine === 'online'">
            <div class="tts-banner-title">已启用在线语音（Microsoft Edge TTS）</div>
            <div class="tts-banner-sub">
              经本机后端合成，需联网；当前音色 <code>{{ status.onlineVoiceId }}</code>。
              失败时朗读会自动回退到系统语音。
            </div>
          </template>
          <template v-else-if="status.yunxiAvailable">
            <div class="tts-banner-title">已启用系统语音：{{ status.systemVoice }}</div>
            <div class="tts-banner-sub">当前正在使用 Windows 云希 / 晓晓 神经网络语音。</div>
          </template>
          <template v-else-if="status.neuralAvailable">
            <div class="tts-banner-title">已启用系统神经网络语音：{{ status.systemVoice }}</div>
            <div class="tts-banner-sub">若想切换到云希(Yunxi)，可安装该语音包后点击"使用 Yunxi"。</div>
          </template>
          <template v-else>
            <div class="tts-banner-title">没检测到云希/晓晓 神经网络语音</div>
            <div class="tts-banner-sub">
              当前 TTS：<strong>{{ status.systemVoice || '浏览器默认（可能是英文）' }}</strong>。
              可一键使用<strong>在线神经网络</strong>（Edge），或安装系统云希 / 下载离线包。
            </div>
          </template>
        </div>
      </div>
      <div class="tts-banner-actions">
        <button
          v-if="!downloading && !status.yunxiAvailable"
          class="tts-btn tts-btn-primary"
          :disabled="installing"
          @click="installWindowsVoice"
        >
          {{ installing ? '等待管理员授权…' : '一键安装系统云希' }}
        </button>
        <button
          v-if="!downloading && status.engineMode !== 'online'"
          class="tts-btn"
          :class="{ 'tts-btn-primary': status.yunxiAvailable === false && !status.neuralAvailable && status.effectiveEngine !== 'offline' }"
          @click="useOnline"
        >
          在线语音 (Edge)
        </button>
        <button
          v-if="!downloading && !status.offlineReady"
          class="tts-btn"
          :class="{ 'tts-btn-primary': status.yunxiAvailable === false && !status.neuralAvailable }"
          @click="downloadOffline"
        >
          下载离线包 (~60MB)
        </button>
        <button v-if="!downloading && status.offlineReady && status.effectiveEngine === 'system'" class="tts-btn" @click="useOffline">
          切到离线语音
        </button>
        <button v-if="!downloading && status.effectiveEngine === 'online' && status.offlineReady" class="tts-btn" @click="useOffline">
          切到离线语音
        </button>
        <button v-if="!downloading && status.effectiveEngine === 'offline' && status.yunxiAvailable" class="tts-btn" @click="useSystem">
          切到系统云希
        </button>
        <button v-if="!downloading && status.effectiveEngine === 'online'" class="tts-btn" @click="useSystem">
          切到系统语音
        </button>
        <button v-if="!downloading" class="tts-btn tts-btn-ghost" @click="close">不再提示</button>
      </div>
      <el-dialog v-model="psDialog" title="安装 Windows 云希语音" width="520" append-to-body>
        <div class="tts-dialog-body">
          <p>两种方式任选其一：</p>
          <ol>
            <li>
              打开 <code>Windows 设置 → 时间和语言 → 语音 → 管理语音 → 添加语音</code>，
              搜索"中文（简体）Microsoft 云希"。已点"打开设置"按钮自动跳转。
            </li>
            <li>
              以 <strong>管理员身份</strong>打开 PowerShell，执行：
              <pre class="tts-ps-code">{{ psCommand }}</pre>
              <button class="tts-btn tts-btn-primary" @click="copyPs">复制命令</button>
            </li>
          </ol>
          <p class="tts-tip">
            安装完成后重启浏览器（推荐 Microsoft Edge，对 Windows 神经网络语音兼容最好），
            再回到这里就能看到 Yunxi 生效。
          </p>
        </div>
      </el-dialog>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { asRecord, asArray, asString } from '@/utils/typeGuards'
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ElMessage, ElDialog } from 'element-plus'
import { api, ApiError } from '@/api'
import {
  getTtsStatus,
  onTtsStatusChange,
  ensureVoicesLoaded,
  setEngineMode,
  dismissBanner,
  isBannerDismissed,
  startOfflineDownload,
  type TtsStatus,
} from '@/utils/tts'

const status = ref<TtsStatus>(getTtsStatus())
const downloading = computed(() => status.value.offlineLoading)
const psDialog = ref(false)
const installing = ref(false)

const psCommand = `Get-WindowsCapability -Online | Where-Object Name -like "Language.Speech~*zh-CN*" | Add-WindowsCapability -Online`

let unsubscribe: (() => void) | null = null

function refresh() {
  status.value = getTtsStatus()
}

onMounted(async () => {
  unsubscribe = onTtsStatusChange(refresh)
  await ensureVoicesLoaded()
  refresh()
})

onBeforeUnmount(() => {
  unsubscribe?.()
})

const visible = computed(() => {
  if (isBannerDismissed()) return false
  if (downloading.value) return true
  // 用户显式选了在线引擎时保留顶栏，便于切回系统/离线
  if (status.value.engineMode === 'online') return true
  // 已有云希 → 低调不打扰
  if (status.value.yunxiAvailable) return false
  // 系统自带 Huihui / Yaoyao / Kangkang 等中文本地语音也当作"够用"，不再弹提示。
  // 云希/晓晓属于 Win11 22H2+ 的自然语音，没有也不算故障。
  if (status.value.anyChineseLocal) return false
  return true
})

async function installWindowsVoice() {
  if (installing.value) return
  installing.value = true
  const hint = ElMessage.info({ message: '正在申请管理员权限以安装中文语音包…', duration: 0 })
  try {
    // 优先走本机后端一键提权安装：UAC 通过后由独立 PowerShell 窗口显示进度
    const resp = await api.post<{ success: boolean; message?: string; code?: number }>(
      '/api/tts/install-system-voice',
      {},
    )
    hint.close()
    if (resp && resp.success) {
      ElMessage.success(resp.message || '已发起安装，请在 UAC 对话框点"是"并等待完成')
      return
    }
    // 失败时回退到"打开设置 + 手动命令"旧流程
    ElMessage.warning(resp?.message || '自动安装未成功，已为你打开手动安装说明')
    try { window.location.href = 'ms-settings:speech' } catch { /* ignore */ }
    psDialog.value = true
  } catch (e: unknown) {
    hint.close()
    // 后端返回 4xx/5xx 会走这里；ApiError.data 里带着后端的中文说明
    const serverMsg = e instanceof ApiError ? asString(asRecord(e.data).message) : ''
    if (serverMsg) {
      ElMessage.warning(serverMsg)
    } else {
      const msg = e instanceof Error ? e.message : String(e)
      ElMessage.warning(`自动安装不可用（${msg}），已切换到手动安装模式`)
    }
    try { window.location.href = 'ms-settings:speech' } catch { /* ignore */ }
    psDialog.value = true
  } finally {
    installing.value = false
  }
}

async function copyPs() {
  try {
    await navigator.clipboard.writeText(psCommand)
    ElMessage.success('已复制命令，请在管理员 PowerShell 中粘贴执行')
  } catch {
    ElMessage.warning('复制失败，请手动选中命令复制')
  }
}

async function downloadOffline() {
  try {
    ElMessage.info('正在下载离线语音包，首次约 60MB…')
    await startOfflineDownload()
    setEngineMode('offline')
    ElMessage.success('离线语音包就绪，已切换到本地合成')
    refresh()
  } catch (e: unknown) {
    ElMessage.error(`下载失败：${e instanceof Error ? e.message : String(e)}`)
    refresh()
  }
}

function useOffline() {
  setEngineMode('offline')
  ElMessage.success('已切换到离线语音')
  refresh()
}

function useOnline() {
  setEngineMode('online')
  ElMessage.success('已切换到在线语音（Edge TTS），需联网；失败时自动用系统语音朗读')
  refresh()
}

function useSystem() {
  setEngineMode('system')
  ElMessage.success('已切换到系统语音')
  refresh()
}

function close() {
  dismissBanner()
  refresh()
}
</script>

<style scoped>
.tts-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #eef5ff 0%, #f5f8ff 100%);
  border: 1px solid #c7dbff;
  border-radius: 8px;
  margin: 8px 12px;
  font-size: 13px;
  color: #2b3a55;
  flex-wrap: wrap;
}
.tts-banner.is-downloading {
  background: linear-gradient(135deg, #fff7e6 0%, #fffaef 100%);
  border-color: #ffd591;
}
.tts-banner-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1 1 260px;
  min-width: 0;
}
.tts-banner-icon {
  font-size: 20px;
  flex-shrink: 0;
}
.tts-banner-text {
  min-width: 0;
}
.tts-banner-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tts-banner-sub {
  margin-top: 2px;
  color: #5a6b89;
  font-size: 12px;
  line-height: 1.45;
}
.tts-progress {
  margin-top: 6px;
  width: 100%;
  height: 4px;
  background: #e8eef7;
  border-radius: 2px;
  overflow: hidden;
}
.tts-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #4a90e2, #2d7bd6);
  transition: width 0.3s ease;
}
.tts-banner-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.tts-btn {
  padding: 5px 12px;
  border: 1px solid #c7dbff;
  border-radius: 6px;
  background: #fff;
  color: #2b3a55;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.tts-btn:hover {
  background: #f0f6ff;
  border-color: #4a90e2;
}
.tts-btn-primary {
  background: #2d7bd6;
  border-color: #2d7bd6;
  color: #fff;
}
.tts-btn-primary:hover {
  background: #1f6bc5;
  border-color: #1f6bc5;
  color: #fff;
}
.tts-btn-ghost {
  background: transparent;
  border-color: transparent;
  color: #7b8aa5;
}
.tts-btn-ghost:hover {
  background: #f0f2f5;
  border-color: #f0f2f5;
}
.tts-dialog-body ol { padding-left: 20px; }
.tts-dialog-body li { margin-bottom: 10px; line-height: 1.6; }
.tts-ps-code {
  margin: 8px 0;
  padding: 8px 10px;
  background: #1e1e1e;
  color: #e6e6e6;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.tts-tip {
  margin-top: 12px;
  color: #7b8aa5;
  font-size: 12px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
