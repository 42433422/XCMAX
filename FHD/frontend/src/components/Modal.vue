<template>
  <!-- Teleport 到 body，避免侧栏 transform/overflow 把 fixed 遮罩困在侧栏里 -->
  <Teleport to="body">
    <div class="modal" :class="{ visible: modelValue }" @click.self="handleClose">
      <div class="modal-content" :style="contentStyle">
        <div class="modal-header" v-if="title">
          {{ title }}
        </div>
        <div class="modal-body">
          <slot></slot>
        </div>
        <div class="modal-footer" v-if="$slots.footer">
          <slot name="footer"></slot>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: '',
  },
  maxWidth: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['update:modelValue', 'close'])

const contentStyle = computed(() => {
  const style = {}
  if (props.maxWidth) {
    style.maxWidth = props.maxWidth
  }
  return style
})

const handleClose = () => {
  emit('update:modelValue', false)
  emit('close')
}
</script>

<style scoped>
.modal {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 10050;
  justify-content: center;
  align-items: center;
}

.modal.visible {
  display: flex;
}

.modal-content {
  background: white;
  border-radius: 8px;
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e0e0e0;
  font-size: 18px;
  font-weight: 600;
}

.modal-body {
  padding: 20px;
}

.modal-footer {
  padding: 16px 20px;
  border-top: 1px solid #e0e0e0;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
</style>
