import { sanitizeMermaidSource } from '@/utils/mermaidSanitize'

/**
 * Markdown 渲染后的 DOM 增强（代码块复制按钮 + Mermaid 流程图）。
 *
 * 从 MessageBody.vue 抽出为共享逻辑，供 MessageBody 与主对话消息列表
 * （ChatMessageList）复用：两者都用 lightMarkdown 渲染出 `.md-code__copy`
 * 与 `.md-mermaid[data-source]`，此前只有 MessageBody 接线，主列表的复制
 * 按钮点了没反应、Mermaid 占位不渲染。
 *
 * 所有函数按 `data-bound` / `data-rendered` + srcHash 幂等，可在同一容器上
 * 重复调用（含流式追加、多条消息共享容器）。
 */

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

function escapeText(raw: string): string {
  return raw.replace(
    /[<>&]/g,
    (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' } as Record<string, string>)[c] || c,
  )
}

/** 渲染容器内所有未处理的 Mermaid 块（原始 source 优先，失败再用 sanitize 后重试）。 */
export async function flushMermaid(host: HTMLElement | null): Promise<void> {
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

/** 给容器内所有代码块复制按钮绑定点击（幂等：已绑定的跳过）。 */
export function bindCodeCopyButtons(host: HTMLElement | null): void {
  if (!host) return
  const btns = Array.from(host.querySelectorAll('.md-code__copy')) as HTMLButtonElement[]
  for (const btn of btns) {
    if (btn.dataset.bound === '1') continue
    btn.dataset.bound = '1'
    btn.addEventListener('click', async () => {
      const code =
        btn.parentElement?.parentElement?.querySelector('.md-code__body')?.textContent || ''
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

/** 一次性完成容器内的代码复制绑定 + Mermaid 渲染。 */
export async function enhanceMarkdownContainer(host: HTMLElement | null): Promise<void> {
  if (!host) return
  bindCodeCopyButtons(host)
  await flushMermaid(host)
}
