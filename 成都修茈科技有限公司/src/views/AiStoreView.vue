<template>
  <div class="store-page">
    <header class="store-hero">
      <div class="store-hero-inner">
        <p class="store-eyebrow">XC AGI · AI 员工商店</p>
        <h1 class="store-title">按行业与类型挑选能力</h1>
        <p class="store-sub">
          浏览可购买的 MOD 与 AI 员工扩展；管理员上架时可填写「行业」便于归类。
        </p>
      </div>
    </header>

    <div class="store-toolbar">
      <div class="toolbar-row">
        <label class="sr-only" for="store-search">搜索</label>
        <input
          id="store-search"
          v-model="searchQ"
          class="input search-input"
          type="search"
          placeholder="搜索名称、包名、描述…"
          @keydown.enter.prevent="applyFilters"
        />
        <button type="button" class="btn btn-ghost" @click="applyFilters">搜索</button>
        <button type="button" class="btn btn-text" @click="resetFilters">重置</button>
      </div>

      <div class="filter-block">
        <span class="filter-label">行业</span>
        <div class="chip-row">
          <button
            type="button"
            class="chip"
            :class="{ active: !filters.industry }"
            @click="setIndustry('')"
          >
            全部
          </button>
          <button
            v-for="ind in facetIndustries"
            :key="'ind-' + ind"
            type="button"
            class="chip"
            :class="{ active: filters.industry === ind }"
            @click="setIndustry(ind)"
          >
            {{ ind }}
          </button>
        </div>
      </div>

      <div class="filter-block">
        <span class="filter-label">类型</span>
        <div class="chip-row">
          <button
            type="button"
            class="chip"
            :class="{ active: !filters.artifact }"
            @click="setArtifact('')"
          >
            全部
          </button>
          <button
            v-for="art in facetArtifacts"
            :key="'art-' + art"
            type="button"
            class="chip"
            :class="{ active: filters.artifact === art }"
            @click="setArtifact(art)"
          >
            {{ artifactLabel(art) }}
          </button>
        </div>
      </div>

      <div class="filter-block">
        <span class="filter-label">保密级</span>
        <div class="chip-row">
          <button type="button" class="chip" :class="{ active: !filters.securityLevel }" @click="setSecurityLevel('')">全部</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'personal' }" @click="setSecurityLevel('personal')">个人级</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'enterprise' }" @click="setSecurityLevel('enterprise')">企业级</button>
          <button type="button" class="chip" :class="{ active: filters.securityLevel === 'confidential' }" @click="setSecurityLevel('confidential')">保密级</button>
        </div>
      </div>
    </div>

    <div v-if="err" class="flash flash-err">{{ err }}</div>

    <div v-if="loading" class="state-msg">加载中…</div>
    <div v-else-if="!items.length" class="state-msg muted">暂无符合的商品，试试调整筛选或搜索。</div>
    <div v-else class="store-grid">
      <article v-for="item in items" :key="item.id" class="store-card">
        <div class="card-tags">
          <span class="tag tag-industry">{{ item.industry || '通用' }}</span>
          <span class="tag tag-type">{{ artifactLabel(item.artifact) }}</span>
          <span class="tag" :class="securityLevelClass(item.security_level)">{{ securityLabel(item.security_level) }}</span>
          <span v-if="item.purchased" class="tag tag-owned">已购</span>
        </div>
        <h2 class="card-title">{{ item.name }}</h2>
        <p class="card-desc">{{ truncate(item.description, 120) }}</p>
        <p class="card-meta">{{ item.pkg_id }} · v{{ item.version }}</p>
        <div class="card-footer">
          <span class="price" :class="{ free: item.price <= 0 }">
            {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
          </span>
          <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn btn-detail">
            详情
          </router-link>
        </div>
      </article>
    </div>

    <p v-if="!loading && total > items.length" class="pager-hint">共 {{ total }} 条，当前展示前 {{ items.length }} 条。</p>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { api } from '../api.js'

const ARTIFACT_LABELS = {
  mod: 'MOD 插件',
  employee_pack: 'AI 员工包',
  bundle: '资源包',
  surface: '界面扩展',
}

const SECURITY_LABELS = {
  personal: '个人',
  enterprise: '企业',
  confidential: '保密',
}

const loading = ref(true)
const err = ref('')
const items = ref([])
const total = ref(0)
const searchQ = ref('')
const appliedQ = ref('')
const facets = ref({ industries: [], artifacts: [], security_levels: [] })

const filters = reactive({
  industry: '',
  artifact: '',
  securityLevel: '',
})

const facetIndustries = computed(() => facets.value.industries || [])
const facetArtifacts = computed(() => facets.value.artifacts || [])
const facetSecurityLevels = computed(() => facets.value.security_levels || [])

function artifactLabel(art) {
  return ARTIFACT_LABELS[art] || art || '其他'
}

function securityLabel(level) {
  return SECURITY_LABELS[level] || '个人'
}

function securityLevelClass(level) {
  if (level === 'confidential') return 'tag-confidential'
  if (level === 'enterprise') return 'tag-enterprise'
  return 'tag-personal'
}

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}

