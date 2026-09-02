<script setup>
// 副窗标签栏：由 TopAssistantFloat.vue 模板机械切分而来（行为保持不变）。
defineProps({
  activeTab: { type: String, default: 'push' },
})

defineEmits(['select', 'open-tutorial'])
</script>

<template>
  <div class="assistant-tabs" role="tablist" aria-label="副窗分区">
    <button
      type="button"
      class="assistant-tab"
      role="tab"
      data-tutorial-id="tab-push"
      :aria-selected="activeTab === 'push'"
      :tabindex="activeTab === 'push' ? 0 : -1"
      :class="{ active: activeTab === 'push' }"
      @click="$emit('select', 'push')"
    >
      推送
    </button>
    <button
      type="button"
      class="assistant-tab"
      role="tab"
      data-tutorial-id="tab-assistant"
      :aria-selected="activeTab === 'assistant'"
      :tabindex="activeTab === 'assistant' ? 0 : -1"
      :class="{ active: activeTab === 'assistant' }"
      @click="$emit('select', 'assistant')"
    >
      协助副窗
    </button>
    <button
      type="button"
      class="assistant-tab"
      role="tab"
      data-tutorial-id="tab-starterPack"
      :aria-selected="activeTab === 'starterPack'"
      :tabindex="activeTab === 'starterPack' ? 0 : -1"
      :class="{ active: activeTab === 'starterPack' }"
      @click="$emit('select', 'starterPack')"
    >
      新手对话包
    </button>
    <button
      type="button"
      class="assistant-tab"
      role="tab"
      data-tutorial-id="tab-tutorial"
      :aria-selected="activeTab === 'tutorial'"
      :tabindex="activeTab === 'tutorial' ? 0 : -1"
      :class="{ active: activeTab === 'tutorial' }"
      @click="$emit('open-tutorial')"
    >
      新手教程
    </button>
  </div>
</template>

<style scoped src="./top-assistant-float.css"></style>
