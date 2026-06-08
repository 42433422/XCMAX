<template>
  <div class="kb-mgr">
    <header class="kb-header">
      <div>
        <h1 class="page-title">知识库</h1>
        <p class="kb-sub">
          上传资料形成集合，AI 员工与工作流会按权限自动检索；可分享给员工、工作流或其他用户。
        </p>
      </div>
      <button class="btn btn-primary-solid" type="button" @click="openCreateModal">+ 新建集合</button>
    </header>

    <section class="kb-status" v-if="status">
      <div class="kb-status__item">
        <span class="kb-status__label">引擎</span>
        <span class="kb-status__value">
          {{ status.engine?.backend || '-' }}
          <span class="kb-status__hint" v-if="status.engine?.persist_dir">· {{ status.engine.persist_dir }}</span>
        </span>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">Embedding</span>
        <span class="kb-status__value">
          {{ status.embedding?.model || '-' }} · dim {{ status.embedding?.dim || 0 }}
          <span class="kb-status__hint" v-if="!status.embedding?.configured">（未配置 API Key）</span>
        </span>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">我的集合</span>
        <span class="kb-status__value">{{ status.owned_collections || 0 }} 个</span>
      </div>
    </section>

    <div v-if="loading && !collections.length" class="kb-loading">加载中…</div>
    <div v-if="error" class="flash flash-err">{{ error }}</div>

    <section v-for="group in groupedCollections" :key="group.key" class="kb-section">
      <h2 class="kb-section__title">
        {{ group.title }}
        <span class="kb-section__count">· {{ group.items.length }}</span>
      </h2>
      <div v-if="!group.items.length" class="kb-empty">{{ group.empty }}</div>
      <div v-else class="kb-grid">
        <article
          v-for="coll in group.items"
          :key="coll.id"
          class="kb-card"
          :class="{ 'kb-card--open': openedId === coll.id }"
        >
          <header class="kb-card__head" @click="toggleCollection(coll)">
            <h3 class="kb-card__title">{{ coll.name }}</h3>
            <span class="kb-card__meta">
              {{ ownerKindLabel(coll.owner_kind) }}
              · {{ coll.chunk_count || 0 }} chunks
              · {{ visibilityLabel(coll.visibility) }}
            </span>
          </header>
          <p v-if="coll.description" class="kb-card__desc">{{ coll.description }}</p>

          <div v-if="openedId === coll.id" class="kb-card__body">
            <div class="kb-card__actions">
              <label class="btn btn-default kb-upload-btn">
                <input
                  type="file"
                  class="kb-upload-input"
                  :disabled="!canWrite(coll) || uploading"
                  :accept="ACCEPT"
                  @change="onPickFile($event, coll)"
                />
                <span>{{ uploading && uploadingCollId === coll.id ? '上传中…' : '+ 上传文档' }}</span>
              </label>
              <button
                class="btn btn-default"
                type="button"
                :disabled="!canAdmin(coll)"
                @click="openShareModal(coll)"
              >
                共享 / 授权
              </button>
              <button
                class="btn btn-danger"
                type="button"
                :disabled="!canAdmin(coll)"
                @click="deleteCollection(coll)"
              >
                删除集合
              </button>
            </div>

            <div v-if="docsByColl[coll.id]?.error" class="flash flash-err">
              {{ docsByColl[coll.id].error }}
            </div>
            <div v-if="!docsByColl[coll.id]?.docs?.length" class="kb-empty">
              暂无文档
            </div>
            <ul v-else class="kb-docs">
              <li v-for="doc in docsByColl[coll.id].docs" :key="doc.doc_id" class="kb-doc">
                <div class="kb-doc__name">{{ doc.filename || '(未命名)' }}</div>
                <div class="kb-doc__meta">
                  {{ formatBytes(doc.size_bytes) }} · {{ doc.chunk_count }} chunks
                  · {{ formatDate(doc.created_at) }}
                </div>
                <button
                  class="btn btn-link kb-doc__del"
                  type="button"
                  :disabled="!canWrite(coll)"
                  @click="deleteDoc(coll, doc)"
                >
                  删除
                </button>
              </li>
            </ul>
          </div>
        </article>
      </div>
    </section>

    <!-- 创建集合 -->
    <div v-if="showCreate" class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal__panel">
        <header class="kb-modal__head">
          <h3>新建集合</h3>
          <button class="btn btn-link" type="button" @click="showCreate = false">×</button>
        </header>
        <div class="kb-modal__body">
          <label class="kb-field">
            <span class="kb-field__label">名称</span>
            <input
              class="input"
              v-model.trim="createForm.name"
              maxlength="64"
              placeholder="如：业务 SOP / 产品手册"
            />
          </label>
          <label class="kb-field">
            <span class="kb-field__label">说明（可选）</span>
            <textarea class="input" v-model.trim="createForm.description" maxlength="500" rows="3"></textarea>
          </label>
          <label class="kb-field">
            <span class="kb-field__label">可见性</span>
            <select class="input" v-model="createForm.visibility">
              <option value="private">仅自己</option>
              <option value="shared">仅授权用户</option>
              <option value="public">所有登录用户可读</option>
            </select>
          </label>
          <div v-if="createError" class="flash flash-err">{{ createError }}</div>
        </div>
        <footer class="kb-modal__foot">
          <button class="btn btn-default" type="button" @click="showCreate = false">取消</button>
          <button
            class="btn btn-primary-solid"
            type="button"
            :disabled="!createForm.name || creating"
            @click="submitCreate"
          >
            {{ creating ? '创建中…' : '创建' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 共享 -->
    <div v-if="showShare" class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal__panel">
        <header class="kb-modal__head">
          <h3>共享 / 授权 · {{ shareForm.coll?.name }}</h3>
          <button class="btn btn-link" type="button" @click="closeShareModal">×</button>
        </header>
        <div class="kb-modal__body">
          <label class="kb-field">
            <span class="kb-field__label">授权给（owner kind）</span>
            <select class="input" v-model="shareForm.grantee_kind">
              <option value="user">用户</option>
              <option value="employee">AI 员工</option>
              <option value="workflow">工作流</option>
              <option value="org">组织</option>
            </select>
          </label>
          <label class="kb-field">
            <span class="kb-field__label">对应 ID</span>
            <input
              class="input"
              v-model.trim="shareForm.grantee_id"
              :placeholder="granteeIdPlaceholder"
              maxlength="64"
            />
          </label>
          <label class="kb-field">
            <span class="kb-field__label">权限</span>
            <select class="input" v-model="shareForm.permission">
              <option value="read">只读</option>
              <option value="write">可写</option>
              <option value="admin">管理员</option>
            </select>
          </label>
          <div v-if="shareError" class="flash flash-err">{{ shareError }}</div>
        </div>
        <footer class="kb-modal__foot">
          <button class="btn btn-default" type="button" @click="closeShareModal">取消</button>
          <button
            class="btn btn-primary-solid"
            type="button"
            :disabled="!shareForm.grantee_id || sharing"
            @click="submitShare"
          >
            {{ sharing ? '保存中…' : '保存授权' }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../api'
import { useAuthStore } from '../stores/auth'

interface Collection {
  id: number
  owner_kind: string
  owner_id: string
  name: string
  description?: string
  visibility?: string
  embedding_model?: string
  embedding_dim?: number
  chunk_count?: number
  created_at?: number
  updated_at?: number
}

interface DocItem {
  doc_id: string
  filename: string
  size_bytes: number
  chunk_count: number
  created_at: number
}

const ACCEPT = '.txt,.md,.json,.csv,.pdf,.docx,.xlsx'

const authStore = useAuthStore()
const myUserId = computed<string>(() => {
  const uid = (authStore.user as any)?.id
  return uid != null ? String(uid) : ''
})

const status = ref<any>(null)
const collections = ref<Collection[]>([])
const docsByColl = reactive<Record<number, { docs: DocItem[]; error?: string }>>({})

const loading = ref(false)
const error = ref('')
const openedId = ref<number | null>(null)

const uploading = ref(false)
const uploadingCollId = ref<number | null>(null)

const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = reactive({
  name: '',
  description: '',
  visibility: 'private',
})

const showShare = ref(false)
const sharing = ref(false)
const shareError = ref('')
const shareForm = reactive({
  coll: null as Collection | null,
  grantee_kind: 'user',
  grantee_id: '',
  permission: 'read',
})

const groupedCollections = computed(() => {
  const mine: Collection[] = []
  const shared: Collection[] = []
  const publicCols: Collection[] = []
  for (const c of collections.value) {
    const myOwned = c.owner_kind === 'user' && String(c.owner_id) === myUserId.value
    if (myOwned) {
      mine.push(c)
    } else if ((c.visibility || '') === 'public' && !myOwned) {
      publicCols.push(c)
    } else {
      shared.push(c)
    }
  }
  return [
    { key: 'mine', title: '我的集合', items: mine, empty: '还没有自己的集合，点右上角"新建集合"开始。' },
    { key: 'shared', title: '共享给我的 / 来自员工或工作流', items: shared, empty: '暂无共享给我的集合。' },
    { key: 'public', title: '公开可读', items: publicCols, empty: '暂无公开集合。' },
  ]
})

const granteeIdPlaceholder = computed(() => {
  switch (shareForm.grantee_kind) {
    case 'user':
      return '用户 ID（数字）'
    case 'employee':
      return '员工包 ID（如 builtin_workmate）'
    case 'workflow':
      return '工作流 ID（数字）'
    case 'org':
      return '组织 ID'
    default:
      return ''
  }
})

function ownerKindLabel(kind: string): string {
  return (
    {
      user: '用户',
      employee: 'AI 员工',
      workflow: '工作流',
      org: '组织',
    } as Record<string, string>
  )[kind] || kind
}

function visibilityLabel(v?: string): string {
  return (
    {
      private: '私有',
      shared: '授权可见',
      public: '公开可读',
    } as Record<string, string>
  )[v || 'private'] || (v || 'private')
}

function canAdmin(coll: Collection): boolean {
  return coll.owner_kind === 'user' && String(coll.owner_id) === myUserId.value
}

function canWrite(coll: Collection): boolean {
  return canAdmin(coll)
}

function formatBytes(n: number): string {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

function formatDate(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleString()
}

async function loadStatus() {
  try {
    status.value = await api.knowledgeV2Status()
  } catch (e: any) {
    status.value = null
    if (e?.message) error.value = e.message
  }
}

async function loadCollections() {
  loading.value = true
  error.value = ''
  try {
    const res: any = await api.knowledgeV2ListCollections()
    collections.value = Array.isArray(res?.collections) ? res.collections : []
  } catch (e: any) {
    error.value = e?.message || String(e)
    collections.value = []
  } finally {
    loading.value = false
  }
}

async function toggleCollection(coll: Collection) {
  if (openedId.value === coll.id) {
    openedId.value = null
    return
  }
  openedId.value = coll.id
  if (!docsByColl[coll.id]) {
    docsByColl[coll.id] = { docs: [] }
    await loadDocs(coll)
  }
}

async function loadDocs(coll: Collection) {
  try {
    const res: any = await api.knowledgeV2ListDocuments(coll.id)
    docsByColl[coll.id] = {
      docs: Array.isArray(res?.documents) ? res.documents : [],
    }
  } catch (e: any) {
    docsByColl[coll.id] = { docs: [], error: e?.message || String(e) }
  }
}

function openCreateModal() {
  createForm.name = ''
  createForm.description = ''
  createForm.visibility = 'private'
  createError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  createError.value = ''
  try {
    await api.knowledgeV2CreateCollection({
      name: createForm.name,
      description: createForm.description,
      visibility: createForm.visibility,
    })
    showCreate.value = false
    await Promise.all([loadCollections(), loadStatus()])
  } catch (e: any) {
    createError.value = e?.message || String(e)
  } finally {
    creating.value = false
  }
}

function openShareModal(coll: Collection) {
  shareForm.coll = coll
  shareForm.grantee_kind = 'user'
  shareForm.grantee_id = ''
  shareForm.permission = 'read'
  shareError.value = ''
  showShare.value = true
}

function closeShareModal() {
  showShare.value = false
  shareForm.coll = null
}

async function submitShare() {
  if (!shareForm.coll) return
  sharing.value = true
  shareError.value = ''
  try {
    await api.knowledgeV2ShareCollection(shareForm.coll.id, {
      grantee_kind: shareForm.grantee_kind,
      grantee_id: shareForm.grantee_id,
      permission: shareForm.permission,
    })
    closeShareModal()
  } catch (e: any) {
    shareError.value = e?.message || String(e)
  } finally {
    sharing.value = false
  }
}

async function deleteCollection(coll: Collection) {
  if (!canAdmin(coll)) return
  if (!confirm(`确认删除集合「${coll.name}」？所有文档与 chunks 将被清除。`)) return
  try {
    await api.knowledgeV2DeleteCollection(coll.id)
    if (openedId.value === coll.id) openedId.value = null
    delete docsByColl[coll.id]
    await Promise.all([loadCollections(), loadStatus()])
  } catch (e: any) {
    error.value = e?.message || String(e)
  }
}

async function deleteDoc(coll: Collection, doc: DocItem) {
  if (!canWrite(coll)) return
  if (!confirm(`确认删除文档「${doc.filename || doc.doc_id}」？`)) return
  try {
    await api.knowledgeV2DeleteDocument(coll.id, doc.doc_id)
    await loadDocs(coll)
    await loadCollections()
  } catch (e: any) {
    docsByColl[coll.id] = {
      ...(docsByColl[coll.id] || { docs: [] }),
      error: e?.message || String(e),
    }
  }
}

async function onPickFile(ev: Event, coll: Collection) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  uploadingCollId.value = coll.id
  try {
    await api.knowledgeV2UploadDocument(coll.id, file)
    await loadDocs(coll)
    await loadCollections()
  } catch (e: any) {
    docsByColl[coll.id] = {
      ...(docsByColl[coll.id] || { docs: [] }),
      error: e?.message || String(e),
    }
  } finally {
    uploading.value = false
    uploadingCollId.value = null
    input.value = ''
  }
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadCollections()])
})
</script>

