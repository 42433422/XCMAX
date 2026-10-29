<template>
  <section v-if="canManage" class="platform-model" aria-labelledby="platform-model-title" :aria-busy="busy">
    <header class="platform-model__header">
      <div>
        <h2 id="platform-model-title">平台模型配置</h2>
        <p>管理员配置 · 平台共用密钥 · 与用户自带密钥（BYOK）分开管理</p>
      </div>
      <button type="button" class="btn btn-sm btn-secondary" :disabled="busy" @click="load">重新读取</button>
    </header>
    <div class="platform-model__scope">
      <strong>实际生效范围</strong>
      <p>{{ state?.scope_description || '读取成功后显示当前平台网关的实际配置。' }}</p>
      <p>{{ state?.byok_policy || '用户 BYOK 与个人显式模型选择由服务端独立处理。' }}</p>
      <p>独立部署、桌面内网模式和环境变量直连模型不会自动同步此配置。</p>
      <p v-if="state">平台管理配置的默认供应商：{{ defaultLabel }}</p>
    </div>
    <p v-if="loading" role="status">正在读取平台配置…</p>
    <p v-if="loadError" role="alert" class="platform-model__error">{{ loadError }}</p>
    <p v-if="state && !state.encryption_ready" role="alert" class="platform-model__error">
      服务端密钥加密尚未就绪，暂时不能保存。请先配置服务端加密主密钥，再重新读取。
    </p>
    <form @submit.prevent="save">
      <fieldset :disabled="!loaded || busy">
        <legend class="platform-model__legend">供应商与默认模型</legend>
        <div class="platform-model__fields">
          <label for="platform-model-provider">模型供应商
            <select id="platform-model-provider" v-model="provider">
              <option value="" disabled>请选择供应商</option>
              <option v-for="row in state?.providers || []" :key="row.provider" :value="row.provider">{{ row.label }}</option>
            </select>
          </label>
          <label for="platform-model-url">API 地址
            <input id="platform-model-url" v-model="draft.base_url" type="url" maxlength="2048" placeholder="https://api.example.com/v1" autocomplete="off" />
          </label>
          <label for="platform-model-id">模型 ID
            <input id="platform-model-id" v-model="draft.model" maxlength="256" placeholder="供应商提供的模型 ID" autocomplete="off" />
          </label>
          <label for="platform-model-name">展示名称
            <input id="platform-model-name" v-model="draft.display_name" maxlength="128" placeholder="便于识别的模型名称" autocomplete="off" />
          </label>
          <label for="platform-model-key">平台密钥
            <input id="platform-model-key" v-model="keyDraft" type="password" maxlength="4096" autocomplete="new-password" spellcheck="false" :placeholder="selected?.has_key ? '留空保留当前供应商密钥' : '请输入平台密钥'" aria-describedby="platform-model-key-hint" />
          </label>
          <div class="platform-model__key-state" id="platform-model-key-hint">
            <span>已保存密钥：<code>{{ selected?.masked_key || '未配置' }}</code></span>
            <span>来源：{{ keySource }}</span>
            <span>完整密钥只提交给服务端，不会读回。修改 API 地址时必须重新输入密钥。</span>
          </div>
        </div>
        <p class="platform-model__hint">使用 OpenAI 兼容 API 根地址（可包含 /v1），不要填写 /chat/completions，也不要在地址中携带密钥。</p>
        <label class="platform-model__default">
          <input v-model="draft.make_default" type="checkbox" :disabled="selected?.is_default" />
          设为平台默认模型（用于共享平台网关的默认请求，保留用户显式选择与 BYOK 优先级）
        </label>
        <div class="platform-model__actions">
          <button type="button" class="btn btn-sm btn-secondary" :disabled="!selected" @click="testConnection">{{ pending === 'test' ? '测试中…' : '连接测试' }}</button>
          <button type="submit" class="btn btn-sm btn-primary" :disabled="!selected || !state?.encryption_ready">{{ pending === 'save' ? '保存中…' : '保存平台配置' }}</button>
        </div>
      </fieldset>
    </form>
    <p v-if="actionError" role="alert" class="platform-model__error">{{ actionError }}</p>
    <p v-if="testMessage" role="status" class="platform-model__success">{{ testMessage }}</p>
    <p v-if="saveMessage" role="status" class="platform-model__success">{{ saveMessage }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { platformModelApi, type PlatformModelDraft, type PlatformModelList } from '@/api/platformModel'

const props = defineProps<{ canManage: boolean }>()
const state = ref<PlatformModelList | null>(null)
const provider = ref('')
const draft = reactive({ base_url: '', model: '', display_name: '', make_default: false })
const keyDraft = ref('')
const loading = ref(false)
const loaded = ref(false)
const pending = ref<'' | 'test' | 'save'>('')
const loadError = ref('')
const actionError = ref('')
const testMessage = ref('')
const saveMessage = ref('')
const busy = computed(() => loading.value || pending.value !== '')
const selected = computed(() => state.value?.providers.find(row => row.provider === provider.value))
const defaultLabel = computed(() => state.value?.providers.find(row => row.provider === state.value?.default_provider)?.label || '未设置（沿用现有路由）')
const keySource = computed(() => ({ stored: '服务端加密配置', environment: '服务端环境变量', none: '未配置' })[selected.value?.source || 'none'])
let request: AbortController | null = null
let epoch = 0

function clearMessages() { actionError.value = ''; testMessage.value = ''; saveMessage.value = '' }
function resetDraft() {
  const row = selected.value
  Object.assign(draft, { base_url: row?.base_url || '', model: row?.model || '', display_name: row?.display_name || '', make_default: Boolean(row?.is_default || !state.value?.default_provider) })
  keyDraft.value = ''
  clearMessages()
}
watch(provider, resetDraft, { flush: 'sync' })
watch([draft, keyDraft], clearMessages, { flush: 'sync' })

function failure(error: unknown, operation: string): string {
  // Never render upstream errors, request bodies or provider responses: they may echo credentials.
  const status = (error as { status?: number } | null)?.status
  if (status === 401) return '管理员登录已失效，请重新登录。'
  if (status === 403) return '权限校验失败，请使用平台管理员账号重新登录后再试。'
  if (status === 409) return '配置已被其他管理员修改，请重新读取后再保存。'
  if (status === 400 || status === 422) return `${operation}失败，请检查 API 地址、模型 ID 和密钥格式。`
  if (status === 503) return `${operation}失败，服务端配置暂不可用，请检查密钥加密与网关状态。`
  if (status === 504 || status === 0) return `${operation}未完成，请检查网络或稍后重试；可重新读取确认当前保存状态。`
  if (status === 502) return `${operation}失败，上游模型服务未通过连接验证，请检查地址、模型与密钥。`
  return `${operation}失败，请稍后重试；可重新读取确认当前保存状态。`
}

async function load() {
  if (!props.canManage || busy.value) return
  const current = ++epoch
  request = new AbortController()
  loading.value = true
  loaded.value = false
  loadError.value = ''
  keyDraft.value = ''
  clearMessages()
  try {
    const result = await platformModelApi.list(request.signal)
    if (current !== epoch || !props.canManage) return
    if (!result.ok || !Array.isArray(result.providers) || !result.providers.length) throw new Error('invalid configuration')
    state.value = result
    if (!result.providers.some(row => row.provider === provider.value)) provider.value = result.providers.find(row => row.provider === result.default_provider)?.provider || result.providers[0].provider
    resetDraft()
    loaded.value = true
  } catch (error) {
    if (current === epoch && props.canManage) { state.value = null; loadError.value = failure(error, '读取平台配置') }
  } finally {
    if (current === epoch) { loading.value = false; request = null }
  }
}

function payload(): PlatformModelDraft | null {
  clearMessages()
  if (!props.canManage || !loaded.value || busy.value || !selected.value) return null
  const base = draft.base_url.trim().replace(/\/+$/, '')
  let url: URL
  try { url = new URL(base) } catch { actionError.value = '请输入有效的 HTTPS API 地址。'; return null }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || base.endsWith('/chat/completions')) {
    actionError.value = 'API 地址必须使用 HTTPS，不含账号、密钥、查询参数或 /chat/completions。'
    return null
  }
  if (!draft.model.trim() || !draft.display_name.trim()) { actionError.value = '请填写模型 ID 和展示名称。'; return null }
  const key = keyDraft.value.trim()
  if ((!selected.value.has_key || base !== selected.value.base_url.replace(/\/+$/, '')) && !key) {
    actionError.value = '首次配置或修改 API 地址时，请重新输入平台密钥。'
    return null
  }
  return { base_url: base, model: draft.model.trim(), display_name: draft.display_name.trim(), make_default: draft.make_default, expected_revision: selected.value.revision, ...(key ? { api_key: key } : {}) }
}

