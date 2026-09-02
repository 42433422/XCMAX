<script setup>
import { defineProps } from 'vue'

// 拆分自 BrainView.vue 模板（原第 188–301 行）；模板逐字迁移，行为不变。
const props = defineProps({ tm: { type: Object, required: true } })

const {
  activeTab, skillRows, codeCreateIfMissing, codeAnalyzePath, codeEditNewContent,
  codeDraftInstruction, codeLastPreview, fillNewFromPreview, codeProbeLoading,
  probeCodeEditorDraft, probeCodeEditorStatus, probeCodeEditorAnalyze,
  probeCodeEditorEdit, probeCodeEditorDiff, probeCodeEditorApply, lastEditId,
} = props.tm
</script>

<template>
          <div v-show="activeTab === 'skills'" class="brain-panel card brain-card">
            <div class="card-header">Level 1 · 能力层（Skill）</div>
            <p class="muted">与 code-editor 栈对齐：analyze / edit / diff 可联调；apply 须设置页 P2 + 与服务器一致的提升口令。</p>
            <div class="brain-skill-grid">
              <article v-for="s in skillRows" :key="s.id" class="brain-skill-card">
                <header class="brain-skill-card__head">
                  <code class="brain-skill-card__id">{{ s.id }}</code>
                  <span class="brain-skill-card__status">{{ s.status }}</span>
                </header>
                <p class="brain-skill-card__desc">{{ s.desc }}</p>
              </article>
            </div>
            <div class="brain-code-editor-stub">
              <div class="brain-obs-title">code-editor 契约</div>
              <p class="muted brain-obs-hint">
                路径均相对 <code class="brain-mono">WORKSPACE_ROOT</code>。
                <code class="brain-mono">POST /edit</code> 提交完整
                <code class="brain-mono">new_content</code>；
                <code class="brain-mono">POST /apply</code> 会带上本机 P2 头并写盘。勾选「新建」时父目录须已存在，且为可识别文本后缀。
              </p>
              <label class="brain-stub-check">
                <input v-model="codeCreateIfMissing" type="checkbox" />
                <span class="muted">create_if_missing（path 不存在时按新建文本提案）</span>
              </label>
              <label class="brain-stub-path">
                <span class="muted">path</span>
                <input
                  v-model="codeAnalyzePath"
                  type="text"
                  class="brain-stub-path__input"
                  placeholder="例如 backend/env.example（留空则 noop）"
                  autocomplete="off"
                />
              </label>
              <label class="brain-stub-path">
                <span class="muted">new_content（POST /edit）</span>
                <textarea
                  v-model="codeEditNewContent"
                  class="brain-stub-textarea"
                  rows="4"
                  placeholder="编辑后的完整文件 UTF-8 文本…"
                  spellcheck="false"
                />
              </label>
              <label class="brain-stub-path">
                <span class="muted">instruction（POST /draft，须 P2 + LLM）</span>
                <textarea
                  v-model="codeDraftInstruction"
                  class="brain-stub-textarea brain-stub-textarea--sm"
                  rows="2"
                  placeholder="用自然语言描述希望对 path 的修改；成功后结果写入下方 new_content"
                  spellcheck="true"
                />
              </label>
              <div class="brain-stub-actions brain-stub-actions--wrap">
                <button type="button" class="btn btn-secondary btn-sm" :disabled="!codeLastPreview" @click="fillNewFromPreview">
                  用上次 analyze 预览填入
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading || !codeAnalyzePath.trim() || !codeDraftInstruction.trim()"
                  @click="probeCodeEditorDraft"
                >
                  POST /draft
                </button>
              </div>
              <div class="brain-stub-actions">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading"
                  @click="probeCodeEditorStatus"
                >
                  GET /status
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading"
                  @click="probeCodeEditorAnalyze"
                >
                  POST /analyze
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading || !codeAnalyzePath.trim() || !codeEditNewContent"
                  @click="probeCodeEditorEdit"
                >
                  POST /edit
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading || !lastEditId"
                  @click="probeCodeEditorDiff"
                >
                  GET /diff
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  :disabled="codeProbeLoading || !lastEditId"
                  @click="probeCodeEditorApply"
                >
                  POST /apply
                </button>
              </div>
              <p v-if="lastEditId" class="muted brain-stub-editid">
                当前 <code class="brain-mono">edit_id</code>：<code class="brain-mono">{{ lastEditId }}</code>
              </p>
            </div>
          </div>
</template>

<style scoped src="./brain.css"></style>
