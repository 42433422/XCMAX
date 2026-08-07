<template>
  <!-- 旧「业务对接」已退役；保留宿主桥接路径以免书签 404，统一进 ETL 数据对接中心 -->
  <div class="page-view" />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
onMounted(() => {
  void router.replace({ name: 'business-docking' })
})
</script>