async function perform(operation: 'test' | 'save') {
  if (operation === 'save' && !state.value?.encryption_ready) return
  const body = payload()
  if (!body) return
  const current = ++epoch
  const selectedProvider = provider.value
  request = new AbortController()
  pending.value = operation
  try {
    if (operation === 'test') {
      const result = await platformModelApi.test(selectedProvider, body, request.signal)
      if (current !== epoch || !props.canManage) return
      if (!result.ok) throw new Error('test failed')
      testMessage.value = `连接测试成功（${Math.round(result.latency_ms)} ms），尚未保存此配置。`
    } else {
      const result = await platformModelApi.save(selectedProvider, body, request.signal)
      if (current !== epoch || !props.canManage) return
      if (!result.ok || result.config?.provider !== selectedProvider) throw new Error('save failed')
      if (state.value) {
        state.value = { ...state.value, default_provider: result.default_provider, effective_scope: result.effective_scope, scope_description: result.scope_description, byok_policy: result.byok_policy,
          providers: state.value.providers.map(row => row.provider === selectedProvider ? { ...row, ...result.config } : { ...row, is_default: row.provider === result.default_provider }) }
      }
      resetDraft()
      saveMessage.value = '平台模型配置已保存，后续共享网关请求按上述范围生效。'
    }
  } catch (error) {
    if (current !== epoch || !props.canManage) return
    const status = (error as { status?: number } | null)?.status
    if (status === 401 || status === 403 || status === 409) { loaded.value = false; keyDraft.value = '' }
    actionError.value = failure(error, operation === 'test' ? '连接测试' : '保存平台配置')
  } finally {
    if (current === epoch) { pending.value = ''; request = null }
    delete body.api_key
  }
}
const save = () => perform('save')
const testConnection = () => perform('test')