<style scoped>
.kb-mgr {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}
.kb-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.kb-sub {
  color: #6b7280;
  margin: 4px 0 0;
  font-size: 14px;
}
.kb-status {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 12px 0 24px;
  padding: 12px 16px;
  background: var(--surface-2, #f7f7f9);
  border-radius: 12px;
}
.kb-status__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.kb-status__label {
  font-size: 12px;
  color: #9ca3af;
}
.kb-status__value {
  font-weight: 600;
  font-size: 14px;
}
.kb-status__hint {
  color: #9ca3af;
  font-weight: normal;
  font-size: 12px;
  margin-left: 4px;
}

.kb-section {
  margin-top: 24px;
}
.kb-section__title {
  font-size: 16px;
  margin: 0 0 8px;
  color: #374151;
}
.kb-section__count {
  font-weight: normal;
  color: #9ca3af;
  font-size: 13px;
  margin-left: 4px;
}
.kb-empty {
  color: #9ca3af;
  font-size: 13px;
  padding: 8px 0;
}
.kb-loading {
  color: #6b7280;
  padding: 24px 0;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.kb-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px 16px;
  background: white;
  transition: box-shadow 0.15s ease;
}
.kb-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.kb-card--open {
  grid-column: 1 / -1;
}
.kb-card__head {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kb-card__title {
  font-size: 15px;
  margin: 0;
}
.kb-card__meta {
  font-size: 12px;
  color: #6b7280;
}
.kb-card__desc {
  margin: 8px 0 0;
  font-size: 13px;
  color: #4b5563;
}
.kb-card__body {
  margin-top: 12px;
  border-top: 1px dashed #e5e7eb;
  padding-top: 12px;
}
.kb-card__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.kb-upload-btn {
  position: relative;
  cursor: pointer;
}
.kb-upload-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  width: 100%;
  height: 100%;
}
.kb-docs {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid #f3f4f6;
}
.kb-doc {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
  font-size: 13px;
}
.kb-doc__name {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-doc__meta {
  color: #9ca3af;
  font-size: 12px;
}

.kb-modal {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.kb-modal__panel {
  background: white;
  border-radius: 12px;
  width: min(480px, calc(100vw - 32px));
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}
.kb-modal__head {
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
}
.kb-modal__head h3 {
  margin: 0;
  font-size: 15px;
}
.kb-modal__body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.kb-modal__foot {
  padding: 12px 16px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.kb-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kb-field__label {
  font-size: 12px;
  color: #6b7280;
}
.flash {
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}
.flash-err {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

html[data-workbench-theme='light'] .kb-mgr { background: #f5f5f7; color: #1d1d1f; }
html[data-workbench-theme='light'] .page-title { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-sub { color: #86868b; }
html[data-workbench-theme='light'] .kb-status { background: #ffffff; border: 1px solid rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-status__label { color: #86868b; }
html[data-workbench-theme='light'] .kb-status__value { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-status__hint { color: #86868b; }
html[data-workbench-theme='light'] .kb-section__title { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-section__count { color: #86868b; }
html[data-workbench-theme='light'] .kb-empty { color: #86868b; }
html[data-workbench-theme='light'] .kb-loading { color: #86868b; }
html[data-workbench-theme='light'] .kb-card { background: #ffffff; border-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-card__title { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-card__meta { color: #86868b; }
html[data-workbench-theme='light'] .kb-card__desc { color: #515154; }
html[data-workbench-theme='light'] .kb-card__body { border-top-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-docs { border-top-color: rgba(0,0,0,0.04); }
html[data-workbench-theme='light'] .kb-doc { border-bottom-color: rgba(0,0,0,0.04); }
html[data-workbench-theme='light'] .kb-doc__name { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-doc__meta { color: #86868b; }
html[data-workbench-theme='light'] .kb-modal { background: rgba(0,0,0,0.3); }
html[data-workbench-theme='light'] .kb-modal__panel { background: #ffffff; box-shadow: 0 8px 32px rgba(0,0,0,0.12); }
html[data-workbench-theme='light'] .kb-modal__head { border-bottom-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-modal__head h3 { color: #1d1d1f; }
html[data-workbench-theme='light'] .kb-modal__foot { border-top-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .kb-field__label { color: #86868b; }
html[data-workbench-theme='light'] .input { border-color: rgba(0,0,0,0.1); background: #ffffff; color: #1d1d1f; }
html[data-workbench-theme='light'] .btn-primary-solid { background: #0071e3; color: #ffffff; }
html[data-workbench-theme='light'] .btn-default { background: rgba(0,0,0,0.03); color: #1d1d1f; border-color: rgba(0,0,0,0.1); }
html[data-workbench-theme='light'] .btn-danger { background: rgba(220,38,38,0.08); color: #dc2626; border-color: rgba(220,38,38,0.2); }
html[data-workbench-theme='light'] .btn-link { color: #0071e3; }
</style>
