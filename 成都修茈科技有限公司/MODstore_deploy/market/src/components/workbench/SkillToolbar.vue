<template>
  <div class="skill-toolbar" role="toolbar" aria-label="技能开关">
    <button
      v-for="s in skills"
      :key="s.id"
      type="button"
      class="skill-toolbar__btn"
      :class="{ 'skill-toolbar__btn--on': active.includes(s.id) }"
      :title="s.tip"
      :aria-pressed="active.includes(s.id)"
      @click="toggle(s.id)"
    >
      <span class="skill-toolbar__icon" aria-hidden="true">{{ s.icon }}</span>
      <span class="skill-toolbar__label">{{ s.label }}</span>
    </button>
    <span v-if="active.length" class="skill-toolbar__hint" role="status">
      已开启 {{ active.length }} 项 · 点同名按钮关闭
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ALL_SKILLS } from '../../utils/chatSkills'

const props = defineProps<{
  active: string[]
}>()

const emit = defineEmits<{
  (e: 'update:active', v: string[]): void
}>()

const skills = computed(() => ALL_SKILLS)

function toggle(id: string) {
  const cur = props.active.slice()
  const idx = cur.indexOf(id)
  if (idx >= 0) cur.splice(idx, 1)
  else cur.push(id)
  emit('update:active', cur)
}
</script>

<style scoped>
.skill-toolbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  padding: 0.35rem 0;
}

.skill-toolbar__btn {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.32rem 0.65rem;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(226, 232, 240, 0.82);
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1.2;
  transition: background 140ms ease, border-color 140ms ease, color 140ms ease;
}

.skill-toolbar__btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.skill-toolbar__btn--on {
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.32), rgba(99, 102, 241, 0.5));
  border-color: rgba(165, 180, 252, 0.55);
  color: #fff;
  box-shadow: 0 0 0 1px rgba(165, 180, 252, 0.25), 0 4px 14px rgba(99, 102, 241, 0.32);
}

.skill-toolbar__icon {
  font-size: 0.95rem;
}

.skill-toolbar__hint {
  font-size: 0.72rem;
  color: rgba(203, 213, 225, 0.55);
  margin-left: 0.3rem;
}
</style>
