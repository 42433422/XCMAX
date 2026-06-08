<template>
  <section class="workbench-panel vibe-code-panel">
    <header class="vibe-head">
      <h2>AI 代码技能 · vibe-coding</h2>
      <p class="muted small">
        用一句自然语言描述你想要的 Python 函数，vibe-coding 会写代码 → 跑沙箱 → 自动修复，
        完成后可一键打包成 <code>.xcmod</code> 上架到 MODstore。
      </p>
    </header>

    <div class="vibe-form">
      <label>brief</label>
      <textarea
        v-model="brief"
        rows="6"
        placeholder="例：解析 input.csv 取第 2 列求和，返回 {sum, rows}"
        class="vibe-input"
        :disabled="busy"
      />

      <div class="vibe-row">
        <label>试运行 input (JSON)</label>
        <textarea
          v-model="runInputJson"
          rows="3"
          placeholder='{"x": 1}'
          class="vibe-input mono"
          :disabled="busy"
        />
      </div>

      <div class="vibe-row vibe-row-inline">
        <label class="cb"><input type="checkbox" v-model="dryRun" :disabled="busy" /> 仅生成 + 试跑（不上架）</label>
        <label class="cb"><input type="checkbox" v-model="publishAfter" :disabled="busy || dryRun" /> 试跑通过后立即上架</label>
      </div>

      <div v-if="publishAfter && !dryRun" class="vibe-publish">
        <div class="vibe-pub-row">
          <label>上架 pkg_id <span class="req">*</span></label>
          <input v-model="pkgId" class="vibe-input" placeholder="vc-string-reverse-1" :disabled="busy" />
        </div>
        <div class="vibe-pub-row">
          <label>名称</label>
          <input v-model="pubName" class="vibe-input" placeholder="字符串反转技能" :disabled="busy" />
        </div>
        <div class="vibe-pub-row">
          <label>简介</label>
          <input v-model="pubDescription" class="vibe-input" placeholder="一句话说明" :disabled="busy" />
        </div>
        <div class="vibe-pub-row vibe-pub-3">
          <div>
            <label>价格</label>
            <input
              v-model.number="pubPrice"
              type="number"
              min="0"
              step="0.01"
              class="vibe-input"
              :disabled="busy"
            />
          </div>
          <div>
            <label>artifact</label>
            <select v-model="pubArtifact" class="vibe-input" :disabled="busy">
              <option value="mod">mod</option>
              <option value="employee_pack">employee_pack</option>
            </select>
          </div>
          <div>
            <label>行业</label>
            <input v-model="pubIndustry" class="vibe-input" placeholder="通用" :disabled="busy" />
          </div>
        </div>
      </div>

      <div class="vibe-actions">
        <button type="button" class="btn btn-primary" :disabled="busy || !brief.trim()" @click="submit">
          {{ busy ? '执行中…' : (publishAfter && !dryRun ? '生成 → 试跑 → 上架' : '生成 → 试跑') }}
        </button>
      </div>
    </div>

    <div v-if="error" class="vibe-error">{{ error }}</div>

    <article v-if="result" class="vibe-result">
      <div class="vibe-result-head">
        <h3>执行结果</h3>
        <button
          v-if="hasHandoffTarget"
          type="button"
          class="btn btn-handoff"
          title="将生成的技能代码与配置带入员工制作工作台"
          @click="sendToEmployeeWorkbench"
        >
          带入员工工作台 →
        </button>
      </div>
      <p v-if="result.skill?.skill_id" class="muted small">
        skill_id: <code>{{ result.skill.skill_id }}</code>
      </p>
      <details open>
        <summary>生成代码</summary>
        <pre class="vibe-code">{{ resultCode }}</pre>
      </details>
      <details v-if="result.run">
        <summary>试运行输出</summary>
        <pre class="vibe-code">{{ JSON.stringify(result.run, null, 2) }}</pre>
      </details>
      <details v-if="result.publish">
        <summary>上架结果</summary>
        <pre class="vibe-code">{{ JSON.stringify(result.publish, null, 2) }}</pre>
      </details>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { requestJson } from '../../infrastructure/http/client'

const req = requestJson
const router = useRouter()

/** sessionStorage key 与 EmployeeAuthoringView 约定一致 */
const EMP_VIBE_HANDOFF_KEY = 'modstore_emp_vibe_handoff'

const brief = ref('')
const runInputJson = ref('{}')
const dryRun = ref(false)
const publishAfter = ref(false)

const pkgId = ref('')
const pubName = ref('')
const pubDescription = ref('')
const pubPrice = ref(0)
const pubArtifact = ref<'mod' | 'employee_pack'>('mod')
const pubIndustry = ref('通用')

const busy = ref(false)
const error = ref('')
const result = ref<any>(null)

const resultCode = computed(() => String(result.value?.skill?.code || result.value?.skill?.code_excerpt || ''))

const hasHandoffTarget = computed(() => !!result.value?.skill?.skill_id || !!result.value?.skill?.code)

