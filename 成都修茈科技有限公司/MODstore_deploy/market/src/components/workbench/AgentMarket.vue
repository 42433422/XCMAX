<template>
  <div v-if="open" class="am-mask" role="dialog" aria-modal="true" aria-labelledby="am-title" @click.self="$emit('close')">
    <div class="am-card">
      <header class="am-head">
        <h2 id="am-title" class="am-title">智能体广场</h2>
        <div class="am-head-ops">
          <input
            v-model="kw"
            type="search"
            class="am-search"
            placeholder="搜索智能体名称 / 场景…"
            aria-label="搜索智能体"
          />
          <button type="button" class="am-btn am-btn--primary" @click="openCreator">+ 创建智能体</button>
          <button type="button" class="am-btn am-btn--ghost" @click="$emit('close')">关闭</button>
        </div>
      </header>

      <nav class="am-cats" role="tablist" aria-label="分类">
        <button
          v-for="c in categories"
          :key="c.id"
          type="button"
          role="tab"
          class="am-cat"
          :class="{ 'am-cat--on': activeCat === c.id }"
          :aria-selected="activeCat === c.id"
          @click="activeCat = c.id"
        >{{ c.label }}</button>
      </nav>

      <section v-if="loading" class="am-loading" role="status">正在加载智能体清单…</section>
      <section v-else-if="error" class="am-error" role="alert">{{ error }}</section>
      <section v-else class="am-grid">
        <article
          v-for="bot in filtered"
          :key="bot.id"
          class="am-bot"
          :class="{ 'am-bot--mine': bot.mine, 'am-bot--builtin': bot.builtin }"
        >
          <div class="am-bot__avatar" aria-hidden="true">{{ bot.icon }}</div>
          <div class="am-bot__main">
            <h3 class="am-bot__name">
              {{ bot.name }}
              <span v-if="bot.builtin" class="am-bot__tag am-bot__tag--builtin">官方</span>
              <span v-if="bot.mine" class="am-bot__tag am-bot__tag--mine">我的</span>
            </h3>
            <p class="am-bot__desc">{{ bot.desc }}</p>
            <div class="am-bot__meta">
              <span>对话 · {{ bot.uses ?? '—' }}</span>
              <span v-if="bot.tags?.length">·</span>
              <span v-for="t in (bot.tags || []).slice(0, 3)" :key="t" class="am-bot__chip">{{ t }}</span>
            </div>
          </div>
          <div class="am-bot__ops">
            <button type="button" class="am-btn am-btn--primary" @click="$emit('start', bot)">开始对话</button>
            <button v-if="bot.mine" type="button" class="am-btn am-btn--ghost" @click="$emit('remove', bot)">删除</button>
            <button
              type="button"
              class="am-btn am-btn--ghost"
              :class="{ 'am-btn--toggle-on': bot.favorite }"
              @click="$emit('favorite', bot)"
            >
              {{ bot.favorite ? '★ 已收藏' : '☆ 收藏' }}
            </button>
          </div>
        </article>
        <p v-if="!filtered.length" class="am-empty">没有命中的智能体，可以试试创建一个新的。</p>
      </section>

      <Transition name="am-creator">
        <section v-if="showCreator" class="am-creator">
          <header class="am-creator__head">
            <h3>创建智能体</h3>
            <button type="button" class="am-btn am-btn--ghost" @click="showCreator = false">收起</button>
          </header>
          <div class="am-creator__row">
            <label class="am-creator__field">
              <span>头像 emoji</span>
              <input v-model="draft.icon" type="text" maxlength="3" class="am-input am-input--mini" placeholder="⚙️" />
            </label>
            <label class="am-creator__field am-creator__field--grow">
              <span>名字</span>
              <input v-model="draft.name" type="text" maxlength="24" class="am-input" placeholder="例如：抖音脚本搭子" />
            </label>
          </div>
          <label class="am-creator__field">
            <span>一句话简介</span>
            <input v-model="draft.desc" type="text" maxlength="80" class="am-input" placeholder="按口播节奏写脚本，附拍摄分镜" />
          </label>
          <label class="am-creator__field">
            <span>人设 / 系统提示</span>
            <textarea v-model="draft.persona" class="am-input am-input--area" rows="4" placeholder="你是一名抖音口播脚本作者，输出 30s 脚本+分镜+口播台词…" />
          </label>
          <label class="am-creator__field">
            <span>开场白</span>
            <input v-model="draft.opener" type="text" maxlength="80" class="am-input" placeholder="嗨～告诉我你想做什么主题的视频？" />
          </label>
          <label class="am-creator__field">
            <span>标签（逗号分隔，最多 3 个）</span>
            <input v-model="draft.tagsRaw" type="text" maxlength="40" class="am-input" placeholder="抖音, 脚本, 口播" />
          </label>
          <div class="am-creator__foot">
            <button type="button" class="am-btn am-btn--primary" :disabled="!canSubmitDraft" @click="onSubmitDraft">保存到「我的 Bot」</button>
            <button type="button" class="am-btn am-btn--ghost" @click="resetDraft">重置</button>
          </div>
        </section>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { AgentBot } from '../../utils/agentBots'

