<template>
  <div ref="hostRef" class="msg-body" v-html="rendered" />
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { renderMarkdown } from '../../utils/lightMarkdown'
import { sanitizeMermaidSource } from '../../utils/mermaidSanitize'
import type { Mermaid } from 'mermaid'

const props = defineProps<{
  content: string
  /** 是否在生成中（生成中末尾会附加光标） */
  streaming?: boolean
}>()

const hostRef = ref<HTMLDivElement | null>(null)

const rendered = computed(() => {
  const text = props.content || ''
  const html = renderMarkdown(text)
  if (props.streaming && text.trim()) {
    return `${html}<span class="msg-body__cursor" aria-hidden="true">▍</span>`
  }
  return html
})

let mermaidApi: Mermaid | null = null
let mermaidInit = false

async function getMermaid() {
  if (!mermaidApi) {
    const mod = await import('mermaid')
    mermaidApi = mod.default
  }
  if (!mermaidInit) {
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'dark',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    })
    mermaidInit = true
  }
  return mermaidApi
}

/** 简单哈希：用于跳过 source 未变化的 mermaid 块 */
function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  }
  return h
}

async function flushMermaid() {
  const host = hostRef.value
  if (!host) return
  const els = Array.from(host.querySelectorAll('.md-mermaid')) as HTMLElement[]
  if (!els.length) return
  let mer
  try {
    mer = await getMermaid()
  } catch {
    for (const el of els) el.textContent = '[流程图加载失败]'
    return
  }
  for (const el of els) {
    const src = el.dataset.source || ''
    if (!src) {
      el.dataset.rendered = '1'
      continue
    }
    const srcHash = String(hashStr(src))
    if (el.dataset.rendered === '1' && el.dataset.srcHash === srcHash) continue

    // 优先用原始 source；失败再用 sanitize 后的版本重试一次。
    // 这样既不破坏已经合法的图，又能挽救常见 LLM 失误（括号/引号/冒号未引）。
    const variants: string[] = [src]
    const sanitized = sanitizeMermaidSource(src)
    if (sanitized && sanitized !== src) variants.push(sanitized)

    let rendered = false
    let lastErr: unknown = null
    for (const variant of variants) {
      const slot = document.createElement('div')
      slot.className = 'mermaid'
      slot.textContent = variant
      el.innerHTML = ''
      el.appendChild(slot)
      try {
        await mer.run({ nodes: [slot] })
        rendered = true
        break
      } catch (e) {
        lastErr = e
      }
    }

    if (!rendered) {
      const errMsg = (lastErr as Error)?.message || String(lastErr || '')
      const escapeMap: Record<string, string> = { '<': '&lt;', '>': '&gt;', '&': '&amp;' }
      const escapeText = (raw: string) => raw.replace(/[<>&]/g, (c) => escapeMap[c] || c)
      el.innerHTML =
        `<div class="md-mermaid-fail">` +
        `<div class="md-mermaid-fail__head">` +
        `<span class="md-mermaid-fail__msg">流程图解析失败：${escapeText(errMsg)}</span>` +
        `<button type="button" class="md-mermaid-fail__copy" data-copy-source>复制源码</button>` +
        `</div>` +
        `<pre class="md-code"><code class="md-code__body">${escapeText(src)}</code></pre>` +
        `</div>`
      const copyBtn = el.querySelector('[data-copy-source]') as HTMLButtonElement | null
      if (copyBtn) {
        copyBtn.addEventListener('click', async () => {
          const orig = copyBtn.textContent
          try {
            await navigator.clipboard.writeText(src)
            copyBtn.textContent = '已复制'
          } catch {
            copyBtn.textContent = '复制失败'
          }
          window.setTimeout(() => {
            copyBtn.textContent = orig || '复制源码'
          }, 1400)
        })
      }
    }
    el.dataset.rendered = '1'
    el.dataset.srcHash = srcHash
  }
}

function bindCopyButtons() {
  const host = hostRef.value
  if (!host) return
  const btns = Array.from(host.querySelectorAll('.md-code__copy')) as HTMLButtonElement[]
  for (const btn of btns) {
    if (btn.dataset.bound === '1') continue
    btn.dataset.bound = '1'
    btn.addEventListener('click', async () => {
      const code = btn.parentElement?.parentElement?.querySelector('.md-code__body')?.textContent || ''
      try {
        await navigator.clipboard.writeText(code)
        const orig = btn.textContent
        btn.textContent = '已复制'
        window.setTimeout(() => {
          btn.textContent = orig || '复制'
        }, 1400)
      } catch {
        btn.textContent = '复制失败'
      }
    })
  }
}

async function flushAll() {
  await nextTick()
  bindCopyButtons()
  await flushMermaid()
}

onMounted(() => {
  void flushAll()
})

// 流式输出中只更新 rendered HTML（computed 自动处理），
// 不触发 Mermaid/复制绑定等高成本后处理；流结束后（streaming 变 false）
// 以及内容发生语义变化时（新消息/内容追加完毕）才做完整后处理。
let _postFlushRafId: number | null = null
watch(
  () => props.content,
  () => {
    // streaming 时跳过重型后处理，只让 computed 刷新 DOM
    if (props.streaming) return
    // 非流式时使用 RAF 合并，避免短时间内多次触发
    if (_postFlushRafId !== null) return
    _postFlushRafId = requestAnimationFrame(() => {
      _postFlushRafId = null
      void flushAll()
    })
  },
)

// streaming 结束后（false → true 方向为误触发，false 为完成）做最终 flush
watch(
  () => props.streaming,
  (isStreaming) => {
    if (!isStreaming) {
      if (_postFlushRafId !== null) { cancelAnimationFrame(_postFlushRafId); _postFlushRafId = null }
      void flushAll()
    }
  },
)
</script>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./MessageBody.css，模板与逻辑保持原样。 -->
<style scoped src="./MessageBody.css"></style>
