<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { LEGAL_DOCUMENTS } from '@/constants/legalDocuments'

const props = defineProps<{ document: keyof typeof LEGAL_DOCUMENTS }>()
const route = useRoute()
const documentContent = computed(() => LEGAL_DOCUMENTS[props.document])
watchEffect(() => { document.title = `${documentContent.value.title} · XCAGI` })
</script>

<template>
  <main class="login-legal" :aria-label="documentContent.title">
    <article>
      <RouterLink :to="{ name: 'login', query: route.query }">返回登录</RouterLink>
      <h1>{{ documentContent.title }}</h1>
      <p role="note">审阅草案，尚未作为生效条款发布。</p>
      <p>版本 {{ documentContent.version }} · 更新日期 {{ documentContent.updatedAt }} · 生效日期 {{ documentContent.effectiveAt }}</p>
      <section v-for="section in documentContent.sections" :key="section.title">
        <h2>{{ section.title }}</h2>
        <p v-for="(paragraph, index) in section.paragraphs" :key="index">{{ paragraph }}</p>
      </section>
      <footer><a href="mailto:970882904@qq.com">隐私联系：970882904@qq.com</a></footer>
    </article>
  </main>
</template>

<style scoped>
.login-legal { min-height: 100vh; overflow-y: auto; padding: 2rem 1rem; background: #f3f4f7; color: #1f2937; line-height: 1.8; }
article { max-width: 48rem; margin: auto; padding: 2rem; background: #fff; border-radius: 12px; overflow-wrap: anywhere; }
h1 { font-size: 1.6rem; }
h2 { margin-top: 1.5rem; font-size: 1.1rem; }
a { color: #0052d9; }
@media (max-width: 520px) { article { padding: 1rem; } }
</style>
