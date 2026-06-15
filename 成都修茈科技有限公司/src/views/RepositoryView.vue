<template>
  <div class="repo-page">
    <div class="page-header">
      <h1 class="page-title">仓库</h1>
      <p class="page-desc">管理所有 Mod 源码，新建、导入、推送、拉取；Mod 制作请在卡片上点「制作 / 编辑」</p>
      <div class="header-actions">
        <button class="btn btn-primary" @click="showCreate = true">新建 Mod</button>
        <label class="btn">
          导入 ZIP
          <input type="file" accept=".zip" class="hidden-input" @change="onImport" />
        </label>
        <button class="btn" :disabled="syncing" @click="doPull">从 XCAGI 拉回</button>
        <button class="btn" :disabled="syncing" @click="doPush">推送到 XCAGI</button>
      </div>
    </div>

    <div v-if="message" :class="['flash', messageOk ? 'flash-ok' : 'flash-err']">{{ message }}</div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="mods.length" class="mods-grid">
      <div v-for="m in mods" :key="m.id" class="mod-card">
        <div class="mod-card-badges">
          <span class="badge" :class="m.ok ? 'badge-ok' : 'badge-warn'">{{ m.ok ? '通过' : '待修正' }}</span>
          <span v-if="m.primary" class="badge badge-primary">主扩展</span>
        </div>
        <h3 class="mod-card-name">{{ m.name || m.id }}</h3>
        <p v-if="getBlurb(m)" class="mod-card-blurb">{{ getBlurb(m) }}</p>
        <div class="mod-card-id">{{ m.id }} · v{{ m.version || '?' }}</div>
        <div v-if="m.warnings?.length" class="mod-card-warn">{{ m.warnings[0] }}{{ m.warnings.length > 1 ? ' …' : '' }}</div>
        <div v-if="m.error" class="mod-card-warn">{{ m.error }}</div>
        <div class="mod-card-actions">
          <button class="btn btn-sm" @click="viewMod(m.id)">制作 / 编辑</button>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <p>库中暂无 Mod</p>
      <p class="empty-hint">点击上方「新建 Mod」或「导入 ZIP」开始使用</p>
    </div>

    <!-- 新建 Mod 弹窗 -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h2 class="modal-title">新建 Mod</h2>
        <div class="form-group">
          <label class="label">目录名 / manifest.id</label>
          <input v-model="createId" class="input" placeholder="如 acme-pro" />
        </div>
        <div class="form-group">
          <label class="label">显示名称</label>
          <input v-model="createName" class="input" placeholder="客户或产品名" />
        </div>
        <div class="modal-actions">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn btn-primary" @click="submitCreate">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const mods = ref([])
const loading = ref(true)
const message = ref('')
const messageOk = ref(true)
const syncing = ref(false)
const showCreate = ref(false)
const createId = ref('')
const createName = ref('')

function flash(msg, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 5000)
}

function getBlurb(m) {
  if (!m || typeof m !== 'object') return ''
  const b = typeof m.library_blurb === 'string' ? m.library_blurb.trim() : ''
  if (b) return b
  const d = typeof m.description === 'string' ? m.description.trim() : ''
  if (!d) return ''
  const one = d.replace(/\s+/g, ' ')
  return one.length > 120 ? `${one.slice(0, 117)}…` : one
}

function viewMod(id) {
  router.push({ name: 'mod-authoring', params: { modId: id } })
}

async function load() {
  loading.value = true
  try {
    const res = await api.listMods()
    mods.value = Array.isArray(res?.data) ? res.data : []
  } catch (e) {
    flash('加载仓库失败: ' + (e.message || String(e)), false)
    mods.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  try {
    const res = await api.createMod(createId.value, createName.value)
    const newId = res.id
    showCreate.value = false
    createId.value = ''
    createName.value = ''
    flash(`已创建 ${newId}`)
    await load()
    router.push({ name: 'mod-authoring', params: { modId: newId } })
  } catch (e) {
    flash(e.message || String(e), false)
  }
}

async function onImport(ev) {
  const f = ev.target.files?.[0]
  ev.target.value = ''
  if (!f) return
  try {
    const res = await api.importZIP(f, true)
    flash(`已导入 ${res.id}`)
    await load()
  } catch (e) {
    flash(e.message || String(e), false)
  }
}

async function doPull() {
  syncing.value = true
  try {
    const res = await api.pull(null)
    flash(`已拉回: ${(res.pulled || []).join(', ') || '无'}`)
    await load()
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    syncing.value = false
  }
}

async function doPush() {
  syncing.value = true
  try {
    const res = await api.push(null)
    flash(`已部署: ${(res.deployed || []).join(', ') || '无'}`)
    await load()
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    syncing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.repo-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.page-header {
  margin-bottom: 2rem;
}

.page-title {
  font-size: 1.75rem;
  margin: 0 0 0.5rem;
  color: #ffffff;
}

.page-desc {
  font-size: 0.9rem;
  color: rgba(255,255,255,0.4);
  margin: 0 0 1.25rem;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.hidden-input {
  display: none;
}

.flash {
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.flash-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.flash-err {
  background: rgba(255,80,80,0.1);
  color: #ff6b6b;
}

.loading {
  text-align: center;
  padding: 3rem;
  color: rgba(255,255,255,0.3);
}

.mods-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.mod-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
  transition: all 0.2s;
}

.mod-card:hover {
  border-color: rgba(255,255,255,0.2);
  transform: translateY(-2px);
}

.mod-card-badges {
  display: flex;
  gap: 0.375rem;
  margin-bottom: 0.75rem;
}

.mod-card-name {
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.375rem;
}

.mod-card-blurb {
  font-size: 0.8125rem;
  color: rgba(255,255,255,0.5);
  line-height: 1.5;
  margin: 0 0 0.625rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mod-card-id {
  font-size: 0.75rem;
  color: rgba(255,255,255,0.3);
  font-family: monospace;
  margin-bottom: 0.5rem;
}

.mod-card-warn {
  font-size: 0.75rem;
  color: #fbbf24;
}

.mod-card-actions {
  margin-top: 1rem;
}

.empty-state {
  text-align: center;
  padding: 4rem 1rem;
  color: rgba(255,255,255,0.3);
}

.empty-state p {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
}

.empty-hint {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.2);
}

.btn {
  padding: 0.5rem 1rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255,255,255,0.7);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  background: rgba(255,255,255,0.06);
  color: #ffffff;
}

.btn-primary {
  background: #ffffff;
  color: #0a0a0a;
  border: none;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.1875rem 0.5rem;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 500;
}

.badge-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.badge-warn {
  background: rgba(251,191,36,0.1);
  color: #fbbf24;
}

.badge-primary {
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.5);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.modal {
  width: 100%;
  max-width: 420px;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  padding: 1.5rem;
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0 0 1.25rem;
  color: #ffffff;
}

.form-group {
  margin-bottom: 1rem;
}

.label {
  display: block;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.5);
  margin-bottom: 0.4rem;
}

.input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
  color: #ffffff;
  font-size: 0.9rem;
  outline: none;
}

.input:focus {
  border-color: rgba(255,255,255,0.3);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}
</style>
