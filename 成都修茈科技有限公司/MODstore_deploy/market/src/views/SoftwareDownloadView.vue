<template>
  <div
    class="sd"
    :class="{
      'sd--mobile': isMobileViewport,
      'sd--android-ua': isAndroidUa,
      'sd--embedded': isEmbeddedInWorkbench,
    }"
  >
    <header class="sd-topbar">
      <button type="button" class="sd-back" @click="goBack">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        <span>返回</span>
      </button>
    </header>

    <div class="sd-scroll">
      <div class="sd-center">
      <div class="sd-brand">
        <img
          class="sd-brand__logo"
          :src="brandLogoSrc"
          alt="XC 桌面端"
          width="80"
          height="80"
          decoding="async"
        />
      </div>
      <h1 class="sd-title">下载 XC</h1>
      <p class="sd-sub">
        {{
          platformTab === 'android'
            ? 'Android 客户端：AI 对话、能力市场与电脑端协同'
            : '选择适合你的版本，在本地开始 AI 创作与自动化工作流'
        }}
      </p>

      <div class="sd-platform-links" role="tablist" aria-label="选择平台">
        <button
          type="button"
          role="tab"
          class="sd-platform-link"
          :class="{ 'sd-platform-link--active': platformTab === 'desktop' }"
          :aria-selected="platformTab === 'desktop'"
          @click="platformTab = 'desktop'"
        >
          桌面端
        </button>
        <span class="sd-platform-links__sep" aria-hidden="true">|</span>
        <button
          type="button"
          role="tab"
          class="sd-platform-link"
          :class="{ 'sd-platform-link--active': platformTab === 'android' }"
          :aria-selected="platformTab === 'android'"
          @click="platformTab = 'android'"
        >
          Android
        </button>
      </div>

      <div
        v-if="platformTab === 'desktop'"
        class="sd-edition-switch"
        role="tablist"
        aria-label="选择版本"
      >
        <button
          type="button"
          role="tab"
          class="sd-edition-switch__btn"
          :class="{ 'sd-edition-switch__btn--active': edition === 'personal' }"
          :aria-selected="edition === 'personal'"
          @click="edition = 'personal'"
        >
          个人版
        </button>
        <button
          type="button"
          role="tab"
          class="sd-edition-switch__btn sd-edition-switch__btn--enterprise"
          :class="{ 'sd-edition-switch__btn--active': edition === 'enterprise' }"
          :aria-selected="edition === 'enterprise'"
          @click="edition = 'enterprise'"
        >
          企业版
        </button>
      </div>

      <p v-if="releaseContext" class="sd-release-context">{{ releaseContext }}</p>

      <ul class="sd-releases" aria-label="可下载版本">
        <li v-for="row in releaseRows" :key="row.id">
          <button
            type="button"
            class="sd-release-row"
            :class="{ 'sd-release-row--primary': row.primary }"
            @click="download(row.sku, row.platform)"
          >
            <span class="sd-release-row__main">
              <span class="sd-release-row__name">{{ row.label }}</span>
              <span v-if="row.meta" class="sd-release-row__meta">{{ row.meta }}</span>
            </span>
            <span class="sd-release-row__action">{{ row.primary ? '立即下载' : '下载' }}</span>
          </button>
        </li>
      </ul>

      <p class="sd-footnote">
        <template v-if="platformTab === 'desktop'">
          支持 Windows 10+（64 位）、macOS 12+（{{ macArchLabel }}）。
        </template>
        <template v-else>
          下载后请在系统设置中允许「安装未知应用」。
          <a href="https://xiu-ci.com/legal/privacy" target="_blank" rel="noopener noreferrer">隐私政策</a>
          ·
          <a href="https://xiu-ci.com/legal/terms" target="_blank" rel="noopener noreferrer">服务协议</a>
        </template>
      </p>

      <details v-if="platformTab === 'desktop'" class="sd-compare-fold">
        <summary>版本功能对比</summary>
        <div class="sd-compare-fold__grid">
          <article class="sd-edition-card sd-edition-card--personal">
            <h3>个人版</h3>
            <p class="sd-edition-card__price">免费</p>
            <ul>
              <li>基础 AI 对话与创作</li>
              <li>3 个员工配额</li>
              <li>社区模板市场</li>
              <li>5GB 云端存储</li>
            </ul>
          </article>
          <article class="sd-edition-card sd-edition-card--enterprise">
            <h3>企业版 <span class="sd-edition-card__badge">推荐</span></h3>
            <p class="sd-edition-card__price">
              <a :href="ENTERPRISE_MAILTO">联系商务</a>
            </p>
            <ul>
              <li>完整 AI 创作与 ERP 能力</li>
              <li>无限员工配额</li>
              <li>团队协作与权限管理</li>
              <li>私有云 / 本地部署</li>
            </ul>
          </article>
        </div>
      </details>
      </div>
    </div>

    <nav v-if="isMobileViewport" class="sd-dock" aria-label="快捷下载">
      <button
        v-if="platformTab === 'desktop'"
        type="button"
        class="sd-dock__btn"
        @click="download(edition, 'win')"
      >
        <span class="sd-dock__icon"><IconWindows /></span>
        <span>Windows</span>
      </button>
      <button
        v-if="platformTab === 'desktop'"
        type="button"
        class="sd-dock__btn"
        @click="download(edition, 'mac')"
      >
        <span class="sd-dock__icon"><IconApple /></span>
        <span>macOS</span>
      </button>
      <button
        type="button"
        class="sd-dock__btn"
        @click="download(edition, 'android')"
      >
        <span class="sd-dock__icon"><IconAndroid /></span>
        <span>Android</span>
      </button>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DEFAULT_XCAGI_ANDROID_VERSION,
  DEFAULT_XCAGI_DOWNLOAD_VERSION,
  detectMacDownloadArch,
  macDownloadArchLabel,
  normalizeXcagiDownloadBase,
  type XcagiDownloadPlatform,
  type XcagiProductSku,
  xcagiDownloadFileName,
  xcagiDownloadUrl,
} from '../utils/xcagiDownloadLinks'