const props = defineProps<{
  open: boolean
  bots: AgentBot[]
  loading?: boolean
  error?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'start', bot: AgentBot): void
  (e: 'create', bot: AgentBot): void
  (e: 'remove', bot: AgentBot): void
  (e: 'favorite', bot: AgentBot): void
}>()

const kw = ref('')
const activeCat = ref('all')
const showCreator = ref(false)

const draft = reactive({
  icon: '⚙️',
  name: '',
  desc: '',
  persona: '',
  opener: '',
  tagsRaw: '',
})

const categories = computed(() => {
  const set = new Map<string, number>()
  set.set('all', props.bots.length)
  set.set('mine', props.bots.filter((b) => b.mine).length)
  set.set('favorite', props.bots.filter((b) => b.favorite).length)
  for (const b of props.bots) {
    if (!b.category) continue
    set.set(b.category, (set.get(b.category) || 0) + 1)
  }
  return [
    { id: 'all', label: `全部 ${set.get('all') || 0}` },
    { id: 'mine', label: `我的 ${set.get('mine') || 0}` },
    { id: 'favorite', label: `收藏 ${set.get('favorite') || 0}` },
    ...Array.from(set.keys())
      .filter((id) => !['all', 'mine', 'favorite'].includes(id))
      .map((id) => ({ id, label: `${id} ${set.get(id) || 0}` })),
  ]
})

const filtered = computed(() => {
  const q = kw.value.trim().toLowerCase()
  return props.bots.filter((b) => {
    if (activeCat.value === 'mine' && !b.mine) return false
    if (activeCat.value === 'favorite' && !b.favorite) return false
    if (!['all', 'mine', 'favorite'].includes(activeCat.value) && b.category !== activeCat.value) return false
    if (!q) return true
    if (b.name.toLowerCase().includes(q)) return true
    if (b.desc.toLowerCase().includes(q)) return true
    if ((b.tags || []).some((t) => t.toLowerCase().includes(q))) return true
    return false
  })
})

const canSubmitDraft = computed(() => draft.name.trim().length >= 2 && draft.persona.trim().length >= 6)

function openCreator() {
  showCreator.value = true
}

function resetDraft() {
  draft.icon = '⚙️'
  draft.name = ''
  draft.desc = ''
  draft.persona = ''
  draft.opener = ''
  draft.tagsRaw = ''
}

function onSubmitDraft() {
  if (!canSubmitDraft.value) return
  const tags = draft.tagsRaw
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 3)
  const bot: AgentBot = {
    id: `mybot_${Date.now().toString(36)}`,
    name: draft.name.trim(),
    desc: draft.desc.trim() || `${draft.name.trim()} —— 我的智能体`,
    icon: draft.icon || '⚙️',
    category: 'mine',
    tags,
    mine: true,
    persona: draft.persona.trim(),
    opener: draft.opener.trim() || '需要我做什么？',
    favorite: true,
  }
  emit('create', bot)
  resetDraft()
  showCreator.value = false
}

watch(
  () => props.open,
  (v) => {
    if (!v) {
      showCreator.value = false
      kw.value = ''
      activeCat.value = 'all'
    }
  },
)
</script>

<style scoped>
.am-mask {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(2, 6, 23, 0.7);
  display: grid;
  place-items: center;
  padding: 1rem;
  backdrop-filter: blur(6px);
}

.am-card {
  width: min(60rem, 100%);
  max-height: 92vh;
  overflow-y: auto;
  padding: 1.1rem 1.4rem 1.5rem;
  background: rgba(15, 23, 42, 0.97);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.95rem;
  color: #e2e8f0;
}

.am-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.85rem;
}

.am-title {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
}

