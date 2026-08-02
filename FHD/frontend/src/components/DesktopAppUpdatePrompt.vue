<template>
  <div v-if="badgeVisible" class="desktop-update-anchor">
    <button
      type="button"
      class="desktop-update-chip"
      :class="{
        'is-downloading': phase === 'downloading',
        'is-ready': phase === 'downloaded',
      }"
      :title="badgeLabel"
      @click="openModal"
    >
      <span class="desktop-update-chip__dot" aria-hidden="true" />
      <span>{{ badgeLabel }}</span>
    </button>
    <button
      type="button"
      class="desktop-update-dismiss"
      aria-label="稍后提醒"
      title="稍后提醒"
      @click.stop="dismiss"
    >
      ×
    </button>
  </div>

  <!-- 角标仍挂侧栏；弹窗由 Modal 统一 Teleport 到 body，相对整窗居中 -->
  <Modal v-model="modalOpen" title="软件更新" :max-width="modalMaxWidth">
    <div class="desktop-update-modal">
      <div v-if="mediaSlides.length" class="desktop-update-media" aria-label="更新亮点">
        <div class="desktop-update-media__frame">
          <template v-if="activeSlide">
            <video
              v-if="activeSlide.videoUrl && videoPlaying && !videoFailed"
              ref="videoEl"
              class="desktop-update-media__video"
              :src="activeSlide.videoUrl"
              :poster="activeSlide.posterUrl"
              muted
              loop
              playsinline
              autoplay
              @error="onVideoError"
            />
            <img
              v-else-if="!posterFailed"
              class="desktop-update-media__poster"
              :src="activeSlide.posterUrl"
              :alt="activeSlide.caption || '更新预览'"
              @error="onPosterError"
            />
            <div v-else class="desktop-update-media__fallback" aria-hidden="true" />

            <button
              v-if="activeSlide.videoUrl && !videoPlaying && !videoFailed && !posterFailed"
              type="button"
              class="desktop-update-media__play"
              aria-label="播放演示"
              @click="playVideo"
            >
              <span class="desktop-update-media__play-icon" aria-hidden="true" />
              播放演示
            </button>
          </template>
        </div>

        <p v-if="activeSlide?.caption" class="desktop-update-media__caption">
          {{ activeSlide.caption }}
        </p>

        <div v-if="mediaSlides.length > 1" class="desktop-update-media__nav">
          <button
            type="button"
            class="desktop-update-media__arrow"
            aria-label="上一张"
            :disabled="slideIndex <= 0"
            @click="prevSlide"
          >
            ‹
          </button>
          <div class="desktop-update-media__dots" role="tablist" aria-label="更新亮点页">
            <button
              v-for="(_, idx) in mediaSlides"
              :key="idx"
              type="button"
              class="desktop-update-media__dot"
              :class="{ 'is-active': idx === slideIndex }"
              :aria-label="`第 ${idx + 1} 页`"
              :aria-selected="idx === slideIndex"
              role="tab"
              @click="goSlide(idx)"
            />
          </div>
          <button
            type="button"
            class="desktop-update-media__arrow"
            aria-label="下一张"
            :disabled="slideIndex >= mediaSlides.length - 1"
            @click="nextSlide"
          >
            ›
          </button>
        </div>
      </div>

      <p class="desktop-update-modal__lead">
        <template v-if="updateInfo?.version">
          新版本 <strong>{{ updateInfo.version }}</strong> 可用
        </template>
        <template v-else>有新版本可用</template>
        <span v-if="updateInfo?.buildSha" class="muted">
          · 构建 {{ updateInfo.buildSha.slice(0, 12) }}
        </span>
      </p>

      <div class="desktop-update-notes" aria-label="更新说明">
        <pre>{{ notesText }}</pre>
      </div>

      <div v-if="phase === 'downloading'" class="desktop-update-progress">
        <div class="desktop-update-progress__bar" :style="{ width: `${downloadPercent}%` }" />
        <span>正在下载 {{ Math.round(downloadPercent) }}%</span>
      </div>

      <p v-if="errorMessage" class="desktop-update-error">{{ errorMessage }}</p>
      <p v-if="selfUpdateBlockReason" class="desktop-update-error">
        {{ selfUpdateBlockReason }} 已保存的数据和登录状态不会被清除。
      </p>
    </div>
    <template #footer>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="busy" @click="closeModal">
        稍后
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="busy || phase === 'downloading' || !isSelfUpdateSupported"
        @click="primaryAction"
      >
        <template v-if="!isSelfUpdateSupported">请先正式安装</template>
        <template v-else-if="phase === 'downloaded'">更新并重新加载</template>
        <template v-else-if="phase === 'downloading'">下载中…</template>
        <template v-else>下载更新</template>
      </button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import Modal from '@/components/Modal.vue'
import { useDesktopAppUpdater } from '@/composables/useDesktopAppUpdater'

