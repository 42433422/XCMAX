/**
 * 朗读双语字幕总线（QQ 音乐式底部悬浮窗）。
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
  return gen
}

export function isTtsSubtitleSession(gen: number): boolean {
  return gen === sessionGen && visible.value
}

export function setTtsSubtitleIndex(index: number, gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  if (!visible.value || !lines.value.length) return
  currentIndex.value = Math.max(0, Math.min(lines.value.length - 1, index))
}

export function updateTtsSubtitleEn(index: number, en: string, gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  const row = lines.value[index]
  if (!row) return
  const next = [...lines.value]
  next[index] = { ...row, en: String(en || '').trim() }
  lines.value = next
}

export function endTtsSubtitles(gen?: number): void {
  if (gen != null && gen !== sessionGen) return
  visible.value = false
  lines.value = []
  currentIndex.value = 0
  sessionGen += 1
}

export function useTtsSubtitleStore() {
  const current = computed(() => lines.value[currentIndex.value] || null)
  const prev = computed(() =>
    currentIndex.value > 0 ? lines.value[currentIndex.value - 1] || null : null,
  )
  const next = computed(() =>
    currentIndex.value < lines.value.length - 1
      ? lines.value[currentIndex.value + 1] || null
      : null,
  )
  return {
    visible: readonly(visible),
    lines: readonly(lines),
    currentIndex: readonly(currentIndex),
    current,
    prev,
    next,
    dismiss: () => endTtsSubtitles(),
  }
}