const route = useRoute()
const router = useRouter()
const isEmbeddedInWorkbench = computed(() => String(route.name || '') === 'workbench-download')

/** 与 AI 管家浮球同源 Logo（站点根路径 /corp-butler/） */
const brandLogoSrc = '/corp-butler/brand-xc-logo.jpg'

// 下载版本来源优先级：运行时 /download-release.json（SSOT 公开子集，installer 日由发布脚本回写）
// → 构建期 VITE_XCAGI_* → 代码常量（v10 锁 10.0.0）。运行时读取让「P6 推送后无需重建站点即生效」。
const downloadVersion = ref(import.meta.env.VITE_XCAGI_DOWNLOAD_VERSION || DEFAULT_XCAGI_DOWNLOAD_VERSION)
const androidVersion = ref(import.meta.env.VITE_XCAGI_ANDROID_VERSION || DEFAULT_XCAGI_ANDROID_VERSION)
const downloadBaseOverride = ref<string | undefined>(import.meta.env.VITE_XCAGI_DOWNLOAD_BASE_URL)
const winInstallerMb = ref(String(import.meta.env.VITE_XCAGI_WIN_INSTALLER_MB || '654'))
const downloadBase = computed(() =>
  normalizeXcagiDownloadBase(downloadBaseOverride.value, downloadVersion.value),
)

function releaseManifestUrls(): string[] {
  const base = (import.meta.env.BASE_URL || '/').replace(/\/?$/, '/')
  const candidates = [`${base}download-release.json`, '/download-release.json']
  return candidates.filter((url, index) => candidates.indexOf(url) === index)
}

async function loadReleaseManifest() {
  try {
    let resp: Response | null = null
    for (const url of releaseManifestUrls()) {
      const attempt = await fetch(url, { cache: 'no-store' })
      if (attempt.ok) {
        resp = attempt
        break
      }
    }
    if (!resp) return
    const j = (await resp.json()) as Record<string, unknown>
    if (!j || typeof j !== 'object') return
    if (j.download_version) downloadVersion.value = String(j.download_version)
    if (j.android_version) androidVersion.value = String(j.android_version)
    if (j.win_installer_mb != null) winInstallerMb.value = String(j.win_installer_mb)
    if (j.release_root) downloadBaseOverride.value = String(j.release_root)
    else if (j.cos_base_url)
      downloadBaseOverride.value = `${String(j.cos_base_url).replace(/\/$/, '')}/xcagi-v${downloadVersion.value}`
  } catch {
    /* 离线 / 404：回退构建期常量（v10 锁 10.0.0） */
  }
}