const {
  phase,
  updateInfo,
  downloadPercent,
  errorMessage,
  modalOpen,
  busy,
  badgeVisible,
  badgeLabel,
  notesText,
  mediaSlides,
  selfUpdateBlockReason,
  isSelfUpdateSupported,
  openModal,
  closeModal,
  dismiss,
  primaryAction,
} = useDesktopAppUpdater()

const slideIndex = ref(0)
const videoPlaying = ref(false)
const videoFailed = ref(false)
const posterFailed = ref(false)
const videoEl = ref<HTMLVideoElement | null>(null)

const activeSlide = computed(() => mediaSlides.value[slideIndex.value] || null)
const modalMaxWidth = computed(() => (mediaSlides.value.length ? '560px' : '520px'))

function resetMediaState() {
  videoPlaying.value = false
  videoFailed.value = false
  posterFailed.value = false
  if (videoEl.value) {
    try {
      videoEl.value.pause()
    } catch {
      /* ignore */
    }
  }
}

function goSlide(idx: number) {
  const max = mediaSlides.value.length - 1
  slideIndex.value = Math.max(0, Math.min(max, idx))
  resetMediaState()
}

function prevSlide() {
  goSlide(slideIndex.value - 1)
}

function nextSlide() {
  goSlide(slideIndex.value + 1)
}

async function playVideo() {
  if (!activeSlide.value?.videoUrl || videoFailed.value) return
  videoPlaying.value = true
  await nextTick()
  try {
    await videoEl.value?.play()
  } catch {
    videoFailed.value = true
    videoPlaying.value = false
  }
}

function onVideoError() {
  videoFailed.value = true
  videoPlaying.value = false
}

function onPosterError() {
  posterFailed.value = true
}

watch(
  () => mediaSlides.value.map((s) => `${s.posterUrl}|${s.videoUrl || ''}`).join(';'),
  () => {
    slideIndex.value = 0
    resetMediaState()
  },
)

watch(modalOpen, (open) => {
  if (!open) {
    resetMediaState()
    return
  }
  slideIndex.value = 0
  resetMediaState()
})
</script>

<style scoped>
.desktop-update-anchor {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
}

.desktop-update-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 180px;
  padding: 3px 8px;
  border: 1px solid rgba(37, 99, 235, 0.35);
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.3;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.desktop-update-chip.is-downloading {
  border-color: rgba(217, 119, 6, 0.4);
  background: #fffbeb;
  color: #b45309;
}

.desktop-update-chip.is-ready {
  border-color: rgba(22, 163, 74, 0.4);
  background: #f0fdf4;
  color: #15803d;
}

.desktop-update-chip__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: 0 0 auto;
}

.desktop-update-dismiss {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}

.desktop-update-media {
  margin: 0 0 14px;
}

.desktop-update-media__frame {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 10px;
  overflow: hidden;
  background: #0f172a;
  border: 1px solid #e2e8f0;
}

.desktop-update-media__poster,
.desktop-update-media__video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.desktop-update-media__fallback {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #1e293b, #334155);
}

.desktop-update-media__play {
  position: absolute;
  inset: 0;
  margin: auto;
  width: max-content;
  height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  border: none;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.72);
  color: #f8fafc;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  backdrop-filter: blur(4px);
}

.desktop-update-media__play:hover {
  background: rgba(15, 23, 42, 0.88);
}

.desktop-update-media__play-icon {
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 6px 0 6px 10px;
  border-color: transparent transparent transparent #f8fafc;
}

.desktop-update-media__caption {
  margin: 8px 0 0;
  font-size: 13px;
  color: #334155;
  text-align: center;
}

.desktop-update-media__nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 10px;
}

.desktop-update-media__arrow {
  width: 28px;
  height: 28px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  color: #0f172a;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.desktop-update-media__arrow:disabled {
  opacity: 0.35;
  cursor: default;
}

.desktop-update-media__dots {
  display: inline-flex;
  gap: 6px;
}

.desktop-update-media__dot {
  width: 7px;
  height: 7px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: #cbd5e1;
  cursor: pointer;
}

.desktop-update-media__dot.is-active {
  background: #2563eb;
}

.desktop-update-modal__lead {
  margin: 0 0 12px;
  font-size: 14px;
}

.desktop-update-notes {
  max-height: 220px;
  overflow: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px 14px;
}

.desktop-update-notes pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
}

.desktop-update-progress {
  margin-top: 12px;
  font-size: 12px;
  color: #64748b;
}

.desktop-update-progress__bar {
  height: 6px;
  margin-bottom: 6px;
  border-radius: 999px;
  background: #2563eb;
  transition: width 160ms ease;
}

.desktop-update-error {
  margin: 12px 0 0;
  color: #b91c1c;
  font-size: 13px;
}

.muted {
  color: #64748b;
  font-weight: 400;
}
</style>
