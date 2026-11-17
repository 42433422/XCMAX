<template>
  <span class="group-avatar" :style="{ '--columns': tiles.length > 4 ? 3 : tiles.length > 1 ? 2 : 1 }" aria-hidden="true">
    <span v-for="tile in tiles" :key="tile.id" class="group-avatar__tile">
      <img v-if="tile.src && !failed.includes(tile.src)" :src="tile.src" alt="" decoding="async" draggable="false" @error="failed.push(tile.src)" />
      <span v-else>{{ tile.initial }}</span>
    </span>
    <span v-if="!tiles.length" class="group-avatar__empty">{{ Array.from(name)[0] || '群' }}</span>
  </span>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AiGroupMember } from '@/api/aiGroups'
import { resolveSuperEmployeeAvatarSrc } from '@/constants/superEmployeeAvatars'
import { publicAssetUrl } from '@/utils/publicAssetUrl'
import { employeeAvatarUrl } from '@/utils/employeeAvatar'
const props = defineProps<{ name: string; members?: AiGroupMember[] }>()
const failed = ref<string[]>([])
function avatar(member: AiGroupMember) {
  const src = resolveSuperEmployeeAvatarSrc(member.employee_id, member.avatar) || employeeAvatarUrl(member.employee_id)
  return !src || /^(https?:|data:|blob:|\/)/i.test(src) ? src : publicAssetUrl(src)
}
const tiles = computed(() => [...new Map((props.members || []).map(member => [member.employee_id, member])).values()].slice(0, 9).map(member => ({
  id: member.employee_id,
  src: avatar(member),
  initial: Array.from(member.name || 'AI')[0],
})))
</script>
<style scoped>
.group-avatar { width:40px; height:40px; box-sizing:border-box; padding:3px; gap:2px; border-radius:9px; display:flex; flex-wrap:wrap; align-content:center; justify-content:center; flex:none; background:#e6ebf1; overflow:hidden; }
.group-avatar__tile { width:calc((100% - (var(--columns) - 1) * 2px) / var(--columns)); aspect-ratio:1; display:flex; align-items:center; justify-content:center; overflow:hidden; border-radius:2px; background:#d6e3f3; color:#35577d; font-size:calc(25px / var(--columns)); line-height:1; }
.group-avatar__tile img { width:100%; height:100%; object-fit:cover; }
.group-avatar__empty { align-self:center; font-size:16px; color:#35577d; }
</style>
