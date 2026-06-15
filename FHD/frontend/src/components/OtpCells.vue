<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: string;
    length?: number;
    disabled?: boolean;
  }>(),
  {
    length: 6,
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const focusedIndex = ref(0);

const digits = computed(() =>
  props.modelValue.replace(/\D/g, '').slice(0, props.length).split(''),
);

watch(
  () => props.modelValue,
  (value) => {
    const clean = value.replace(/\D/g, '').slice(0, props.length);
    if (clean !== value) emit('update:modelValue', clean);
    focusedIndex.value = Math.min(clean.length, props.length - 1);
  },
);

function onInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, props.length);
  emit('update:modelValue', raw);
  focusedIndex.value = Math.min(raw.length, props.length - 1);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Backspace' && props.modelValue.length > 0) {
    const next = props.modelValue.slice(0, -1);
    emit('update:modelValue', next);
    focusedIndex.value = Math.max(0, next.length);
    event.preventDefault();
  }
}

function onPaste(event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text') || '';
  const clean = text.replace(/\D/g, '').slice(0, props.length);
  if (!clean) return;
  event.preventDefault();
  emit('update:modelValue', clean);
  focusedIndex.value = Math.min(clean.length, props.length - 1);
  void nextTick(() => inputRef.value?.blur());
}

onMounted(() => {
  focusedIndex.value = Math.min(props.modelValue.length, props.length - 1);
});
</script>

<template>
  <div class="otp-cells" role="group" aria-label="短信验证码">
    <div class="otp-cells__row">
      <div
        v-for="index in length"
        :key="index"
        class="otp-cells__cell"
        :class="{ 'is-focused': !disabled && digits.length === index - 1 }"
      >
        {{ digits[index - 1] || '' }}
      </div>
      <input
        ref="inputRef"
        class="otp-cells__input"
        type="tel"
        inputmode="numeric"
        autocomplete="one-time-code"
        :disabled="disabled"
        :value="modelValue"
        :maxlength="length"
        aria-label="短信验证码"
        @input="onInput"
        @keydown="onKeydown"
        @paste="onPaste"
        @focus="focusedIndex = Math.min(digits.length, length - 1)"
      />
    </div>
  </div>
</template>

<style scoped>
.otp-cells {
  position: relative;
}

.otp-cells__row {
  position: relative;
  display: flex;
  gap: 8px;
  justify-content: center;
  cursor: text;
}

.otp-cells__cell {
  flex: 1;
  max-width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-lg);
  background: var(--xc-color-surface);
  font-size: 20px;
  font-weight: var(--xc-font-weight-medium);
  color: var(--xc-color-text);
  transition:
    border-color var(--xc-transition-fast),
    box-shadow var(--xc-transition-fast);
}

.otp-cells__cell.is-focused {
  border-color: var(--xc-color-primary);
  box-shadow: 0 0 0 2px var(--xc-color-primary-soft);
}

.otp-cells__input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  border: 0;
  background: transparent;
  color: transparent;
  caret-color: transparent;
}
</style>
