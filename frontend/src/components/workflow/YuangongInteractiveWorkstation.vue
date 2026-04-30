<script setup lang="ts">
import { useRouter } from 'vue-router'
import { YUANGONG_EMPLOYEE_SCENE_PNG } from '@/constants/yuangongAssets'
import { YUANGONG_EMPLOYEE_HOTSPOTS } from '@/constants/yuangongEmployeeHotspots'

withDefaults(
  defineProps<{
    /** 头顶状态（与工位卡片一致） */
    statusLine: string
    /** 底部工作流全称（如 panelTitle） */
    workflowFullName: string
  }>(),
  {
    statusLine: '—',
    workflowFullName: '—',
  }
)

const router = useRouter()

function navigate(routeName: string) {
  router.push({ name: routeName })
}
</script>

<template>
  <div class="yiw" role="region" aria-labelledby="yiw-heading">
    <h4 id="yiw-heading" class="yiw-title">工位示意 · 快捷入口</h4>
    <p class="yiw-lead">
      根据场景图划分可点区域：右侧资料夹进入「原材料仓库」（库存数据）。图上沿为当前工位状态，下沿为工作流全称；点击下方某一工位可切换。
    </p>
    <div class="yiw-frame" aria-label="员工工位示意图">
      <img
        class="yiw-img"
        :src="YUANGONG_EMPLOYEE_SCENE_PNG"
        alt="像素风工位：显示器、主机与桌面右侧三本蓝色资料夹"
        width="576"
        height="1024"
        decoding="async"
        fetchpriority="low"
      />
      <div class="yiw-ribbon yiw-ribbon--top" aria-live="polite">
        <span class="yiw-ribbon__k">状态</span>
        <span class="yiw-ribbon__v">{{ statusLine }}</span>
      </div>
      <div class="yiw-ribbon yiw-ribbon--bottom" aria-live="polite">
        <span class="yiw-ribbon__k">工作流</span>
        <span class="yiw-ribbon__v yiw-ribbon__v--title">{{ workflowFullName }}</span>
      </div>
      <button
        v-for="h in YUANGONG_EMPLOYEE_HOTSPOTS"
        :key="h.id"
        type="button"
        class="yiw-hit"
        :style="{
          left: `${h.leftPct}%`,
          top: `${h.topPct}%`,
          width: `${h.widthPct}%`,
          height: `${h.heightPct}%`,
        }"
        :aria-label="h.ariaLabel ?? h.label"
        @click="navigate(h.routeName)"
      >
        <span class="yiw-hit-ring" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.yiw {
  margin-top: 1.25rem;
  padding: 1rem 0 0.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.yiw-title {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.yiw-lead {
  margin: 0 0 0.75rem;
  font-size: 0.8rem;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.65);
}

.yiw-frame {
  position: relative;
  max-width: min(280px, 100%);
  margin: 0 auto;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
}

.yiw-img {
  display: block;
  width: 100%;
  height: auto;
  vertical-align: top;
}

.yiw-ribbon {
  position: absolute;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 2px;
  padding: 6px 8px;
  pointer-events: none;
  background: linear-gradient(
    180deg,
    rgba(15, 23, 42, 0.88) 0%,
    rgba(15, 23, 42, 0.72) 100%
  );
  color: rgba(248, 250, 252, 0.95);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-sizing: border-box;
}

.yiw-ribbon--top {
  top: 0;
  border-radius: 0 0 6px 6px;
  border-top: none;
}

.yiw-ribbon--bottom {
  bottom: 0;
  border-radius: 6px 6px 0 0;
  border-bottom: none;
  background: linear-gradient(
    0deg,
    rgba(15, 23, 42, 0.92) 0%,
    rgba(15, 23, 42, 0.78) 100%
  );
}

.yiw-ribbon__k {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(148, 200, 255, 0.85);
}

.yiw-ribbon__v {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  word-break: break-word;
}

.yiw-ribbon__v--title {
  font-size: 10px;
  font-weight: 600;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.yiw-hit {
  position: absolute;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  box-sizing: border-box;
  z-index: 2;
}

.yiw-hit:focus {
  outline: none;
}

.yiw-hit:focus-visible .yiw-hit-ring {
  opacity: 1;
  box-shadow: 0 0 0 2px rgba(100, 180, 255, 0.95);
}

.yiw-hit:hover .yiw-hit-ring {
  opacity: 0.55;
  background: rgba(120, 200, 255, 0.12);
}

.yiw-hit-ring {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 4px;
  border: 1px dashed rgba(180, 220, 255, 0.45);
  opacity: 0.25;
  transition: opacity 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
  pointer-events: none;
}
</style>
