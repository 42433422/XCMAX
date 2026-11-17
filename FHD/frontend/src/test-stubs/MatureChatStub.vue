<template>
  <section>
    <header class="chat-header"><span class="chat-title">{{ title }}</span><span class="chat-subtitle">{{ subtitle }}</span><slot name="actions" /></header>
    <button v-if="hasMore" class="chat-load-older" @click="$emit('load-older')">更早消息</button>
    <div class="chat-body">
      <div v-for="row in rows" :key="row.id" class="chat-row" :class="{ mine:row.mine, theirs:!row.mine, 'is-streaming':row.label === '正在回复' }">
        <span class="chat-avatar"><img v-if="row.avatar" :src="row.avatar" /><span v-else>{{ row.sender?.slice(0,1) || 'A' }}</span></span>
        <span class="chat-sender">{{ row.sender }}</span><span class="chat-label">{{ row.label }}</span><p class="chat-message">{{ row.body }}</p>
      </div><span v-if="!rows.length" class="chat-empty">暂无消息</span>
    </div>
    <p v-if="disabled" class="chat-busy">{{ busyLabel }}</p>
    <form class="chat-form" @submit.prevent="send">
      <input class="chat-input" :value="draft" :disabled="disabled" @input="$emit('update:draft', ($event.target as HTMLInputElement).value)" @keyup.enter="send" @keydown.enter.prevent="send" />
      <button class="chat-send" type="button" :disabled="disabled || !draft?.trim()" @click="send">发送</button>
    </form>
  </section>
</template>
<script setup lang="ts">
import type { ChatRow } from '@/components/im/MatureChat.vue'
const props = defineProps<{ title:string; subtitle?:string; rows:ChatRow[]; draft?:string; disabled?:boolean; hasMore?:boolean; busyLabel?:string }>()
const emit = defineEmits(['send','update:draft','load-older'])
function send() { if (!props.disabled && props.draft?.trim()) emit('send',props.draft.trim()) }
</script>
