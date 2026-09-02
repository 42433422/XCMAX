<script setup lang="ts">
// 拆分自 HomeView.vue 模板（原第 220–268 行）；模板逐字迁移，v-model 改为 :value/@input + emits 写回，行为不变。
import type { ContactField } from './useContactForm'
import type { ContactFormState } from './homeViewTypes'

defineProps<{
  csIntakeActive: boolean
  contactForm: ContactFormState
  contactError: string
  contactSuccess: boolean
  contactSubmitting: boolean
}>()

defineEmits<{
  (e: 'update-field', field: ContactField, value: string | boolean): void
  (e: 'submit'): void
}>()
</script>

<template>
  <section id="contact" class="section section--border-top">
    <div class="container grid grid-2">
      <div class="contact-intro">
        <h2 class="section-title">商务合作与咨询</h2>
        <p v-if="csIntakeActive" class="cs-intake-banner">
          修茈科技邀请您填写项目需求，提交后您的专属顾问将尽快跟进。
        </p>
        <p class="section-description contact-intro__text">
          留下您的需求与联系方式，我们会通过邮箱尽快回复。信息将保存至平台数据库，仅用于商务联络。
        </p>
      </div>
      <form id="contact-form" class="contact-form" @submit.prevent="$emit('submit')">
        <div class="form-group">
          <label for="contact-name">称呼</label>
          <input
            id="contact-name"
            :value="contactForm.name"
            type="text"
            required
            maxlength="128"
            autocomplete="name"
            @input="$emit('update-field', 'name', ($event.target as HTMLInputElement).value.trim())"
          />
        </div>
        <div class="form-group">
          <label for="contact-email">邮箱</label>
          <input
            id="contact-email"
            :value="contactForm.email"
            type="email"
            required
            maxlength="256"
            autocomplete="email"
            @input="$emit('update-field', 'email', ($event.target as HTMLInputElement).value.trim())"
          />
        </div>
        <div class="form-group">
          <label for="contact-phone">电话（选填）</label>
          <input
            id="contact-phone"
            :value="contactForm.phone"
            type="tel"
            maxlength="64"
            autocomplete="tel"
            @input="$emit('update-field', 'phone', ($event.target as HTMLInputElement).value.trim())"
          />
        </div>
        <div class="form-group">
          <label for="contact-company">公司 / 组织（选填）</label>
          <input
            id="contact-company"
            :value="contactForm.company"
            type="text"
            maxlength="256"
            autocomplete="organization"
            @input="$emit('update-field', 'company', ($event.target as HTMLInputElement).value.trim())"
          />
        </div>
        <div class="form-group">
          <label for="contact-message">需求说明（选填）</label>
          <textarea
            id="contact-message"
            :value="contactForm.message"
            maxlength="8000"
            rows="4"
            @input="$emit('update-field', 'message', ($event.target as HTMLTextAreaElement).value.trim())"
          />
        </div>
        <label class="footer-meta contact-privacy-consent">
          <input
            :checked="contactForm.privacyAgreed"
            type="checkbox"
            required
            @change="$emit('update-field', 'privacyAgreed', ($event.target as HTMLInputElement).checked)"
          />
          <span>我已阅读并同意 <a href="/privacy.html" target="_blank" rel="noopener noreferrer">《用户协议与隐私政策》</a>，同意修茈科技仅为商务联络、方案评估与顾问回访处理本次提交的信息。</span>
        </label>
        <div v-if="contactError" class="error-message">{{ contactError }}</div>
        <div v-if="contactSuccess" class="success-message">已提交，我们会尽快与您联系。</div>
        <div class="form-actions contact-form__actions">
          <button type="submit" class="btn btn-primary" :disabled="contactSubmitting">
            {{ contactSubmitting ? '提交中…' : '提交' }}
          </button>
        </div>
        <p id="form-tip" class="footer-meta">
          提交后写入服务器数据库；若提示失败请检查网络或稍后重试。
        </p>
      </form>
    </div>
  </section>
</template>

<style scoped src="./home-view.css"></style>