const ENTERPRISE_MAILTO =
  'mailto:970882904@qq.com?subject=' + encodeURIComponent('XC 企业版咨询')

const macArch = detectMacDownloadArch()
const macArchLabel = computed(() => macDownloadArchLabel(macArch))

type PlatformTab = 'desktop' | 'android'
const platformTab = ref<PlatformTab>('desktop')
const edition = ref<XcagiProductSku>('personal')
const isMobileViewport = ref(false)
const isAndroidUa = ref(false)

interface ReleaseRow {
  id: string
  label: string
  meta?: string
  platform: XcagiDownloadPlatform
  sku: XcagiProductSku
  primary?: boolean
}

const releaseContext = computed(() => {
  if (platformTab.value === 'android') {
    return `XC ${androidVersion.value}`
  }
  const editionLabel = edition.value === 'personal' ? '个人版' : '企业版'
  return `XC ${downloadVersion.value} · ${editionLabel}`
})

const releaseRows = computed<ReleaseRow[]>(() => {
  if (platformTab.value === 'android') {
    return [
      {
        id: 'android-personal',
        label: 'Android · 个人版',
        platform: 'android',
        sku: 'personal',
        primary: true,
      },
      {
        id: 'android-enterprise',
        label: 'Android · 企业版',
        meta: '可与个人版共存',
        platform: 'android',
        sku: 'enterprise',
      },
    ]
  }

  const sku = edition.value
  return [
    {
      id: `win-${sku}`,
      label: 'Windows 64 位',
      meta: winInstallerMb.value ? `安装包约 ${winInstallerMb.value} MB` : undefined,
      platform: 'win',
      sku,
      primary: true,
    },
    {
      id: `mac-${sku}`,
      label: `macOS（${macArchLabel.value}）`,
      platform: 'mac',
      sku,
    },
  ]
})

function syncPlatformContext() {
  if (typeof window === 'undefined') return
  isMobileViewport.value = window.matchMedia('(max-width: 768px)').matches
  isAndroidUa.value = /Android/i.test(navigator.userAgent)
  if (isMobileViewport.value || isAndroidUa.value) {
    platformTab.value = 'android'
  }
}

onMounted(() => {
  syncPlatformContext()
  void loadReleaseManifest()
  window.addEventListener('resize', syncPlatformContext)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncPlatformContext)
})

function goBack() {
  if (isEmbeddedInWorkbench.value) {
    void router.push({ name: 'workbench-home' })
    return
  }
  if (window.history.length > 1) {
    router.back()
    return
  }
  window.location.assign('/index.html')
}

function downloadUrl(
  sku: XcagiProductSku,
  platform: XcagiDownloadPlatform,
  arch = macArch,
): string | null {
  return xcagiDownloadUrl(
    sku,
    platform,
    downloadBase.value,
    downloadVersion.value,
    androidVersion.value,
    arch,
  )
}

