<script setup lang="ts">
import { computed } from 'vue'

export type CatalogAuthor = {
  id: number
  username: string
  avatar_initial?: string
}

export type CatalogCreatorStats = {
  favorite_count?: number
  review_count?: number
  average_rating?: number
  works_count?: number
}

const props = defineProps<{
  author: CatalogAuthor | null
  stats: CatalogCreatorStats | null
  installCount?: number
  industry?: string
  favorited?: boolean
  following?: boolean
  favBusy?: boolean
  isSelf?: boolean
}>()

const emit = defineEmits<{
  follow: []
  favorite: []
  complaint: []
}>()

const displayName = computed(() => props.author?.username || '未知创作者')
const avatarLetter = computed(
  () => props.author?.avatar_initial || displayName.value.charAt(0).toUpperCase() || '创',
)

function formatCount(n: number | undefined): string {
  const v = Number(n ?? 0)
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

const statItems = computed(() => {
  const s = props.stats || {}
  const items = [
    { label: '获赞与收藏', value: formatCount(Number(s.favorite_count ?? 0)) },
    { label: '安装', value: formatCount(props.installCount) },
    { label: '评价', value: formatCount(Number(s.review_count ?? 0)) },
  ]
  const avg = Number(s.average_rating ?? 0)
  if (avg > 0) {
    items.push({ label: '均分', value: avg.toFixed(1) })
  }
  return items
})
</script>

<template>
  <section class="creator-profile" aria-label="创作者主页">
    <div class="creator-profile__main">
      <div class="creator-profile__avatar" aria-hidden="true">{{ avatarLetter }}</div>
      <div class="creator-profile__info">
        <div class="creator-profile__name-row">
          <h2 class="creator-profile__name">{{ displayName }}</h2>
          <button
            v-if="author && !isSelf"
            type="button"
            class="creator-profile__follow"
            :class="{ 'creator-profile__follow--on': following }"
            @click="emit('follow')"
          >
            {{ following ? '已关注' : '+ 关注' }}
          </button>
        </div>
        <p class="creator-profile__bio">
          <span>创作者</span>
          <span v-if="industry" class="creator-profile__sep">·</span>
          <span v-if="industry">{{ industry }}</span>
          <span v-if="stats?.works_count != null" class="creator-profile__sep">·</span>
          <span v-if="stats?.works_count != null">{{ stats.works_count }} 件公开作品</span>
        </p>
        <ul class="creator-profile__stats">
          <li v-for="st in statItems" :key="st.label" class="creator-profile__stat">
            <strong>{{ st.value }}</strong>
            <span>{{ st.label }}</span>
          </li>
        </ul>
      </div>
    </div>

    <div class="creator-profile__actions">
      <button
        type="button"
        class="creator-profile__action creator-profile__action--like"
        :class="{ 'creator-profile__action--on': favorited }"
        :disabled="favBusy"
        @click="emit('favorite')"
      >
        <span class="creator-profile__action-icon" aria-hidden="true">{{ favorited ? '♥' : '♡' }}</span>
        {{ favorited ? '已点赞' : '点赞' }}
        <span v-if="stats?.favorite_count" class="creator-profile__action-count">
          {{ formatCount(stats.favorite_count) }}
        </span>
      </button>
      <button type="button" class="creator-profile__action creator-profile__action--ghost" @click="emit('complaint')">
        投诉 / 申诉
      </button>
    </div>
  </section>
</template>

<style scoped>
.creator-profile {
  margin-bottom: 1.5rem;
  padding: 20px 22px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0.02) 100%);
  border: 0.5px solid rgba(255, 255, 255, 0.12);
}

.creator-profile__main {
  display: flex;
  gap: 18px;
  align-items: flex-start;
}

.creator-profile__avatar {
  flex-shrink: 0;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.75rem;
  font-weight: 700;
  color: #e9d5ff;
  background: linear-gradient(145deg, rgba(124, 58, 237, 0.45), rgba(59, 130, 246, 0.35));
  border: 2px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.creator-profile__info {
  flex: 1;
  min-width: 0;
}

.creator-profile__name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.creator-profile__name {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #fff;
}

.creator-profile__follow {
  padding: 6px 16px;
  border-radius: 999px;
  border: none;
  background: #fff;
  color: #0a0a0a;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.15s;
}

.creator-profile__follow:hover {
  opacity: 0.92;
}

.creator-profile__follow--on {
  background: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.85);
  border: 0.5px solid rgba(255, 255, 255, 0.2);
}

.creator-profile__bio {
  margin: 6px 0 0;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.5);
}

.creator-profile__sep {
  margin: 0 4px;
}

.creator-profile__stats {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}

.creator-profile__stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.creator-profile__stat strong {
  font-size: 1.05rem;
  font-weight: 700;
  color: #fff;
}

.creator-profile__stat span {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.45);
}

.creator-profile__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 0.5px solid rgba(255, 255, 255, 0.08);
}

.creator-profile__action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: 999px;
  border: 0.5px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.88);
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.creator-profile__action:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}

.creator-profile__action:disabled {
  opacity: 0.6;
  cursor: wait;
}

.creator-profile__action--like.creator-profile__action--on {
  background: rgba(248, 113, 113, 0.15);
  border-color: rgba(248, 113, 113, 0.4);
  color: #fca5a5;
}

.creator-profile__action-icon {
  font-size: 1rem;
}

.creator-profile__action-count {
  font-size: 0.78rem;
  opacity: 0.75;
}

.creator-profile__action--ghost {
  background: transparent;
}

@media (max-width: 560px) {
  .creator-profile__main {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .creator-profile__name-row {
    justify-content: center;
  }
  .creator-profile__stats {
    justify-content: center;
  }
  .creator-profile__actions {
    justify-content: center;
  }
}
</style>
