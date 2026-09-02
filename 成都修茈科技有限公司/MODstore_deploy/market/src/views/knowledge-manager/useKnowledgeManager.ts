/**
 * 知识库管理视图逻辑（由 KnowledgeManagerView.vue 原单文件机械迁出，行为不变）。
 * 覆盖：状态/集合加载、文档上传删除、创建集合与共享授权弹窗。
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../../api'
import { useAuthStore } from '../../stores/auth'

export interface Collection {
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

export interface DocItem {
  doc_id: string
  filename: string
  size_bytes: number
  chunk_count: number
  created_at: number
}

export interface KnowledgeStatus {
  engine?: { backend?: string; persist_dir?: string }
  embedding?: { model?: string; dim?: number; configured?: boolean }
  owned_collections?: number
}

export const ACCEPT = '.txt,.md,.json,.csv,.pdf,.docx,.xlsx'

export function useKnowledgeManager() {
  const authStore = useAuthStore()
  const myUserId = computed<string>(() => {
    const uid = authStore.user?.id
    return uid != null ? String(uid) : ''
  })

  const status = ref<KnowledgeStatus | null>(null)
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
      status.value = (await api.knowledgeV2Status()) as KnowledgeStatus
    } catch (e: unknown) {
      status.value = null
      if (e instanceof Error && e.message) error.value = e.message
    }
  }

  async function loadCollections() {
    loading.value = true
    error.value = ''
    try {
      const res = (await api.knowledgeV2ListCollections()) as { collections?: Collection[] }
      collections.value = Array.isArray(res?.collections) ? res.collections : []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
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
      const res = (await api.knowledgeV2ListDocuments(coll.id)) as { documents?: DocItem[] }
      docsByColl[coll.id] = {
        docs: Array.isArray(res?.documents) ? res.documents : [],
      }
    } catch (e: unknown) {
      docsByColl[coll.id] = { docs: [], error: e instanceof Error ? e.message : String(e) }
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
    } catch (e: unknown) {
      createError.value = e instanceof Error ? e.message : String(e)
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
    } catch (e: unknown) {
      shareError.value = e instanceof Error ? e.message : String(e)
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
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function deleteDoc(coll: Collection, doc: DocItem) {
    if (!canWrite(coll)) return
    if (!confirm(`确认删除文档「${doc.filename || doc.doc_id}」？`)) return
    try {
      await api.knowledgeV2DeleteDocument(coll.id, doc.doc_id)
      await loadDocs(coll)
      await loadCollections()
    } catch (e: unknown) {
      docsByColl[coll.id] = {
        ...(docsByColl[coll.id] || { docs: [] }),
        error: e instanceof Error ? e.message : String(e),
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
    } catch (e: unknown) {
      docsByColl[coll.id] = {
        ...(docsByColl[coll.id] || { docs: [] }),
        error: e instanceof Error ? e.message : String(e),
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

  return {
    ACCEPT,
    status,
    collections,
    docsByColl,
    loading,
    error,
    openedId,
    uploading,
    uploadingCollId,
    showCreate,
    creating,
    createError,
    createForm,
    showShare,
    sharing,
    shareError,
    shareForm,
    groupedCollections,
    granteeIdPlaceholder,
    ownerKindLabel,
    visibilityLabel,
    canAdmin,
    canWrite,
    formatBytes,
    formatDate,
    loadStatus,
    loadCollections,
    loadDocs,
    toggleCollection,
    openCreateModal,
    submitCreate,
    openShareModal,
    closeShareModal,
    submitShare,
    deleteCollection,
    deleteDoc,
    onPickFile,
  }
}
