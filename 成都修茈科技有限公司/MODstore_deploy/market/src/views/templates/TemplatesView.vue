<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api'

interface TemplateItem {
  id: number
  pkg_id: string
  name: string
  description: string
  version: string
  price: number
  industry: string
  template_category: string
  template_difficulty: string
  difficulty_label: string
  install_count: number
  created_at: string | null
}

interface CategoryItem {
  name: string
  count: number
}

const router = useRouter()

const items = ref<TemplateItem[]>([])
const total = ref(0)
const loading = ref(false)
const errMsg = ref('')

const categories = ref<CategoryItem[]>([])
const difficulties = ref<Record<string, string>>({})

const filters = ref({ q: '', category: '', difficulty: '', sort: 'popular' })

let searchTimer: ReturnType<typeof setTimeout> | null = null

async function loadCategories() {
  try {
    const r: any = await api.templatesCategories()
    categories.value = Array.isArray(r?.categories) ? r.categories : []
    difficulties.value = r?.difficulties || {}
  } catch {
    categories.value = []
  }
}

async function loadList() {
  loading.value = true
  errMsg.value = ''
  try {
    const r: any = await api.templatesList({
      q: filters.value.q,
      category: filters.value.category,
      difficulty: filters.value.difficulty,
      sort: filters.value.sort,
      limit: 60,
    })
    items.value = Array.isArray(r?.items) ? r.items : []
    total.value = Number(r?.total || items.value.length)
  } catch (e: any) {
    errMsg.value = e?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadCategories(), loadList()])
})

watch(
  () => [filters.value.category, filters.value.difficulty, filters.value.sort],
  () => loadList(),
)

watch(
  () => filters.value.q,
  () => {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(loadList, 300)
  },
)

function pickCategory(name: string) {
  filters.value.category = filters.value.category === name ? '' : name
}

function difficultyLabel(d: string): string {
  return difficulties.value[d] || d
}

function openDetail(item: TemplateItem) {
  router.push({ name: 'template-detail', params: { id: String(item.id) } })
}

async function quickInstall(item: TemplateItem) {
  if (!confirm(`一键安装 "${item.name}"？将在你的工作流列表创建一个副本。`)) return
  try {
    const r: any = await api.templateInstall(item.id)
    if (r?.workflow_id) {
      router.push({ name: 'workflow-v2-editor', params: { id: String(r.workflow_id) } })
    } else {
      alert('安装完成，但未拿到 workflow_id')
    }
  } catch (e: any) {
    alert('安装失败：' + (e?.detail || e?.message || ''))
  }
}

const sortOptions = [
  { value: 'popular', label: '最热门' },
  { value: 'newest', label: '最新发布' },
]

const totalCount = computed(() => total.value)
</script>

<template>
  <main class="tpl">
    <header class="tpl__head">
      <div>
        <h1 class="tpl__title">工作流模板市场</h1>
        <p class="tpl__sub">
          挑一个最贴合业务场景的模板，<strong>一键安装到你的工作流</strong>，再去 v2 画布上改细节。
        </p>
      </div>
      <input
        v-model="filters.q"
        type="search"
        placeholder="搜索模板名称、用途…"
        class="tpl__search"
      />
    </header>

    <section class="tpl__filters">
      <div class="tpl__chip-row">
        <button
          class="tpl__chip"
          :class="{ 'tpl__chip--on': !filters.category }"
          type="button"
          @click="filters.category = ''"
        >
          全部
        </button>
        <button
          v-for="c in categories"
          :key="c.name"
          type="button"
          class="tpl__chip"
          :class="{ 'tpl__chip--on': filters.category === c.name }"
          @click="pickCategory(c.name)"
        >
          {{ c.name }}<span v-if="c.count" class="tpl__chip-count">{{ c.count }}</span>
        </button>
      </div>
      <div class="tpl__row">
        <div class="tpl__seg">
          <button
            class="tpl__seg-btn"
            :class="{ 'tpl__seg-btn--on': !filters.difficulty }"
            type="button"
            @click="filters.difficulty = ''"
          >
            全部难度
          </button>
          <button
            v-for="(label, key) in difficulties"
            :key="key"
            class="tpl__seg-btn"
            :class="{ 'tpl__seg-btn--on': filters.difficulty === key }"
            type="button"
            @click="filters.difficulty = filters.difficulty === key ? '' : key"
          >
            {{ label }}
          </button>
        </div>
        <select v-model="filters.sort" class="tpl__sort">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </div>
    </section>

    <p v-if="errMsg" class="tpl__err">{{ errMsg }}</p>

    <section class="tpl__results">
      <p class="tpl__total">共 <strong>{{ totalCount }}</strong> 个模板</p>
      <div v-if="loading" class="tpl__loading">加载中…</div>
      <div v-else-if="!items.length" class="tpl__empty">
        暂无符合条件的模板。换一个分类或清空筛选试试。
      </div>
      <ul v-else class="tpl__grid">
        <li v-for="t in items" :key="t.id" class="tpl-card">
          <header class="tpl-card__head">
            <span class="tpl-card__cat">{{ t.template_category || '通用' }}</span>
            <span v-if="t.difficulty_label" class="tpl-card__diff">{{ t.difficulty_label }}</span>
          </header>
          <h3 class="tpl-card__name" @click="openDetail(t)">{{ t.name }}</h3>
          <p class="tpl-card__desc">{{ t.description || '该模板暂无描述' }}</p>
          <footer class="tpl-card__foot">
            <span class="tpl-card__metric">
              <strong>{{ t.install_count }}</strong> 次安装
            </span>
            <span class="tpl-card__metric tpl-card__price">
              {{ t.price > 0 ? `¥ ${t.price.toFixed(2)}` : '免费' }}
            </span>
            <span class="tpl-card__spacer" />
            <button class="tpl-card__btn" type="button" @click="openDetail(t)">查看</button>
            <button
              class="tpl-card__btn tpl-card__btn--primary"
              type="button"
              @click="quickInstall(t)"
            >
              一键安装
            </button>
          </footer>
        </li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.tpl {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px 64px;
  color: #0f172a;
}