function download(sku: XcagiProductSku, platform: XcagiDownloadPlatform) {
  const arch = platform === 'mac' ? macArch : undefined
  const url = downloadUrl(sku, platform, arch ?? macArch)
  if (!url) return

  if (platform === 'android' || isMobileViewport.value) {
    window.location.assign(url)
    return
  }

  const a = document.createElement('a')
  a.href = url
  a.download = xcagiDownloadFileName(
    sku,
    platform,
    downloadVersion.value,
    androidVersion.value,
    platform === 'mac' ? macArch : 'arm64',
  )
  a.rel = 'noopener noreferrer'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const IconApple = () =>
  h(
    'svg',
    { class: 'sd-icon', width: 22, height: 22, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true' },
    h('path', {
      d: 'M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z',
    }),
  )

const IconWindows = () =>
  h(
    'svg',
    { class: 'sd-icon', width: 22, height: 22, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true' },
    [
      h('path', { d: 'M3 5.5L11 4v7.5H3V5.5z' }),
      h('path', { d: 'M12 4l9-1.5v8.5H12V4z' }),
      h('path', { d: 'M3 13.5h8V21l-8-1.5V13.5z' }),
      h('path', { d: 'M12 13.5h9V21l-9 1.5V13.5z' }),
    ],
  )

const IconAndroid = () =>
  h(
    'svg',
    {
      class: 'sd-icon',
      width: 22,
      height: 22,
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': 1.7,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
    },
    [
      h('path', { d: 'M7 9h10v8.5a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9z' }),
      h('path', { d: 'M8.5 6.5 6.5 4.5' }),
      h('path', { d: 'm15.5 6.5 2-2' }),
      h('path', { d: 'M8 9a4 4 0 0 1 8 0' }),
      h('path', { d: 'M10 13h.01' }),
      h('path', { d: 'M14 13h.01' }),
    ],
  )
</script>

<style scoped>
/* 微信下载页结构：居中品牌 + 版本列表 + 底部平台坞；保留深色与绿/金强调色 */
.sd {
  --sd-text: #f0f0f5;
  --sd-muted: rgba(255, 255, 255, 0.42);
  --sd-muted-2: rgba(255, 255, 255, 0.28);
  --sd-line: rgba(255, 255, 255, 0.1);
  --sd-surface: rgba(255, 255, 255, 0.06);
  --accent-personal: #34d399;
  --accent-enterprise: #fbbf24;
  --sd-center-max: 640px;
  width: 100%;
  min-height: 100dvh;
  min-height: 100%;
  height: 100%;
  margin: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  color: var(--sd-text);
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.sd-topbar {
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  padding: max(0.65rem, env(safe-area-inset-top)) var(--layout-pad-x, 1.25rem) 0.35rem;
  background: linear-gradient(180deg, rgba(10, 15, 26, 0.98) 70%, rgba(10, 15, 26, 0));
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.sd-back {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border: 0;
  background: transparent;
  padding: 0.35rem 0.5rem 0.35rem 0.15rem;
  margin-left: -0.15rem;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
  -webkit-tap-highlight-color: transparent;
}

.sd-back:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.06);
}

.sd-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: 0 var(--layout-pad-x, 1.25rem);
}

.sd-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: var(--sd-center-max);
  margin: 0 auto;
  padding: clamp(0.5rem, 2vh, 1.25rem) 0 clamp(1rem, 3vh, 1.75rem);
  text-align: center;
}

.sd-brand {
  display: flex;
  justify-content: center;
  margin-bottom: 1.25rem;
}

.sd-brand__logo {
  display: block;
  width: 80px;
  height: 80px;
  border-radius: 20px;
  object-fit: contain;
}

.sd-title {
  margin: 0 0 0.65rem;
  font-size: clamp(1.85rem, 5vw, 2.35rem);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.25;
}

.sd-sub {
  margin: 0 auto;
  max-width: 22rem;
  font-size: 0.9rem;
  line-height: 1.65;
  font-weight: 400;
  color: var(--sd-muted);
}

.sd-platform-links {
  display: inline-flex;
  align-items: center;
  gap: 0.65rem;
  margin-top: 1.35rem;
}

.sd-platform-link {
  border: 0;
  background: transparent;
  padding: 0.2rem 0;
  font-size: 0.875rem;
  color: var(--sd-muted);
  cursor: pointer;
  transition: color 0.15s ease;
}

.sd-platform-link--active {
  color: var(--sd-text);
  font-weight: 600;
}

.sd-platform-links__sep {
  color: var(--sd-muted-2);
  font-size: 0.75rem;
  user-select: none;
}

.sd-edition-switch {
  display: inline-flex;
  margin-top: 1.1rem;
  padding: 3px;
  border-radius: 999px;
  border: 1px solid var(--sd-line);
  background: var(--sd-surface);
}

.sd-edition-switch__btn {
  border: 0;
  background: transparent;
  padding: 0.35rem 1rem;
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--sd-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.sd-edition-switch__btn--active {
  color: #ecfdf5;
  background: rgba(52, 211, 153, 0.28);
}

.sd-edition-switch__btn--enterprise.sd-edition-switch__btn--active {
  color: #fffbeb;
  background: rgba(251, 191, 36, 0.28);
}

.sd-release-context {
  width: min(100%, 440px);
  margin: clamp(1.5rem, 4vh, 2rem) 0 0;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--sd-muted);
  text-align: left;
}

.sd-releases {
  width: min(100%, 440px);
  margin: 0.65rem 0 0;
  padding: 0;
  list-style: none;
  text-align: left;
}

.sd-release-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  padding: 0.85rem 0;
  border: 0;
  border-bottom: 1px solid var(--sd-line);
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
  transition: opacity 0.15s ease;
}