function dispose() {
  epoch++
  request?.abort()
  request = null
  keyDraft.value = ''
  state.value = null
  provider.value = ''
  loaded.value = false
  loading.value = false
  pending.value = ''
  loadError.value = ''
  resetDraft()
}
watch(() => props.canManage, allowed => { if (allowed) void load(); else dispose() }, { immediate: true })
onBeforeUnmount(dispose)
</script>

<style scoped>
.platform-model { margin: 20px; padding: 20px; border: 1px solid var(--border-color, #d8e0ea); border-radius: 12px; }
.platform-model__header, .platform-model__actions { display: flex; gap: 12px; align-items: center; justify-content: space-between; }
.platform-model h2 { margin: 0 0 8px; font-size: 18px; }
.platform-model p { line-height: 1.6; margin: 8px 0; }
.platform-model__scope { padding: 12px 16px; margin: 16px 0; border-radius: 8px; background: var(--bg-secondary, #f3f6fb); }
.platform-model fieldset { border: 0; margin: 0; padding: 0; }
.platform-model__legend { font-weight: 600; margin-bottom: 12px; }
.platform-model__fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.platform-model__fields label, .platform-model__key-state { display: flex; flex-direction: column; gap: 6px; }
.platform-model input:not([type='checkbox']), .platform-model select { padding: 10px; min-width: 0; width: 100%; box-sizing: border-box; border: 1px solid var(--border-color, #c7d0dd); border-radius: 6px; background: var(--bg-primary, #fff); color: inherit; }
.platform-model__key-state, .platform-model__hint, .platform-model__header p { font-size: 13px; color: var(--text-secondary, #526174); }
.platform-model__default { display: flex; gap: 8px; align-items: flex-start; margin: 16px 0; line-height: 1.5; }
.platform-model__actions { justify-content: flex-start; }
.platform-model__error { color: var(--danger-color, #b42318); }
.platform-model__success { color: var(--success-color, #167445); }
@media (max-width: 640px) { .platform-model { margin: 12px; padding: 16px; } .platform-model__fields { grid-template-columns: 1fr; } .platform-model__header { align-items: flex-start; flex-direction: column; } }
</style>
