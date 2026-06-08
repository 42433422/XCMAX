<template>
  <div class="skill-market">
    <div class="skill-market__header">
      <h1 class="skill-market__title">Butler 技能市场</h1>
      <p class="skill-market__sub">管理 AI 数字管家的平台级技能（kind=butler）</p>
    </div>

    <div class="skill-market__toolbar">
      <button type="button" class="sm-btn" @click="fetchSkills">刷新</button>
    </div>

    <div v-if="loading" class="skill-market__loading">加载中…</div>
    <div v-else-if="error" class="skill-market__error">{{ error }}</div>
    <div v-else-if="!skills.length" class="skill-market__empty">暂无 butler 技能</div>

    <div v-else class="skill-list">
      <div v-for="skill in skills" :key="skill.id" class="skill-card">
        <div class="skill-card__head">
          <span class="skill-card__name">{{ skill.name }}</span>
          <span class="skill-card__version">v{{ skill.version }}</span>
          <span :class="['skill-card__status', skill.is_active ? 'skill-card__status--active' : 'skill-card__status--off']">
            {{ skill.is_active ? '启用' : '停用' }}
          </span>
        </div>
        <p class="skill-card__desc">{{ skill.description }}</p>
        <div class="skill-card__meta">
          <span>权限：{{ skill.permission }}</span>
          <span>使用次数：{{ skill.usage_count }}</span>
          <span>关键词：{{ (skill.trigger_keywords || []).join(', ') || '—' }}</span>
        </div>
        <div class="skill-card__actions">
          <button
            type="button"
            class="sm-btn sm-btn--small"
            :class="skill.is_active ? 'sm-btn--danger' : 'sm-btn--success'"
            @click="toggleSkill(skill)"
          >
            {{ skill.is_active ? '停用' : '启用' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../../api'
import type { ESkillDef } from '../../types/agent'

const skills = ref<ESkillDef[]>([])
const loading = ref(false)
const error = ref('')

async function fetchSkills() {
  loading.value = true
  error.value = ''
  try {
    const data = await (api as any).listButlerSkills?.()
    skills.value = Array.isArray(data) ? data : []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleSkill(skill: ESkillDef) {
  try {
    // 复用 createESkill / updateESkill 或专用端点
    await (api as any).updateButlerSkillActive?.(skill.id, !skill.is_active)
    skill.is_active = !skill.is_active
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(fetchSkills)
</script>

<style scoped>
.skill-market {
  padding: 24px;
  max-width: 900px;
  margin: 0 auto;
}

.skill-market__header { margin-bottom: 20px; }
.skill-market__title { font-size: 1.4rem; font-weight: 700; color: #fff; margin: 0 0 4px; }
.skill-market__sub { font-size: 0.85rem; color: rgba(255,255,255,0.45); margin: 0; }

.skill-market__toolbar { margin-bottom: 16px; display: flex; gap: 10px; }

.skill-market__loading,
.skill-market__empty { color: rgba(255,255,255,0.4); font-size: 0.9rem; padding: 20px 0; }
.skill-market__error { color: #f87171; font-size: 0.9rem; padding: 12px 0; }

.skill-list { display: flex; flex-direction: column; gap: 12px; }

.skill-card {
  background: #111;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 12px;
  padding: 16px 18px;
}

.skill-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.skill-card__name { font-size: 0.95rem; font-weight: 700; color: #fff; }
.skill-card__version { font-size: 0.72rem; color: rgba(255,255,255,0.35); }
.skill-card__status { font-size: 0.7rem; font-weight: 700; padding: 1px 8px; border-radius: 999px; margin-left: auto; }
.skill-card__status--active { background: rgba(74,222,128,0.15); color: #4ade80; }
.skill-card__status--off { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.4); }

.skill-card__desc { font-size: 0.84rem; color: rgba(255,255,255,0.55); margin: 0 0 8px; }

.skill-card__meta {
  display: flex;
  gap: 14px;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.35);
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.skill-card__actions { display: flex; justify-content: flex-end; }

.sm-btn {
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.75);
  transition: all 0.15s;
}

.sm-btn:hover { background: rgba(255,255,255,0.1); }

.sm-btn--small { padding: 4px 12px; font-size: 0.78rem; }
.sm-btn--success { background: rgba(74,222,128,0.12); color: #4ade80; border-color: rgba(74,222,128,0.25); }
.sm-btn--success:hover { background: rgba(74,222,128,0.2); }
.sm-btn--danger { background: rgba(248,113,113,0.1); color: #f87171; border-color: rgba(248,113,113,0.25); }
.sm-btn--danger:hover { background: rgba(248,113,113,0.18); }
</style>
