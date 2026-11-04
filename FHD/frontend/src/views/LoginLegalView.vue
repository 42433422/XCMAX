<script setup lang="ts">
import { computed, defineComponent, h, watchEffect, type VNodeChild } from 'vue'
import { useRoute } from 'vue-router'
import { LEGAL_DOCUMENTS } from '@/constants/legalDocuments'

const props = defineProps<{ document: keyof typeof LEGAL_DOCUMENTS }>()
const route = useRoute()
const documentKind = computed(() => props.document === 'model-recipients' ? 'privacy-policy' : props.document)
const documentContent = computed(() => LEGAL_DOCUMENTS[documentKind.value])
watchEffect(() => { document.title = `${documentContent.value.title} · XCAGI` })
const LegalText = defineComponent({
  props: { value: { type: String, required: true } },
  setup: text => () => {
    const parts: VNodeChild[] = []
    let offset = 0
    for (const match of text.value.matchAll(/\*\*([^*]+)\*\*|\[([^\]]+)\]\((https:\/\/[^\s)]+)\)|(https:\/\/[^\s)），。；]+)/g)) {
      parts.push(text.value.slice(offset, match.index))
      parts.push(match[1] ? h('strong', match[1]) : h('a', { href: match[3] || match[4], target: '_blank', rel: 'noopener noreferrer' }, match[2] || match[4]))
      offset = match.index! + match[0].length
    }
    parts.push(text.value.slice(offset))
    return h('span', parts)
  },
})
</script>

<template>
  <main class="login-legal" :aria-label="documentContent.title">
    <article>
      <RouterLink :to="{ name: 'login', query: route.query }">返回登录</RouterLink>
      <nav aria-label="协议与隐私政策">
        <RouterLink v-for="key in (['service-agreement', 'privacy-policy'] as const)" :key="key" :to="{ name: 'login-legal', params: { document: key }, query: route.query }" :aria-current="key === documentKind ? 'page' : undefined">{{ LEGAL_DOCUMENTS[key].title }}</RouterLink>
      </nav>
      <h1>{{ documentContent.title }}</h1>
      <p>版本 {{ documentContent.version }} · 修订日期 {{ documentContent.updatedAt }}</p>
      <section v-for="section in documentContent.sections" :key="section.title">
        <h2 v-if="section.title">{{ section.title }}</h2>
        <template v-for="(block, index) in section.blocks" :key="index">
          <p v-if="block.paragraph"><LegalText :value="block.paragraph" /></p>
          <ul v-if="block.items"><li v-for="(item, itemIndex) in block.items" :key="itemIndex"><LegalText :value="item" /></li></ul>
          <div v-if="block.table" class="legal-table">
            <table><caption>{{ documentContent.title }}</caption>
              <thead><tr><th v-for="column in block.table.columns" :key="column" scope="col">{{ column }}</th></tr></thead>
              <tbody><tr v-for="(row, rowIndex) in block.table.rows" :key="rowIndex">
                <th scope="row"><LegalText :value="row[0]" /></th><td v-for="(cell, cellIndex) in row.slice(1)" :key="cellIndex"><LegalText :value="cell" /></td>
              </tr></tbody>
            </table>
          </div>
        </template>
      </section>
      <footer><a href="mailto:970882904@qq.com">隐私联系：970882904@qq.com</a></footer>
    </article>
  </main>
</template>

<style scoped>
.login-legal { min-height: 100vh; overflow-y: auto; padding: 2rem 1rem; background: var(--xc-color-page-bg); color: var(--xc-color-text); line-height: 1.8; }
article { max-width: 48rem; margin: auto; padding: 2rem; background: var(--xc-color-surface); border-radius: var(--xc-radius-lg, 12px); overflow-wrap: anywhere; }
h1 { font-size: 1.6rem; }
h2 { margin-top: 1.5rem; font-size: 1.1rem; }
a { color: var(--xc-color-primary); text-underline-offset: 2px; }
a:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: 3px; }
nav { display: flex; flex-wrap: wrap; gap: .5rem 1rem; margin-top: 1rem; }
.legal-table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { border: 1px solid var(--xc-color-border); padding: .5rem; text-align: left; vertical-align: top; }
tbody th { min-width: 7rem; }
@media (max-width: 520px) { article { padding: 1rem; } }
</style>
