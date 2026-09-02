<script setup lang="ts">
// 拆分自 HomeView.vue 模板（原第 383–424 行）；模板逐字迁移，行为不变。
import type { RouteLocationRaw } from 'vue-router'

defineProps<{
  isLoggedIn: boolean
  workbenchLink: RouteLocationRaw
}>()
</script>

<template>
  <footer class="footer">
    <div class="container">
      <div class="footer-grid">
        <div class="footer-brand">
          <span class="footer-logo">XC AGI</span>
          <p class="footer-desc">AI 单据智能处理系统</p>
        </div>
        <div class="footer-links">
          <div class="footer-col">
            <h4 class="footer-heading">产品</h4>
            <router-link to="/" class="footer-link">首页</router-link>
            <router-link :to="{ name: 'ai-store' }" class="footer-link">AI 市场</router-link>
            <router-link to="/plans" class="footer-link">套餐</router-link>
            <a href="/download" class="footer-link" target="_blank" rel="noopener">软件下载</a>
          </div>
          <div class="footer-col">
            <h4 class="footer-heading">支持</h4>
            <router-link :to="workbenchLink" class="footer-link">{{ isLoggedIn ? '工作台' : '登录' }}</router-link>
            <router-link v-if="!isLoggedIn" to="/register" class="footer-link">注册</router-link>
          </div>
        </div>
      </div>
      <div class="footer-bottom">
        <p class="footer-legal">© 2026 成都修茈科技有限公司 保留所有权利。</p>
        <p class="footer-contact">
          地址：（请填写公司地址）
          <span class="footer-contact-sep" aria-hidden="true">·</span>
          邮箱：<a class="footer-mail" href="mailto:970882904@qq.com">970882904@qq.com</a>
        </p>
        <p class="footer-beian">
          <a
            class="footer-beian-link"
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
          >蜀ICP备2026014056号-3A</a>
          <span class="footer-beian-sep" aria-hidden="true">·</span>
          <span class="footer-beian-police">川公网安备13f68c61238ea5b1f4c4887c942a0d55号</span>
        </p>
      </div>
    </div>
  </footer>
</template>

<style scoped src="./home-view.css"></style>
