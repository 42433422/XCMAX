<template>
  <div class="industry-step">
    <p class="eyebrow">理解您的业务</p>
    <h1>{{ companyName || '您的公司' }}属于什么行业？</h1>
    <p class="lead">选择接近的方向，也可以用自己的话描述。没有专版的行业使用通用工作空间。</p>
    <label class="sr-only" for="onboarding-industry-search">搜索或描述行业</label>
    <input id="onboarding-industry-search" class="industry-search" :value="query" placeholder="搜索或描述行业，例如：软件、工厂、设计服务" maxlength="32" @input="$emit('update:query', ($event.target as HTMLInputElement).value)" />
    <div class="industry-categories" aria-label="行业分类">
      <button v-for="item in [{ id: 'popular', label: '常用' }, ...categories, { id: 'all', label: '全部' }]" :key="item.id" type="button" :aria-pressed="category === item.id" @click="$emit('category', item.id)">{{ item.label }}</button>
    </div>
    <div class="industry-pick" role="listbox" aria-label="可选行业">
      <button v-for="item in options" :key="item.id" type="button" class="industry-chip" role="option" :aria-selected="selected === item.id" :class="{ active: selected === item.id }" @click="$emit('select', item.id)">
        <span class="industry-chip-name">{{ item.name }}</span><span class="industry-chip-scenario">{{ item.scenario }}</span>
      </button>
    </div>
    <button v-if="hiddenCount > 0" type="button" class="btn text" @click="$emit('expand')">查看另外 {{ hiddenCount }} 个行业</button>
    <button v-if="query.trim()" type="button" class="btn text" @click="$emit('custom', query)">使用「{{ query.trim() }}」作为行业</button>
    <div class="industry-understanding" role="status"><strong>已选：{{ selectedName }}</strong><span>{{ hasSpecialPlan ? '可按账号授权准备对应行业功能' : '将准备通用业务能力，行业名称不会增加授权' }}</span></div>
    <div class="actions"><button type="button" class="btn ghost" @click="$emit('back')">返回公司名称</button><button v-if="!loginRequired" type="button" class="btn primary" :disabled="busy || !selected" @click="$emit('continue')">{{ busy ? '正在保存…' : '生成我的配置方案' }}</button></div>
  </div>
</template>
<script setup lang="ts">
import type { CatalogChipRow } from './useProductOnboardingState'
defineProps<{ companyName: string; query: string; category: string; categories: readonly { id: string; label: string }[]; options: CatalogChipRow[]; hiddenCount: number; selected: string; selectedName: string; hasSpecialPlan: boolean; busy: boolean; loginRequired: boolean }>()
defineEmits<{ 'update:query': [value: string]; category: [value: string]; select: [value: string]; custom: [value: string]; expand: []; continue: []; back: [] }>()
</script>