async function submit() {
  busy.value = true
  error.value = ''
  result.value = null
  let runInput: Record<string, unknown> = {}
  try {
    runInput = runInputJson.value.trim() ? JSON.parse(runInputJson.value) : {}
  } catch (e) {
    error.value = `试运行 input 不是合法 JSON: ${e}`
    busy.value = false
    return
  }
  try {
    const body: Record<string, unknown> = {
      brief: brief.value.trim(),
      run_input: runInput,
      dry_run: dryRun.value,
    }
    if (publishAfter.value && !dryRun.value) {
      if (!pkgId.value.trim()) {
        error.value = '上架时必须填 pkg_id'
        busy.value = false
        return
      }
      body.publish = {
        pkg_id: pkgId.value.trim(),
        name: pubName.value.trim(),
        description: pubDescription.value.trim(),
        price: Number(pubPrice.value || 0),
        artifact: pubArtifact.value,
        industry: pubIndustry.value.trim() || '通用',
      }
    }
    const data = await req('/api/workbench/vibe-code-skill', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    result.value = data
    if (data?.error) {
      error.value = String(data.error)
    }
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    busy.value = false
  }
}

function sendToEmployeeWorkbench() {
  const skill = result.value?.skill
  if (!skill) return
  const payload = {
    skill_id: String(skill.skill_id || '').trim(),
    brief: brief.value.trim(),
    code: String(skill.code || skill.code_excerpt || '').trim(),
    pkg_id: String(result.value?.publish?.pkg_id || pkgId.value || '').trim(),
    name: String(result.value?.publish?.name || pubName.value || '').trim(),
    description: String(result.value?.publish?.description || pubDescription.value || brief.value || '').trim(),
  }
  try {
    sessionStorage.setItem(EMP_VIBE_HANDOFF_KEY, JSON.stringify(payload))
  } catch {
    /* ignore storage errors */
  }
  void router.push({ name: 'workbench-employee', query: { fromVibe: '1' } })
}
</script>

<style scoped>
.workbench-panel {
  min-height: 0;
  height: 100%;
  overflow: auto;
}

.vibe-code-panel {
  padding: 1rem 1.4rem 2rem;
  color: #d4dce6;
  background: #07090c;
}

.vibe-head h2 {
  font-size: 1.15rem;
  margin: 0 0 0.35rem;
}

.vibe-head .muted {
  color: rgba(212, 220, 230, 0.7);
}

.vibe-form {
  margin-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.9rem 1rem 1rem;
}

.vibe-input {
  width: 100%;
  background: #0d1117;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  color: #e6edf3;
  padding: 0.5rem 0.6rem;
  font-family: inherit;
  font-size: 0.9rem;
}

.vibe-input.mono {
  font-family: ui-monospace, SF Mono, Menlo, monospace;
  font-size: 0.85rem;
}

.vibe-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.vibe-row-inline {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
}

.cb {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}

.vibe-publish {
  border-top: 1px dashed rgba(255, 255, 255, 0.1);
  padding-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.vibe-pub-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.vibe-pub-3 {
  flex-direction: row;
  gap: 0.6rem;
}

.vibe-pub-3 > div {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.req {
  color: #f97316;
}

.vibe-actions {
  margin-top: 0.5rem;
}

.btn {
  padding: 0.5rem 1.1rem;
  border-radius: 6px;
  border: 1px solid transparent;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  background: #f97316;
  color: #fff;
}

.btn-primary[disabled] {
  background: rgba(249, 115, 22, 0.4);
  cursor: not-allowed;
}

.vibe-error {
  margin-top: 1rem;
  color: #f87171;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.3);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.9rem;
}

.vibe-result {
  margin-top: 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.9rem 1rem 1rem;
}

.vibe-result-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.vibe-result h3 {
  margin: 0;
  font-size: 1rem;
}

.btn-handoff {
  background: linear-gradient(135deg, #6c63ff 0%, #a855f7 100%);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.35rem 0.9rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity 0.15s;
}

.btn-handoff:hover {
  opacity: 0.88;
}

.vibe-code {
  background: #0d1117;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
  overflow: auto;
  max-height: 380px;
  font: 0.8rem/1.5 ui-monospace, SF Mono, Menlo, monospace;
  white-space: pre-wrap;
}

label {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.7);
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Light theme overrides
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
html[data-workbench-theme='light'] .vibe-code-panel {
  color: #1d1d1f;
  background: #f5f5f7;
}
html[data-workbench-theme='light'] .vibe-head .muted {
  color: #86868b;
}
html[data-workbench-theme='light'] .vibe-form {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .vibe-input {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .vibe-publish {
  border-top-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .req {
  color: #dc2626;
}
html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #fff;
}
html[data-workbench-theme='light'] .btn-primary[disabled] {
  background: rgba(0, 113, 227, 0.4);
}
html[data-workbench-theme='light'] .vibe-error {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.06);
  border-color: rgba(220, 38, 38, 0.2);
}
html[data-workbench-theme='light'] .vibe-result {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .vibe-result h3 {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .btn-handoff {
  background: #0071e3;
}
html[data-workbench-theme='light'] .vibe-code {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] label {
  color: #86868b;
}
</style>
