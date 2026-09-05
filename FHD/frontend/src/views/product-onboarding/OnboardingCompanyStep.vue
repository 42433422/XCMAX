<template>
  <div class="company-step">
    <div class="company-introduction">
      <p class="eyebrow">从认识您的公司开始</p>
      <h1>您的公司叫什么？</h1>
      <p class="lead">一个名称，开启属于您的工作空间。</p>
      <label class="field-label" for="onboarding-company">公司或团队名称</label>
      <input id="onboarding-company" :value="modelValue" class="company-input" maxlength="256" placeholder="例如：成都修茈科技有限公司" autocomplete="organization" @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)" @keydown.enter="proceed" />
      <p class="field-hint">使用熟悉的简称也可以。完成登录后，我们会保存您的选择。</p>
      <button type="button" class="btn primary" :disabled="!modelValue.trim()" @click="proceed">让 XC 认识我的公司 <span aria-hidden="true">→</span></button>
    </div>
    <div class="company-orbit" aria-hidden="true">
      <div class="orbit-ring"></div><div class="orbit-ring orbit-ring-inner"></div>
      <div class="company-seed"><span>XC</span><small>{{ modelValue.trim() || '您的数字公司' }}</small></div>
      <span class="orbit-note orbit-note-one">知识与数据</span><span class="orbit-note orbit-note-two">AI 员工</span><span class="orbit-note orbit-note-three">日常业务</span>
    </div>
  </div>
</template>
<script setup lang="ts">
const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; continue: [] }>()
function proceed() { if (props.modelValue.trim()) emit('continue') }
</script>
