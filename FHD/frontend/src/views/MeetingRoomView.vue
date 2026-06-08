<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

const appId = computed(() => (import.meta.env.VITE_AGORA_APP_ID as string) || '');
const channel = ref('xcagi-demo-1v1');
const token = ref('');
const uid = ref(String(Math.floor(Math.random() * 9000) + 1000));
const status = ref('未连接');
const errorMessage = ref('');
const localVideoRef = ref<HTMLDivElement | null>(null);
const remoteVideoRef = ref<HTMLDivElement | null>(null);

async function joinRoom() {
  errorMessage.value = '';
  if (!appId.value) {
    errorMessage.value = '请配置 VITE_AGORA_APP_ID（声网 PoC）';
    return;
  }
  status.value = '待接入';
  errorMessage.value =
    'PoC 壳页已就绪。接入步骤：cd frontend && npm install agora-rtc-sdk-ng，在此页实现 join/publish（见 integration-suite-roadmap.md）。';
}

async function leaveRoom() {
  status.value = '已离开';
  errorMessage.value = '';
}

onMounted(() => {
  document.title = '会议 PoC · 声网';
});

</script>

<template>
  <main class="meeting-poc">
    <header class="meeting-poc-head">
      <h1>音视频 PoC（声网 Agora 1v1）</h1>
      <p class="muted">P2 集成验证页；生产需 Token 服务与合规说明。</p>
    </header>

    <section class="meeting-poc-form">
      <label>
        频道名
        <input v-model="channel" type="text" />
      </label>
      <label>
        UID
        <input v-model="uid" type="text" />
      </label>
      <label>
        Token（可选）
        <input v-model="token" type="text" placeholder="测试项目可留空" />
      </label>
      <p>状态：{{ status }}</p>
      <p v-if="errorMessage" class="meeting-error" role="alert">{{ errorMessage }}</p>
      <div class="meeting-actions">
        <button type="button" @click="joinRoom">加入</button>
        <button type="button" class="secondary" @click="leaveRoom">离开</button>
      </div>
    </section>

    <section class="meeting-videos">
      <div>
        <h2>本地</h2>
        <div ref="localVideoRef" class="video-box" />
      </div>
      <div>
        <h2>远端</h2>
        <div ref="remoteVideoRef" class="video-box" />
      </div>
    </section>
  </main>
</template>

<style scoped>
.meeting-poc {
  padding: 24px;
  max-width: 960px;
  margin: 0 auto;
}
.meeting-poc-form label {
  display: block;
  margin-bottom: 12px;
}
.meeting-poc-form input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 8px;
}
.meeting-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.meeting-actions button {
  padding: 8px 16px;
}
.meeting-videos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 24px;
}
.video-box {
  min-height: 200px;
  background: #111;
  border-radius: 8px;
}
.meeting-error {
  color: #b91c1c;
}
</style>
