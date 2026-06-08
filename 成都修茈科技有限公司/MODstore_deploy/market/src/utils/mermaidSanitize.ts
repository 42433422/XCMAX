/**
 * 把"模型生成的"宽容 Mermaid 源码尽量挽救成 Mermaid 词法器可以接受的形式。
 *
 * 设计取舍：
 * - 先做结构性修复（endsubgraph、subgraph 标题、粘连的 end），再做节点 label 引号包裹。
 * - 节点标签 `id[label]` / `id(label)` / `id{label}` 中含特殊字符时加 `"..."` 引号；
 *   引号内 `"` 用 `#quot;` 转义。
 * - 不处理双层括号形状（`[[ ]]` / `(( ))` / `{{ }}` / `([ ])` / `[( )]`）。
 */

const PROBLEMATIC = /[:;<>"'`#|&]|\(|\)|\[|\]|\{|\}/
const CJK = /[\u4e00-\u9fff\u3400-\u4dbf]/

function quoteLabel(label: string): string {
  const trimmed = label.trim()
  const escaped = trimmed.replace(/"/g, '#quot;')
  return `"${escaped}"`
}

function quoteIfNeeded(
  id: string,
  open: string,
  label: string,
  close: string,
): string | null {
  const trimmed = label.trim()
  if (!trimmed) return null
  if (/^".*"$/.test(trimmed)) return null
  if (!PROBLEMATIC.test(trimmed) && !CJK.test(trimmed)) return null
  return `${id}${open}${quoteLabel(trimmed)}${close}`
}

function fixStructuralMermaidErrors(input: string): string {
  let s = input
  let sgCounter = 0
  const nextSubgraphId = () => `sg_${++sgCounter}`

  // 模型常写 endsubgraph / endsub，Mermaid 只认 end
  s = s.replace(/\]?\s*endsubgraph/gi, '\nend')
  s = s.replace(/\]?\s*endsub(?!\w)/gi, '\nend')

  // `"]end` 或 `] end` 粘连
  s = s.replace(/\]\s*(?=end\b)/gi, ']\n')

  // end 后同一行跟中文子图标题 + 下一节点：end 员工：xxx B[
  s = s.replace(
    /\bend\b\s+([^\[\n\r\->|]+?)\s+([A-Za-z0-9_\-]+\[)/gi,
    (_match, title: string, nodeStart: string) => {
      const t = title.trim()
      if (!t || t.includes('-->')) return _match
      const id = nextSubgraphId()
      return `end\nsubgraph ${id}[${quoteLabel(t)}]\n${nodeStart}`
    },
  )

  // 独立一行 subgraph 中文/冒号标题：`subgraph 员工：文档文本提取员`
  s = s.replace(
    /^(\s*)subgraph\s+([^\[\n\r"]+)$/gm,
    (match, indent: string, title: string) => {
      const t = title.trim()
      if (!t) return match
      if (/^[A-Za-z0-9_\-]+\[/.test(t)) return match
      if (/^[A-Za-z0-9_\-]+$/.test(t) && !CJK.test(t) && !t.includes(':')) return match
      const id = nextSubgraphId()
      return `${indent}subgraph ${id}[${quoteLabel(t)}]`
    },
  )

  // end 后换行跟孤立的子图标题行
  s = s.replace(
    /^(\s*)end\s*\n\s*([^\[\n\r\->|]+?)\s*$/gm,
    (match, indent: string, title: string) => {
      const t = title.trim()
      if (!t || /^[A-Za-z0-9_\-]+\s*\[/.test(t) || t.includes('-->')) return match
      const id = nextSubgraphId()
      return `${indent}end\n${indent}subgraph ${id}[${quoteLabel(t)}]`
    },
  )

  return s
}

export function sanitizeMermaidSource(input: string): string {
  let s = String(input ?? '').replace(/\r\n?/g, '\n')

  // 偶发：模型把围栏一起塞进来；先剥掉首尾的 ``` 行
  s = s.replace(/^\s*```[\w+-]*\n/, '').replace(/\n```\s*$/, '')

  s = fixStructuralMermaidErrors(s)

  // 方括号节点：A[label]
  s = s.replace(
    /([A-Za-z0-9_\-]+)(\[)([^\[\]\n]*?)(\])/g,
    (match, id: string, open: string, label: string, close: string) =>
      quoteIfNeeded(id, open, label, close) ?? match,
  )

  // 圆括号节点：A(label)
  s = s.replace(
    /([A-Za-z0-9_\-]+)(\()([^()\n]*?)(\))/g,
    (match, id: string, open: string, label: string, close: string) =>
      quoteIfNeeded(id, open, label, close) ?? match,
  )

  // 花括号节点：A{label}
  s = s.replace(
    /([A-Za-z0-9_\-]+)(\{)([^{}\n]*?)(\})/g,
    (match, id: string, open: string, label: string, close: string) =>
      quoteIfNeeded(id, open, label, close) ?? match,
  )

  return s
}

/** 将 Mermaid 词法错误转为用户可读的中文提示 */
export function friendlyMermaidRenderError(raw: unknown): string {
  const msg = String((raw && typeof raw === 'object' && 'message' in raw && raw.message) || raw || '')
    .trim()
  if (!msg) return '流程图解析失败，请查看右侧「详细」说明'
  if (/lexical error/i.test(msg)) {
    return '流程图语法有误，已无法自动修复；请查看右侧「详细」中的文字说明'
  }
  if (/parse error/i.test(msg)) return '流程图结构无法解析，请查看右侧「详细」说明'
  return msg.length > 120 ? `${msg.slice(0, 117)}…` : msg
}
