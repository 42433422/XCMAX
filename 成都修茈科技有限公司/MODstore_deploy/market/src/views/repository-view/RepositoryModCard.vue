<script setup lang="ts">
// 拆分自 RepositoryView.vue 模板（原第 90–173 行 mod-card）；模板逐字迁移，事件改为 emits，行为不变。
import type { ModRow } from './repositoryTypes'
import { artifactLabel, formatUpdatedAt, getBlurb, getUsageScene, isBundle, registerKey } from './repositoryTypes'

defineProps<{
  mod: ModRow
  menuOpen: boolean
  cardDeleteBusy: boolean
  registerBusy: string
  industryLabel: string
  usageText: string
  usageMuted: boolean
}>()

defineEmits<{
  (e: 'toggle-menu'): void
  (e: 'delete'): void
  (e: 'view'): void
  (e: 'test'): void
  (e: 'prefill-employee', emp: Record<string, unknown>, workflowIndex: number): void
  (e: 'register-workflow', workflowIndex: number): void
}>()
</script>

<template>
  <div class="mod-card">
    <div class="mod-card-top">
      <div class="mod-card-badges">
        <span class="badge badge-artifact" :class="'badge-artifact--' + (mod.artifact || 'mod')">{{ artifactLabel(mod.artifact) }}</span>
        <span class="badge" :class="mod.ok ? 'badge-ok' : 'badge-warn'">{{ mod.ok ? '通过' : '待修正' }}</span>
        <span v-if="mod.primary" class="badge badge-primary">主扩展</span>
        <span class="badge badge-scope">{{ industryLabel }}</span>
      </div>
      <div class="mod-card-more-wrap">
        <button
          type="button"
          class="mod-card-more-btn"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          aria-label="更多操作"
          @click.stop="$emit('toggle-menu')"
        >
          ⋯
        </button>
        <div v-if="menuOpen" class="mod-card-menu" role="menu" @click.stop>
          <button
            type="button"
            class="mod-card-menu-item mod-card-menu-item--danger"
            role="menuitem"
            :disabled="cardDeleteBusy"
            @click="$emit('delete')"
          >
            {{ cardDeleteBusy ? '删除中…' : '删除 Mod' }}
          </button>
        </div>
      </div>
    </div>
    <p v-if="isBundle(mod)" class="bundle-hint">组合包：子项见 manifest.bundle</p>
    <h3 class="mod-card-name">{{ mod.name || mod.id }}</h3>
    <p v-if="getBlurb(mod)" class="mod-card-blurb">{{ getBlurb(mod) }}</p>
    <p v-else class="mod-card-blurb mod-card-blurb--muted">暂无简介，可在制作页补充 description 或 library_blurb</p>
    <div class="mod-card-id">{{ mod.id }} · v{{ mod.version || '?' }}</div>
    <div class="mod-card-meta">
      <span v-if="formatUpdatedAt(mod.updated_at)" class="mod-card-meta-item">更新 {{ formatUpdatedAt(mod.updated_at) }}</span>
      <span v-if="getUsageScene(mod)" class="mod-card-meta-item mod-card-meta-item--scene" :title="getUsageScene(mod)">
        场景：{{ getUsageScene(mod) }}
      </span>
    </div>
    <div class="mod-card-scope" :class="{ 'mod-card-scope--muted': usageMuted }">
      {{ usageText }}
    </div>
    <div v-if="mod.warnings?.length" class="mod-card-warn">{{ mod.warnings[0] }}{{ mod.warnings.length > 1 ? ' …' : '' }}</div>
    <div v-if="mod.error" class="mod-card-warn">{{ mod.error }}</div>
    <div v-if="mod.workflow_employees?.length" class="wf-emp-block">
      <div class="wf-emp-title">manifest 中的工作流声明（workflow_employees）</div>
      <div class="wf-emp-actions">
        <div v-for="(e, idx) in mod.workflow_employees" :key="(e.id || '') + '-' + idx" class="wf-emp-line">
          <button
            type="button"
            class="btn btn-sm btn-ghost"
            title="打开员工制作页并预填该条声明（不会自动写入本地包目录）。也可点右侧「一键登记」直接写入 /v1/packages；或完成向导后手动上传登记。"
            @click="$emit('prefill-employee', e, Number(idx))"
          >
            带入员工制作：{{ e.label || e.id || '未命名' }}
          </button>
          <button
            type="button"
            class="btn btn-sm btn-primary"
            :disabled="registerBusy === registerKey(mod.id, idx)"
            title="从该条声明生成最小 employee_pack 并通过沙盒审核后写入本地 /v1/packages（需已登录）。与「带入员工制作」二选一或组合使用；同包 id+version 再次登记会覆盖。"
            @click="$emit('register-workflow', idx)"
          >
            {{ registerBusy === registerKey(mod.id, idx) ? '登记中…' : '一键登记' }}
          </button>
        </div>
      </div>
    </div>
    <div class="mod-card-actions">
      <button class="btn btn-sm" @click="$emit('view')">制作 / 编辑</button>
      <button
        type="button"
        class="btn btn-sm btn-secondary"
        title="把该 Mod ID 自动带入沙箱页，并指向线上 FHD 沙盒宿主"
        @click="$emit('test')"
      >
        沙箱测试
      </button>
    </div>
  </div>
</template>

<style scoped src="./repository-view.css"></style>
