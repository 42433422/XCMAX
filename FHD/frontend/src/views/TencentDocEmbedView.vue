<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

const embedUrl = ref(
  (import.meta.env.VITE_TENCENT_DOC_EMBED_URL as string) ||
    'https://docs.qq.com/demo/embed-placeholder',
);
const configured = computed(() => Boolean(import.meta.env.VITE_TENCENT_DOC_EMBED_URL));

onMounted(() => {
  document.title = '在线文档 PoC';
});
</script>

<template>
  <main class="tdoc-poc">
    <header>
      <h1>在线文档 PoC（腾讯文档 iframe）</h1>
      <p class="muted">
        配置 <code>VITE_TENCENT_DOC_EMBED_URL</code> 为腾讯文档 SDK 生成的可嵌入 URL；未配置时显示占位说明。
      </p>
    </header>

    <section v-if="!configured" class="tdoc-placeholder" role="status">
      <p>尚未配置真实嵌入地址。审批附件预览可在此 iframe 中挂载腾讯文档只读页。</p>
      <p>参见 <code>FHD/docs/integration-suite-roadmap.md</code> M5-W3。</p>
    </section>

    <iframe
      v-else
      class="tdoc-frame"
      :src="embedUrl"
      title="腾讯文档嵌入"
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
    />
  </main>
</template>

<style scoped>
.tdoc-poc {
  padding: 16px;
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.tdoc-frame {
  flex: 1;
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  min-height: 480px;
}
.tdoc-placeholder {
  padding: 24px;
  background: #f9fafb;
  border-radius: 8px;
}
</style>
