<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  YUANGONG_DESK_PNG,
  YUANGONG_DESK_SVG,
  YUANGONG_STAFF_PNG,
  YUANGONG_STAFF_SVG,
  YUANGONG_STAFF_BUSY_PNG,
  YUANGONG_STAFF_BUSY_SVG,
  YUANGONG_FALLBACK_DESK,
  YUANGONG_FALLBACK_STAFF,
  YUANGONG_FALLBACK_STAFF_BUSY,
} from '@/constants/yuangongAssets'

const props = withDefaults(
  defineProps<{
    /** 副窗「一键托管」是否启用该员工：未启用仅显示工位层 */
    enabled: boolean
    /** 已启用且快照为忙时，使用 staff-busy */
    busy: boolean
    ariaLabel: string
    /**
     * composed 且父级已铺全景底图时置为 false：未启用副窗不再叠 desk.png，由底图承担工位画面。
     */
    composedIdleDeskVisible?: boolean
    /**
     * default：desk + 小 staff 叠层；composed：由父级定宽高，单格铺满——副窗开=员工图，副窗关=工位图
     */
    pixelLayout?: 'default' | 'composed'
    /**
     * default：未启用副窗时不叠 staff；composed 模式不按此属性切换（由 enabled 决定工位/员工整格）
     */
    alwaysShowStaff?: boolean
  }>(),
  { pixelLayout: 'default', alwaysShowStaff: false, composedIdleDeskVisible: true }
)

const deskSrc = ref(YUANGONG_DESK_PNG)
const staffSrc = ref(YUANGONG_STAFF_PNG)

const showStaffLayer = computed(() => props.enabled || props.alwaysShowStaff === true)

/** 仅启用且忙时用 busy 素材；alwaysShowStaff 且未启用时固定 idle */
function staffPrimaryPng() {
  if (props.enabled && props.busy) return YUANGONG_STAFF_BUSY_PNG
  return YUANGONG_STAFF_PNG
}

function staffPrimarySvg() {
  if (props.enabled && props.busy) return YUANGONG_STAFF_BUSY_SVG
  return YUANGONG_STAFF_SVG
}

function fallbackStaffFinal() {
  return props.enabled && props.busy ? YUANGONG_FALLBACK_STAFF_BUSY : YUANGONG_FALLBACK_STAFF
}

watch(
  () => [props.enabled, props.busy, props.alwaysShowStaff, props.pixelLayout] as const,
  () => {
    if (props.pixelLayout === 'composed') {
      if (props.enabled) staffSrc.value = staffPrimaryPng()
      return
    }
    if (!showStaffLayer.value) return
    staffSrc.value = staffPrimaryPng()
  },
  { immediate: true }
)

function onDeskError() {
  if (deskSrc.value === YUANGONG_DESK_PNG) {
    deskSrc.value = YUANGONG_DESK_SVG
  } else if (deskSrc.value === YUANGONG_DESK_SVG) {
    deskSrc.value = YUANGONG_FALLBACK_DESK
  }
}

function onStaffError() {
  const primary = staffPrimaryPng()
  const mid = staffPrimarySvg()
  const finalFb = fallbackStaffFinal()
  if (staffSrc.value === primary) {
    staffSrc.value = mid
  } else if (staffSrc.value === mid) {
    staffSrc.value = finalFb
  }
}
</script>

<template>
  <div
    class="yuangong-stack"
    :class="{ 'yuangong-stack--composed': pixelLayout === 'composed' }"
    role="group"
    :aria-label="ariaLabel"
  >
    <template v-if="pixelLayout === 'composed'">
      <img
        v-if="composedIdleDeskVisible"
        class="yuangong-composed-figure yuangong-composed-desk"
        :src="deskSrc"
        alt=""
        decoding="async"
        @error="onDeskError"
      />
      <img
        v-if="enabled"
        class="yuangong-composed-figure yuangong-composed-staff"
        :class="{ 'yuangong-composed-figure--bob': busy }"
        :src="staffSrc"
        alt=""
        decoding="async"
        @error="onStaffError"
      />
    </template>
    <template v-else>
      <img
        class="yuangong-desk"
        :src="deskSrc"
        alt=""
        decoding="async"
        @error="onDeskError"
      />
      <img
        v-if="showStaffLayer"
        class="yuangong-staff"
        :class="{ 'yuangong-staff--bob': enabled && busy }"
        :src="staffSrc"
        alt=""
        decoding="async"
        @error="onStaffError"
      />
    </template>
  </div>
</template>

<style scoped>
.yuangong-stack {
  position: relative;
  width: 80px;
  height: 58px;
  image-rendering: pixelated;
}

.yuangong-stack--composed {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  box-sizing: border-box;
  overflow: visible;
}

/* 横拼：desk 铺满并略溢出，组内负 margin 叠格后消除竖缝 */
.yuangong-composed-figure {
  display: block;
  image-rendering: pixelated;
  pointer-events: none;
}

.yuangong-composed-desk {
  width: 108%;
  height: 100%;
  margin-left: -4%;
  object-fit: cover;
  object-position: center bottom;
}

.yuangong-composed-staff {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  width: 52%;
  max-width: 100%;
  height: 88%;
  margin: 0 auto;
  object-fit: contain;
  object-position: center bottom;
}

@media (prefers-reduced-motion: no-preference) {
  .yuangong-composed-figure--bob {
    animation: yuangong-bob-composed 1.1s ease-in-out infinite;
  }
}

.yuangong-desk {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center bottom;
  image-rendering: pixelated;
}

.yuangong-staff {
  position: absolute;
  left: 20px;
  top: 0;
  max-width: 50px;
  max-height: 56px;
  width: auto;
  height: auto;
  object-fit: contain;
  image-rendering: pixelated;
  pointer-events: none;
}

@media (prefers-reduced-motion: no-preference) {
  .yuangong-staff--bob {
    animation: yuangong-bob 1.1s ease-in-out infinite;
  }
}

@keyframes yuangong-bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-3px);
  }
}

@keyframes yuangong-bob-composed {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-3px);
  }
}
</style>
