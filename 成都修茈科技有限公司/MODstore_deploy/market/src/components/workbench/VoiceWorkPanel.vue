<template>
  <div class="vwp">
    <div
      v-for="(step, i) in steps"
      :key="i"
      class="vwp-step"
      :class="'vwp-step--' + step.status"
    >
      <span class="vwp-icon">
        <svg
          v-if="step.status === 'done'"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M3 7.5L5.8 10.3L11 4.7"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <svg
          v-else-if="step.status === 'active'"
          class="vwp-spin"
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M7 1.5a5.5 5.5 0 1 1-4.78 2.77"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
          />
        </svg>
        <svg
          v-else
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle
            cx="7"
            cy="7"
            r="4.5"
            stroke="currentColor"
            stroke-width="1.2"
          />
        </svg>
      </span>
      <span class="vwp-label">{{ step.label }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  steps: {
    type: Array,
    default: () => []
  }
})
</script>

<style scoped>
.vwp {
  max-width: 320px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vwp-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  line-height: 1.4;
  transition: color 0.2s;
}

.vwp-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.vwp-step--done .vwp-icon {
  color: #34c759;
}

.vwp-step--done .vwp-label {
  color: rgba(255, 255, 255, 0.85);
}

.vwp-step--active .vwp-icon {
  color: #818cf8;
}

.vwp-step--active .vwp-label {
  color: #fff;
}

.vwp-step--pending .vwp-icon {
  color: rgba(255, 255, 255, 0.15);
}

.vwp-step--pending .vwp-label {
  color: rgba(255, 255, 255, 0.3);
}

@keyframes vwp-rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.vwp-spin {
  animation: vwp-rotate 1s linear infinite;
}

@keyframes vwp-flash {
  0% {
    background-color: rgba(129, 140, 248, 0.25);
  }
  100% {
    background-color: transparent;
  }
}

.vwp-step--done {
  animation: vwp-flash 0.5s ease-out;
}

html[data-workbench-theme='light'] .vwp-step--done .vwp-icon {
  color: #34c759;
}

html[data-workbench-theme='light'] .vwp-step--done .vwp-label {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .vwp-step--active .vwp-icon {
  color: #0071e3;
}

html[data-workbench-theme='light'] .vwp-step--active .vwp-label {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .vwp-step--pending .vwp-icon {
  color: #c7c7cc;
}

html[data-workbench-theme='light'] .vwp-step--pending .vwp-label {
  color: #86868b;
}

html[data-workbench-theme='light'] .vwp-step--done {
  animation: vwp-flash-light 0.5s ease-out;
}

@keyframes vwp-flash-light {
  0% {
    background-color: rgba(0, 113, 227, 0.12);
  }
  100% {
    background-color: transparent;
  }
}
</style>
