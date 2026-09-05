<template>
  <div class="configuration-step">
    <p class="eyebrow">为您的公司准备工作空间</p>
    <h1>{{ companyName || '您的公司' }}的配置方案</h1>
    <p class="lead">{{ industryName }} · {{ hasSpecialPlan ? '按账号授权准备行业功能' : '通用业务工作空间' }}。确认后进入系统，业务资料由您决定何时导入。</p>
    <div class="configuration-summary"><div class="configuration-core">XC<small>{{ companyName || '您的公司' }}</small></div><div><h2>从真实可用的能力开始</h2><p>智能对话 · 企业知识 · 数据对接 · AI 员工协作</p><p class="muted">这里只准备功能，不创建客户、商品或订单。</p></div></div>
    <div class="sidebar-preview" aria-label="行业工作空间方案"><p class="sidebar-preview-title">{{ ready ? '进入后可使用' : '准备完成后可使用' }}</p><div class="sidebar-preview-list"><span v-for="label in labels" :key="label" class="sidebar-preview-chip">{{ label }}</span></div></div>
    <p v-if="deferred.length" class="capability-note">暂未提供独立功能：{{ deferred.join('、') }}。这些能力不会作为可用入口展示。</p>
    <div class="status-card" :class="{ ok: ready && !loading, warn: !ready && !loading }" role="status">{{ busy ? '正在准备工作空间，请稍候…' : loading ? '正在核对当前账号的功能…' : ready ? '工作空间功能已准备好' : `还需准备 ${missingCount || 1} 项功能` }}</div>
    <div class="actions"><button type="button" class="btn ghost" :disabled="busy" @click="$emit('back')">调整行业</button><button v-if="!loginRequired" type="button" class="btn primary" :disabled="busy || loading" @click="$emit('create')">{{ busy ? '正在创建…' : `进入${companyName || '我的'}工作空间` }}</button></div>
    <details class="optional-experience"><summary>想先试一件事？（可选）</summary><p>{{ attendance ? '到考勤工作区核对部门和人员。打开页面不会将查询记为完成。' : '演示体验会在您点击准备后创建一个演示客户和商品；制单前仍需要您确认。' }}</p><button type="button" class="btn ghost" :disabled="!ready || busy" @click="$emit('example')">{{ attendance ? '核对考勤名单' : '查看演示业务体验' }}</button></details>
    <details v-if="groups.length" class="host-pack-details"><summary>查看功能准备明细</summary><section v-for="group in groups" :key="group.id"><h3>{{ group.title }}</h3><ul><li v-for="item in group.items" :key="item.mod_id">{{ item.label }} · {{ item.installed ? '已准备' : item.required ? '待准备' : '可选' }}</li></ul></section><button type="button" class="btn text" :disabled="loading || busy" @click="$emit('refresh')">重新检测</button></details>
  </div>
</template>
<script setup lang="ts">
import type { IndustryBaselineGroup } from '@/constants/platformShell'
defineProps<{ companyName: string; industryName: string; labels: string[]; deferred: string[]; hasSpecialPlan: boolean; ready: boolean; loading: boolean; busy: boolean; missingCount: number; attendance: boolean; loginRequired: boolean; groups: IndustryBaselineGroup[] }>()
defineEmits<{ create: []; back: []; refresh: []; example: [] }>()
</script>
