<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="nav-self-credit-overlay nav-admin-digest-unlock-overlay"
      role="presentation"
      @click.self="onCancel"
    >
      <div
        class="nav-self-credit-dialog"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        @click.stop
        @keydown.esc.prevent="onCancel"
      >
        <h3 class="nav-self-credit-dialog__title">{{ title }}</h3>
        <p class="nav-self-credit-dialog__hint">
          <template v-if="hint">{{ hint }}<br /></template>
          请输入<strong>连续 6 位</strong>十六进制身份校验码（与顶栏「解锁管理端」相同，可从 XCmax 页眉<strong>身份码</strong>或当日摘要邮件复制）。
          <span class="nav-admin-unlock__hint-warn">须与当前浏览器所连市场 API 为同一套 MODstore。</span>
        </p>
        <label class="nav-self-credit-dialog__label">身份校验码</label>
        <input
          :value="code"
          type="text"
          maxlength="32"
          inputmode="text"
          autocomplete="off"
          spellcheck="false"
          class="nav-self-credit-dialog__input nav-admin-unlock__code"
          placeholder="粘贴 6 位码"
          @input="emit('update:code', ($event.target as HTMLInputElement).value)"
          @blur="emit('blur-code')"
          @keyup.enter="emit('submit')"
        />
        <p v-if="error" class="nav-self-credit-dialog__err">{{ error }}</p>
        <div class="nav-self-credit-dialog__actions">
          <button type="button" class="nav-self-credit-dialog__primary" :disabled="busy" @click="emit('submit')">
            {{ busy ? '校验中…' : submitLabel }}
          </button>
          <button type="button" class="nav-self-credit-dialog__secondary" @click="onCancel">
            取消
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  open: boolean
  code: string
  error: string
  busy: boolean
  title: string
  submitLabel: string
  hint?: string
}>()

const emit = defineEmits<{
  'update:code': [value: string]
  'blur-code': []
  submit: []
  cancel: []
}>()

function onCancel() {
  emit('cancel')
}
</script>

<style scoped>
/* 高于悬浮管家球/面板（~20006）与企业联系弹窗（26000） */
.nav-admin-digest-unlock-overlay {
  z-index: 28000;
}
</style>
