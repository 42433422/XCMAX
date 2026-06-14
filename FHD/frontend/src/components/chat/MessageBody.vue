<template>
  <div ref="hostRef" class="msg-body" v-html="rendered" />
</template>

<script setup lang="ts">
import { asRecord, asArray, asString } from '@/utils/typeGuards'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { renderMarkdown } from '@/utils/lightMarkdown'
import { sanitizeMermaidSource } from '@/utils/mermaidSanitize'

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

let mermaidApi: {
  initialize: (config?: Record<string, unknown>) => void
  run: (options?: Record<string, unknown>) => Promise<void>
} | null = null
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
      const escapeText = (raw: string) =>
        raw.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' } as Record<string, string>)[c] || c)
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

<style scoped>
.msg-body {
  display: block;
  color: rgba(248, 250, 252, 0.94);
  line-height: 1.6;
  font-size: 0.95rem;
  word-break: break-word;
}

.msg-body :deep(.md-p) {
  margin: 0.4rem 0;
}

.msg-body :deep(.md-h) {
  margin: 0.85rem 0 0.5rem;
  font-weight: 700;
  line-height: 1.3;
}

.msg-body :deep(.md-h1) { font-size: 1.45rem; }
.msg-body :deep(.md-h2) { font-size: 1.25rem; }
.msg-body :deep(.md-h3) { font-size: 1.08rem; }
.msg-body :deep(.md-h4) { font-size: 1rem; color: rgba(226, 232, 240, 0.92); }
.msg-body :deep(.md-h5),
.msg-body :deep(.md-h6) { font-size: 0.94rem; color: rgba(203, 213, 225, 0.9); }

.msg-body :deep(.md-list) {
  padding-left: 1.4rem;
  margin: 0.4rem 0;
}

.msg-body :deep(.md-li) {
  margin: 0.18rem 0;
}

.msg-body :deep(.md-quote) {
  margin: 0.6rem 0;
  padding: 0.4rem 0.85rem;
  border-left: 3px solid rgba(129, 140, 248, 0.55);
  background: rgba(129, 140, 248, 0.08);
  color: rgba(226, 232, 240, 0.88);
  border-radius: 0 0.4rem 0.4rem 0;
}