.sd-release-row:hover {
  opacity: 0.92;
}

.sd-release-row__main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.sd-release-row__name {
  font-size: 0.875rem;
  font-weight: 400;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.88);
}

.sd-release-row__meta {
  font-size: 0.75rem;
  color: var(--sd-muted-2);
}

.sd-release-row__action {
  flex-shrink: 0;
  min-width: 4.5rem;
  padding-top: 0.05rem;
  font-size: 0.8125rem;
  color: var(--sd-muted);
  text-align: right;
  white-space: nowrap;
}

.sd-release-row--primary .sd-release-row__action {
  color: var(--accent-personal);
  font-weight: 600;
}

.sd-release-row--primary:hover .sd-release-row__action {
  color: #6ee7b7;
}

.sd-footnote {
  margin: 1.25rem 0 0;
  max-width: 26rem;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--sd-muted-2);
}

.sd-footnote a {
  color: var(--sd-muted);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.sd-compare-fold {
  width: min(100%, 440px);
  margin-top: 1.5rem;
  text-align: left;
}

.sd-compare-fold summary {
  font-size: 0.8125rem;
  color: var(--sd-muted);
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.sd-compare-fold summary::-webkit-details-marker {
  display: none;
}

.sd-compare-fold summary::after {
  content: ' ›';
  opacity: 0.7;
}

.sd-compare-fold[open] summary::after {
  content: '';
}

.sd-compare-fold__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-top: 0.85rem;
}

.sd-edition-card {
  padding: 0.85rem;
  border-radius: 12px;
  border: 1px solid var(--sd-line);
  background: var(--sd-surface);
}

.sd-edition-card h3 {
  margin: 0 0 0.35rem;
  font-size: 0.875rem;
  font-weight: 600;
}

.sd-edition-card__badge {
  font-size: 0.625rem;
  font-weight: 600;
  color: #1c1917;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--accent-enterprise);
  vertical-align: middle;
}

.sd-edition-card__price {
  margin: 0 0 0.5rem;
  font-size: 0.9375rem;
  font-weight: 600;
}

.sd-edition-card__price a {
  color: var(--accent-enterprise);
  text-decoration: none;
}

.sd-edition-card ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.sd-edition-card li {
  font-size: 0.6875rem;
  line-height: 1.5;
  color: var(--sd-muted);
  padding: 0.15rem 0;
}

.sd-dock {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  gap: clamp(1.75rem, 8vw, 3.5rem);
  padding: 0.85rem 1rem calc(0.85rem + env(safe-area-inset-bottom));
  background: linear-gradient(180deg, transparent 0%, rgba(7, 11, 20, 0.92) 40%);
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.sd-dock__btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.55rem;
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.72);
  font-size: 0.75rem;
  cursor: pointer;
  transition: color 0.15s ease;
}

.sd-dock__btn:hover {
  color: #fff;
}

.sd-dock__icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  transition: background 0.2s ease, transform 0.15s ease;
}

.sd-dock__btn:hover .sd-dock__icon {
  background: rgba(255, 255, 255, 0.22);
  transform: translateY(-2px);
}

.sd-dock__icon :deep(.sd-icon) {
  display: block;
}

@media (max-width: 768px) {
  .sd {
    max-width: none;
  }

  .sd--embedded {
    padding-top: 0;
  }

  .sd-topbar {
    padding-left: max(0.75rem, env(safe-area-inset-left));
    padding-right: max(0.75rem, env(safe-area-inset-right));
  }

  .sd-scroll {
    padding-left: max(1rem, env(safe-area-inset-left));
    padding-right: max(1rem, env(safe-area-inset-right));
  }

  .sd-center {
    padding-top: 0.25rem;
  }

  .sd-compare-fold__grid {
    grid-template-columns: 1fr;
  }

  .sd-release-row {
    padding: 0.95rem 0;
  }

  .sd-release-row__action {
    min-width: 4.5rem;
    text-align: right;
  }

  .sd-release-row__name {
    font-size: 0.8125rem;
  }
}

@media (min-width: 769px) and (min-height: 700px) {
  .sd-center {
    padding-top: clamp(1rem, 5vh, 2.5rem);
  }
}
</style>