.am-head-ops {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.am-search {
  width: 16rem;
  max-width: 100%;
  padding: 0.45rem 0.7rem;
  background: rgba(2, 6, 23, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  border-radius: 0.45rem;
}

.am-search:focus {
  outline: none;
  border-color: rgba(129, 140, 248, 0.55);
}

.am-btn {
  padding: 0.42rem 0.85rem;
  border-radius: 0.45rem;
  cursor: pointer;
  font-size: 0.83rem;
  border: 1px solid transparent;
  white-space: nowrap;
}

.am-btn--primary {
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.55), rgba(99, 102, 241, 0.75));
  color: #fff;
  border-color: rgba(165, 180, 252, 0.55);
}

.am-btn--primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.am-btn--ghost {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.86);
  border-color: rgba(255, 255, 255, 0.1);
}

.am-btn--ghost:hover { background: rgba(255, 255, 255, 0.1); }
.am-btn--toggle-on { color: #fbbf24; border-color: rgba(251, 191, 36, 0.4); }

.am-cats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.8rem;
}

.am-cat {
  padding: 0.32rem 0.7rem;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(226, 232, 240, 0.78);
  cursor: pointer;
  font-size: 0.78rem;
}

.am-cat--on {
  background: rgba(99, 102, 241, 0.32);
  border-color: rgba(165, 180, 252, 0.55);
  color: #fff;
}

.am-grid {
  display: grid;
  gap: 0.65rem;
  grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr));
}

.am-bot {
  display: grid;
  grid-template-columns: 2.5rem 1fr;
  gap: 0.7rem;
  padding: 0.85rem;
  border-radius: 0.6rem;
  background: rgba(2, 6, 23, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.am-bot--mine { border-color: rgba(165, 180, 252, 0.4); }
.am-bot--builtin { border-color: rgba(45, 212, 191, 0.32); }

.am-bot__avatar {
  width: 2.5rem;
  height: 2.5rem;
  display: grid;
  place-items: center;
  border-radius: 0.6rem;
  background: rgba(99, 102, 241, 0.22);
  font-size: 1.4rem;
}

.am-bot__name {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.95rem;
  margin: 0 0 0.18rem;
  font-weight: 600;
}

.am-bot__tag {
  font-size: 0.65rem;
  font-weight: 500;
  padding: 0.05rem 0.3rem;
  border-radius: 0.32rem;
  letter-spacing: 0.04em;
}

.am-bot__tag--builtin { background: rgba(45, 212, 191, 0.22); color: #5eead4; }
.am-bot__tag--mine { background: rgba(99, 102, 241, 0.22); color: #c7d2fe; }

.am-bot__desc {
  font-size: 0.82rem;
  color: rgba(203, 213, 225, 0.78);
  margin: 0 0 0.4rem;
  line-height: 1.4;
}

.am-bot__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.32rem;
  font-size: 0.7rem;
  color: rgba(203, 213, 225, 0.55);
  margin-bottom: 0.55rem;
}

.am-bot__chip {
  padding: 0.05rem 0.4rem;
  border-radius: 0.32rem;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.78);
}

.am-bot__ops {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.am-empty,
.am-loading,
.am-error {
  grid-column: 1 / -1;
  text-align: center;
  padding: 1.5rem;
  font-size: 0.85rem;
  color: rgba(203, 213, 225, 0.65);
}

.am-error { color: rgba(252, 165, 165, 0.95); }

.am-creator {
  margin-top: 1rem;
  padding: 1rem 1.1rem;
  background: rgba(99, 102, 241, 0.08);
  border: 1px dashed rgba(165, 180, 252, 0.3);
  border-radius: 0.7rem;
}

.am-creator__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.6rem;
}

.am-creator__row {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.am-creator__field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 0.6rem;
  font-size: 0.8rem;
  color: rgba(226, 232, 240, 0.85);
}

.am-creator__field--grow { flex: 1 1 18rem; }

.am-input {
  padding: 0.45rem 0.65rem;
  background: rgba(2, 6, 23, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  border-radius: 0.45rem;
  font-family: inherit;
}

.am-input--mini { width: 4.5rem; }
.am-input--area { resize: vertical; min-height: 5rem; }

.am-input:focus { outline: none; border-color: rgba(129, 140, 248, 0.55); }

.am-creator__foot {
  display: flex;
  gap: 0.5rem;
}

.am-creator-enter-active,
.am-creator-leave-active {
  transition: opacity 200ms ease, transform 200ms ease;
}

.am-creator-enter-from,
.am-creator-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