.msg-body :deep(.md-link) {
  color: #93c5fd;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.msg-body :deep(.md-link:hover) { color: #bfdbfe; }

.msg-body :deep(.md-img) {
  max-width: 100%;
  border-radius: 0.5rem;
  margin: 0.4rem 0;
}

.msg-body :deep(.md-hr) {
  border: 0;
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
  margin: 0.85rem 0;
}

.msg-body :deep(.md-code-inline) {
  padding: 0.08em 0.35em;
  border-radius: 0.32em;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 0.88em;
  color: #fbbf24;
}

.msg-body :deep(.md-code) {
  margin: 0.5rem 0;
  border-radius: 0.6rem;
  background: rgba(2, 6, 23, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.msg-body :deep(.md-code__head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.35rem 0.75rem;
  background: rgba(15, 23, 42, 0.85);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 0.72rem;
  color: rgba(226, 232, 240, 0.7);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  user-select: none;
}

.msg-body :deep(.md-code__copy) {
  background: transparent;
  color: rgba(226, 232, 240, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 0.18rem 0.55rem;
  font-size: 0.7rem;
  border-radius: 0.4rem;
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
}
.msg-body :deep(.md-code__copy:hover) {
  background: rgba(99, 102, 241, 0.18);
  color: #fff;
}

.msg-body :deep(.md-code__body) {
  display: block;
  padding: 0.7rem 0.95rem;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 0.86rem;
  line-height: 1.55;
  color: #e2e8f0;
  overflow-x: auto;
  white-space: pre;
  user-select: text;
}

.msg-body :deep(.md-table-wrap) {
  margin: 0.55rem 0;
  overflow-x: auto;
  border-radius: 0.55rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.msg-body :deep(.md-table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.88rem;
}

.msg-body :deep(.md-table th),
.msg-body :deep(.md-table td) {
  padding: 0.45rem 0.7rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  text-align: left;
  vertical-align: top;
}

.msg-body :deep(.md-table th:last-child),
.msg-body :deep(.md-table td:last-child) {
  border-right: none;
}

.msg-body :deep(.md-table th) {
  background: rgba(99, 102, 241, 0.12);
  color: rgba(226, 232, 240, 0.95);
  font-weight: 600;
}

.msg-body :deep(.md-table tbody tr:hover) {
  background: rgba(255, 255, 255, 0.04);
}

.msg-body :deep(.md-math) {
  font-family: 'Cambria Math', 'Times New Roman', serif;
  color: #fbbf24;
  font-style: italic;
}

.msg-body :deep(.md-math-block) {
  display: block;
  margin: 0.6rem 0;
  padding: 0.5rem 0.9rem;
  border: 1px dashed rgba(251, 191, 36, 0.4);
  border-radius: 0.45rem;
  text-align: center;
  background: rgba(251, 191, 36, 0.05);
}

.msg-body :deep(.md-mermaid) {
  display: block;
  margin: 0.55rem 0;
  padding: 0.6rem;
  background: rgba(15, 23, 42, 0.6);
  border-radius: 0.6rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
  text-align: center;
}

.msg-body :deep(.md-mermaid svg) {
  max-width: 100%;
  height: auto;
}

.msg-body :deep(.md-mermaid-fail) {
  display: block;
  margin: 0.55rem 0;
  border-radius: 0.6rem;
  overflow: hidden;
  border: 1px solid rgba(248, 113, 113, 0.4);
  background: rgba(127, 29, 29, 0.18);
}

.msg-body :deep(.md-mermaid-fail__head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 0.4rem 0.7rem;
  background: rgba(127, 29, 29, 0.32);
  color: #fecaca;
  font-size: 0.78rem;
  line-height: 1.4;
}

.msg-body :deep(.md-mermaid-fail__msg) {
  flex: 1;
  word-break: break-word;
}

.msg-body :deep(.md-mermaid-fail__copy) {
  flex-shrink: 0;
  background: transparent;
  color: #fecaca;
  border: 1px solid rgba(252, 165, 165, 0.5);
  padding: 0.16rem 0.55rem;
  font-size: 0.72rem;
  border-radius: 0.4rem;
  cursor: pointer;
}
.msg-body :deep(.md-mermaid-fail__copy:hover) {
  background: rgba(248, 113, 113, 0.18);
  color: #fff;
}

.msg-body :deep(.md-mermaid-fail .md-code) {
  margin: 0;
  border-radius: 0;
  border: none;
  border-top: 1px solid rgba(248, 113, 113, 0.25);
}

.msg-body :deep(.msg-body__cursor) {
  display: inline-block;
  width: 0.55ch;
  margin-left: 0.1ch;
  color: rgba(165, 180, 252, 0.9);
  animation: msgBodyCursorBlink 1s steps(2, start) infinite;
}

@keyframes msgBodyCursorBlink {
  to {
    visibility: hidden;
  }
}

html[data-workbench-theme='light'] .msg-body {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-h4) {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-h5),
html[data-workbench-theme='light'] .msg-body :deep(.md-h6) {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-quote) {
  border-left-color: rgba(0, 113, 227, 0.3);
  background: rgba(0, 113, 227, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-link) {
  color: #0071e3;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-link:hover) {
  color: #2997ff;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-hr) {
  background: rgba(0, 0, 0, 0.04);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code-inline) {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.08);
  color: #d97706;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code) {
  background: rgba(0, 0, 0, 0.05);
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code__head) {
  background: rgba(0, 0, 0, 0.04);
  border-bottom-color: rgba(0, 0, 0, 0.06);
  color: #86868b;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code__copy) {
  color: #1d1d1f;
  border-color: rgba(0, 0, 0, 0.1);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code__copy:hover) {
  background: rgba(0, 113, 227, 0.1);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-code__body) {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-table-wrap) {
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-table th),
html[data-workbench-theme='light'] .msg-body :deep(.md-table td) {
  border-bottom-color: rgba(0, 0, 0, 0.08);
  border-right-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-table th) {
  background: rgba(0, 113, 227, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-table tbody tr:hover) {
  background: rgba(0, 0, 0, 0.03);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-math) {
  color: #d97706;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-math-block) {
  border-color: rgba(217, 119, 6, 0.3);
  background: rgba(217, 119, 6, 0.05);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid) {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid-fail) {
  border-color: rgba(215, 0, 21, 0.3);
  background: rgba(215, 0, 21, 0.06);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid-fail__head) {
  background: rgba(215, 0, 21, 0.1);
  color: #d70015;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid-fail__copy) {
  color: #d70015;
  border-color: rgba(215, 0, 21, 0.4);
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid-fail__copy:hover) {
  background: rgba(215, 0, 21, 0.08);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .msg-body :deep(.md-mermaid-fail .md-code) {
  border-top-color: rgba(215, 0, 21, 0.2);
}

html[data-workbench-theme='light'] .msg-body :deep(.msg-body__cursor) {
  color: #0071e3;
}
</style>
