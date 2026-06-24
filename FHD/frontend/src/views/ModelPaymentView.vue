<template>
  <div class="page-view" id="view-model-payment" aria-busy="true" aria-label="正在跳转到系统设置">
    <div class="redirect-loading" role="status">
      <div class="loading-spinner" aria-hidden="true" />
      <p class="loading-text">正在跳转到系统设置...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';

const router = useRouter();

onMounted(() => {
  void router.replace({
    name: 'settings',
    query: { section: 'model-payment' },
  });
});
</script>

<style scoped>
.redirect-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 60vh;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(0, 0, 0, 0.1);
  border-top-color: rgba(0, 0, 0, 0.55);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-text {
  margin: 0;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.55);
}
</style>