async function loadFacets() {
  try {
    const res = await api.catalogFacets()
    facets.value = {
      industries: res.industries || [],
      artifacts: res.artifacts || [],
      security_levels: res.security_levels || [],
    }
  } catch {
    facets.value = { industries: [], artifacts: [], security_levels: [] }
  }
}

async function loadItems() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.catalog(appliedQ.value, filters.artifact, 80, 0, filters.industry, filters.securityLevel)
    items.value = res.items || []
    total.value = res.total ?? items.value.length
  } catch (e) {
    err.value = e.message || String(e)
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function setIndustry(v) {
  filters.industry = v
}

function setArtifact(v) {
  filters.artifact = v
}

function setSecurityLevel(v) {
  filters.securityLevel = v
}

function applyFilters() {
  appliedQ.value = searchQ.value.trim()
  loadItems()
}

function resetFilters() {
  searchQ.value = ''
  appliedQ.value = ''
  filters.industry = ''
  filters.artifact = ''
  filters.securityLevel = ''
  loadItems()
}

watch(
  () => [filters.industry, filters.artifact, filters.securityLevel],
  () => {
    loadItems()
  },
)

onMounted(async () => {
  await loadFacets()
  await loadItems()
})
</script>

<style scoped>
.store-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #fff;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  padding-bottom: 48px;
}

.store-hero {
  padding: clamp(2rem, 5vw, 3rem) var(--layout-pad-x) clamp(1.5rem, 4vw, 2rem);
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(180deg, rgba(96, 165, 250, 0.08) 0%, transparent 100%);
}

.store-hero-inner {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  box-sizing: border-box;
}

.store-eyebrow {
  font-size: 13px;
  color: rgba(96, 165, 250, 0.9);
  letter-spacing: 0.08em;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.store-title {
  font-size: clamp(26px, 4vw, 34px);
  font-weight: 600;
  margin: 0 0 10px;
  letter-spacing: -0.02em;
}

.store-sub {
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.45);
  max-width: 640px;
}

.store-toolbar {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 1.5rem var(--layout-pad-x) 0.5rem;
  box-sizing: border-box;
}

.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 20px;
}

.search-input {
  flex: 1;
  min-width: 200px;
  max-width: 420px;
}

.filter-block {
  margin-bottom: 18px;
}

.filter-label {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
  margin-bottom: 8px;
  letter-spacing: 0.04em;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.chip:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.chip.active {
  border-color: rgba(96, 165, 250, 0.5);
  background: rgba(96, 165, 250, 0.12);
  color: #fff;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: #141414;
  color: #fff;
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.06);
}

.btn-text {
  border-color: transparent;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
}

.btn-text:hover {
  color: #fff;
}

.input {
  padding: 10px 12px;
  border-radius: 8px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
  font-size: 14px;
  outline: none;
}

.input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.flash {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto 16px;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 14px;
  box-sizing: border-box;
}

.flash-err {
  background: rgba(255, 80, 80, 0.1);
  color: #ff8a8a;
}

.state-msg {
  text-align: center;
  padding: 40px 24px;
  font-size: 15px;
}

.state-msg.muted {
  color: rgba(255, 255, 255, 0.35);
}

.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 17.5rem), 1fr));
  gap: 16px;
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 8px var(--layout-pad-x) 0;
  box-sizing: border-box;
}

.store-card {
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  padding: 18px 16px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s, background 0.2s;
}

.store-card:hover {
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.04);
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}

.tag-industry {
  background: rgba(96, 165, 250, 0.15);
  color: #93c5fd;
}

.tag-type {
  background: rgba(167, 139, 250, 0.12);
  color: #c4b5fd;
}

.tag-owned {
  background: rgba(74, 222, 128, 0.12);
  color: #86efac;
}

.tag-personal { background: rgba(74, 222, 128, 0.12); color: #86efac; }
.tag-enterprise { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
.tag-confidential { background: rgba(248, 113, 113, 0.15); color: #f87171; }

.card-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 8px;
  line-height: 1.35;
}

.card-desc {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 10px;
  line-height: 1.5;
  flex: 1;
}

.card-meta {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.28);
  margin: 0 0 14px;
  word-break: break-all;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.price {
  font-size: 18px;
  font-weight: 700;
}

.price.free {
  color: #86efac;
}

.btn-detail {
  text-decoration: none;
  border: 0.5px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  padding: 6px 12px;
  font-size: 13px;
  border-radius: 8px;
}

.btn-detail:hover {
  background: rgba(255, 255, 255, 0.12);
}

.pager-hint {
  text-align: center;
  margin-top: 24px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

@media (max-width: 640px) {
  .store-hero {
    padding: 32px 16px 24px;
  }
  .store-toolbar {
    padding-left: 16px;
    padding-right: 16px;
  }
  .store-grid {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
