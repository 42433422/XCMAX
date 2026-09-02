import { ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

/** code-editor 联调探针（拆分自 BrainView.vue，逻辑不变） */
export function useBrainCodeEditor({ pushActivity }) {
  const codeProbeLoading = ref(false)
  /** 相对 WORKSPACE_ROOT，传给 POST /api/code-editor/analyze */
  const codeAnalyzePath = ref('')
  /** POST /edit 的完整新文本 */
  const codeEditNewContent = ref('')
  /** 最近一次 text_preview 的原文，用于一键填入 new_content */
  const codeLastPreview = ref('')
  /** 最近一次 POST /edit 返回的 edit_id */
  const lastEditId = ref('')
  /** POST /edit：path 不存在时在已有父目录下新建文本（与后端 JSON 严格 true 一致） */
  const codeCreateIfMissing = ref(false)
  /** POST /api/code-editor/draft */
  const codeDraftInstruction = ref('')

  function fillNewFromPreview() {
    if (codeLastPreview.value) {
      codeEditNewContent.value = codeLastPreview.value
      pushActivity('已将上次 analyze 预览写入 new_content')
    }
  }

  async function probeCodeEditorStatus() {
    codeProbeLoading.value = true
    try {
      const res = await apiFetch('/api/code-editor/status')
      const txt = res.ok ? `code-editor/status → ${res.status}` : `code-editor/status HTTP ${res.status}`
      pushActivity(txt)
    } catch (e) {
      pushActivity(`code-editor/status 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  async function probeCodeEditorAnalyze() {
    codeProbeLoading.value = true
    try {
      const path = codeAnalyzePath.value.trim()
      const res = await apiFetch('/api/code-editor/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: 'brain probe',
          ...(path ? { path } : {})
        })
      })
      let extra = ''
      try {
        const j = await res.clone().json()
        if (j && typeof j.kind === 'string') {
          extra = ` — ${j.kind}`
        } else if (j && typeof j.message === 'string') {
          extra = ` — ${j.message.slice(0, 80)}`
        }
        if (j && j.kind === 'text_preview' && typeof j.preview === 'string') {
          codeLastPreview.value = j.preview
          const snippet = j.preview.replace(/\s+/g, ' ').trim().slice(0, 60)
          if (snippet) {
            extra += ` · ${snippet}${j.preview.length > 60 ? '…' : ''}`
          }
        } else {
          codeLastPreview.value = ''
        }
      } catch {
        /* ignore */
      }
      pushActivity(`code-editor/analyze → ${res.status}${extra}`)
    } catch (e) {
      pushActivity(`code-editor/analyze 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  async function probeCodeEditorDraft() {
    const path = codeAnalyzePath.value.trim()
    const instruction = codeDraftInstruction.value.trim()
    if (!path || !instruction) {
      pushActivity('POST /draft 需要 path 与 instruction')
      return
    }
    codeProbeLoading.value = true
    try {
      const payload = { path, instruction }
      if (codeCreateIfMissing.value) {
        payload.create_if_missing = true
      }
      const res = await apiFetch('/api/code-editor/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      let extra = ''
      try {
        const j = await res.clone().json()
        if (res.ok && j && j.success === true && typeof j.proposed_new_content === 'string') {
          codeEditNewContent.value = j.proposed_new_content
          extra = ' — 已填入 new_content'
          if (j.context_truncated) {
            extra += '（模型侧上下文已截断）'
          }
        } else if (j && typeof j.message === 'string') {
          extra = ` — ${j.message.slice(0, 120)}`
        }
      } catch {
        /* ignore */
      }
      if (res.status === 403) {
        extra += ' — 需 P2'
      }
      if (res.status === 503 || res.status === 502) {
        extra += ' — 检查 LLM 配置'
      }
      pushActivity(`code-editor/draft → ${res.status}${extra}`)
    } catch (e) {
      pushActivity(`code-editor/draft 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  async function probeCodeEditorEdit() {
    const path = codeAnalyzePath.value.trim()
    if (!path) {
      pushActivity('POST /edit 需要 path')
      return
    }
    const newContent = codeEditNewContent.value
    if (!newContent) {
      pushActivity('POST /edit 需要 new_content')
      return
    }
    codeProbeLoading.value = true
    try {
      const body = { path, new_content: newContent }
      if (codeCreateIfMissing.value) {
        body.create_if_missing = true
      }
      const res = await apiFetch('/api/code-editor/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      let extra = ''
      try {
        const j = await res.clone().json()
        if (j && j.edit_id) {
          lastEditId.value = String(j.edit_id)
          extra = ` — edit_id=${lastEditId.value.slice(0, 12)}…`
          if (j.is_new_file) {
            extra += ', new_file'
          }
        }
      } catch {
        /* ignore */
      }
      pushActivity(`code-editor/edit → ${res.status}${extra}`)
    } catch (e) {
      pushActivity(`code-editor/edit 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  async function probeCodeEditorDiff() {
    const id = lastEditId.value.trim()
    if (!id) return
    codeProbeLoading.value = true
    try {
      const res = await apiFetch(`/api/code-editor/diff/${encodeURIComponent(id)}`)
      let extra = ''
      try {
        const j = await res.clone().json()
        if (j && typeof j.unified_diff === 'string') {
          const n = j.unified_diff.split('\n').length
          extra = ` — ${n} 行 diff`
        }
      } catch {
        /* ignore */
      }
      pushActivity(`code-editor/diff → ${res.status}${extra}`)
    } catch (e) {
      pushActivity(`code-editor/diff 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  async function probeCodeEditorApply() {
    const id = lastEditId.value.trim()
    if (!id) return
    codeProbeLoading.value = true
    try {
      const res = await apiFetch(`/api/code-editor/apply/${encodeURIComponent(id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      let extra = ''
      if (res.ok) {
        lastEditId.value = ''
        extra = ' — 已写盘，edit_id 已失效'
      } else if (res.status === 403) {
        extra = ' — 需 P2（设置里开发者模式 + 与服务器一致的口令）'
      } else if (res.status === 409) {
        extra = ' — 磁盘文件在提案后已变，请重新 POST /edit'
      }
      pushActivity(`code-editor/apply → ${res.status}${extra}`)
    } catch (e) {
      pushActivity(`code-editor/apply 异常：${e instanceof Error ? e.message : '错误'}`)
    } finally {
      codeProbeLoading.value = false
    }
  }

  return {
    codeProbeLoading,
    codeAnalyzePath,
    codeEditNewContent,
    codeLastPreview,
    lastEditId,
    codeCreateIfMissing,
    codeDraftInstruction,
    fillNewFromPreview,
    probeCodeEditorStatus,
    probeCodeEditorAnalyze,
    probeCodeEditorDraft,
    probeCodeEditorEdit,
    probeCodeEditorDiff,
    probeCodeEditorApply,
  }
}
