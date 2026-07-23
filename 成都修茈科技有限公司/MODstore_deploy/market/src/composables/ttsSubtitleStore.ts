/**
 * 朗读中文字幕总线（QQ 音乐式底部悬浮窗数据源）。
 * 任意 TTS 入口 begin → setIndex → end；Overlay 只读订阅。
 */

import { computed, ref, readonly } from 'vue'

export interface TtsSubtitleLine {
  zh: string
  en: string
}

const visible = ref(false)
const lines = ref<TtsSubtitleLine[]>([])
const currentIndex = ref(0)
let sessionGen = 0

export function beginTtsSubtitles(zhLines: string[]): number {
  const cleaned = zhLines.map((s) => String(s || '').trim()).filter(Boolean)
  sessionGen += 1
  const gen = sessionGen
  lines.value = cleaned.map((zh) => ({ zh, en: '' }))
  currentIndex.value = 0
  visible.value = cleaned.length > 0
  if (!cleaned.length) {
    // 流式会话先占坑，等首句 append 再显示
    visible.value = false
  }
  return gen
}

export function isTtsSubtitleSession(gen: number): boolean {
  return gen === sessionGen && visible.value
}

export function setTtsSubtitleIndex(index: number, gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  if (!visible.value || !lines.value.length) return
  const i = Math.max(0, Math.min(lines.value.length - 1, index))
  currentIndex.value = i
}

export function updateTtsSubtitleEn(index: number, en: string, gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  const row = lines.value[index]
  if (!row) return
  const next = [...lines.value]
  next[index] = { ...row, en: String(en || '').trim() }
  lines.value = next
}

export function appendTtsSubtitleLine(zh: string, gen?: number): number {
  if (gen != null && gen !== sessionGen) return -1
  const t = String(zh || '').trim()
  if (!t) return -1
  const idx = lines.value.length
  lines.value = [...lines.value, { zh: t, en: '' }]
  if (!visible.value) visible.value = true
  return idx
}

export function endTtsSubtitles(gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  visible.value = false
  lines.value = []
  currentIndex.value = 0
  sessionGen += 1
}

export function useTtsSubtitleStore() {
  // 字幕只暴露当前句，不提供上一句/下一句（避免卡拉 OK 式上下文）
  const current = computed(() => lines.value[currentIndex.value] || null)
  return {
    visible: readonly(visible),
    lines: readonly(lines),
    currentIndex: readonly(currentIndex),
    current,
    dismiss: () => endTtsSubtitles(),
  }
}