.tpl__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.tpl__title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
}

.tpl__sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: #475569;
  max-width: 660px;
}

.tpl__search {
  width: min(320px, 100%);
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
}

.tpl__search:focus {
  outline: none;
  border-color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.18);
}

.tpl__filters {
  margin-bottom: 22px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tpl__chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tpl__chip {
  font-size: 13px;
  background: #f1f5f9;
  border: 1px solid transparent;
  color: #334155;
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tpl__chip:hover {
  background: #e2e8f0;
}

.tpl__chip--on {
  background: #4f46e5;
  color: #fff;
}

.tpl__chip-count {
  font-size: 11px;
  background: rgba(255, 255, 255, 0.16);
  padding: 1px 6px;
  border-radius: 999px;
}

.tpl__chip:not(.tpl__chip--on) .tpl__chip-count {
  background: #fff;
  color: #94a3b8;
}

.tpl__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.tpl__seg {
  display: inline-flex;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  overflow: hidden;
}

.tpl__seg-btn {
  background: #fff;
  border: 0;
  padding: 6px 14px;
  font-size: 13px;
  color: #334155;
  cursor: pointer;
  border-right: 1px solid #e2e8f0;
}

.tpl__seg-btn:last-child {
  border-right: 0;
}

.tpl__seg-btn--on {
  background: #4f46e5;
  color: #fff;
}

.tpl__sort {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  background: #fff;
}

.tpl__err {
  margin: 0 0 16px;
  padding: 8px 14px;
  background: #fee2e2;
  color: #991b1b;
  border-radius: 8px;
  font-size: 13px;
}

.tpl__total {
  margin: 0 0 12px;
  font-size: 13px;
  color: #64748b;
}

.tpl__loading,
.tpl__empty {
  padding: 48px 16px;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  color: #64748b;
}

.tpl__grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.tpl-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}

.tpl-card:hover {
  box-shadow: 0 12px 28px -16px rgba(79, 70, 229, 0.32);
  transform: translateY(-2px);
}

.tpl-card__head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.tpl-card__cat {
  font-size: 11px;
  background: #eef2ff;
  color: #3730a3;
  padding: 1px 8px;
  border-radius: 999px;
  font-weight: 500;
}

.tpl-card__diff {
  font-size: 11px;
  background: #fef3c7;
  color: #92400e;
  padding: 1px 8px;
  border-radius: 999px;
}

.tpl-card__name {
  margin: 6px 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  cursor: pointer;
}

.tpl-card__name:hover {
  color: #4f46e5;
}

.tpl-card__desc {
  margin: 0 0 14px;
  font-size: 13px;
  color: #475569;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
  line-height: 1.5;
}

.tpl-card__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tpl-card__metric {
  font-size: 12px;
  color: #64748b;
}

.tpl-card__metric strong {
  color: #0f172a;
}

.tpl-card__price {
  font-weight: 600;
  color: #16a34a;
}

.tpl-card__spacer {
  flex: 1;
}

.tpl-card__btn {
  font-size: 12px;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.tpl-card__btn:hover {
  background: #f1f5f9;
}

.tpl-card__btn--primary {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #fff;
}

.tpl-card__btn--primary:hover {
  background: #4338ca;
}
</style>
