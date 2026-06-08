<script setup lang="ts">
defineProps<{
  mode: 'image' | 'video'
}>()

const imageSize = defineModel<string>('imageSize', { default: '1024x1024' })
const imageStyle = defineModel<string>('imageStyle', { default: 'default' })
const imageCount = defineModel<number>('imageCount', { default: 1 })

const videoAspect = defineModel<string>('videoAspect', { default: '16:9' })
const videoDurationSec = defineModel<number>('videoDurationSec', { default: 10 })
</script>

<template>
  <aside
    class="wb-direct-media-rail"
    :class="[`wb-direct-media-rail--${mode}`]"
    :aria-label="mode === 'image' ? '生图参数' : '生视频参数'"
  >
    <header class="wb-direct-media-rail__head">
      <span class="wb-direct-media-rail__badge" aria-hidden="true">
        {{ mode === 'image' ? '生图' : '生视频' }}
      </span>
      <span class="wb-direct-media-rail__title">参数</span>
    </header>

    <div class="wb-direct-media-rail__fields">
      <template v-if="mode === 'image'">
        <label class="wb-direct-media-rail__field">
          <span class="wb-direct-media-rail__label">尺寸</span>
          <select v-model="imageSize" class="wb-direct-media-rail__input">
            <option value="1024x1024">1:1 (1024)</option>
            <option value="1024x1536">2:3 竖图</option>
            <option value="1536x1024">3:2 横图</option>
            <option value="768x1280">9:16 手机</option>
          </select>
        </label>
        <label class="wb-direct-media-rail__field">
          <span class="wb-direct-media-rail__label">风格</span>
          <select v-model="imageStyle" class="wb-direct-media-rail__input">
            <option value="default">默认</option>
            <option value="photo">摄影</option>
            <option value="anime">二次元</option>
            <option value="3d">3D 渲染</option>
            <option value="ink">水墨</option>
          </select>
        </label>
        <label class="wb-direct-media-rail__field">
          <span class="wb-direct-media-rail__label">数量</span>
          <select v-model.number="imageCount" class="wb-direct-media-rail__input">
            <option :value="1">1 张</option>
            <option :value="2">2 张</option>
            <option :value="4">4 张</option>
          </select>
        </label>
      </template>

      <template v-else>
        <label class="wb-direct-media-rail__field">
          <span class="wb-direct-media-rail__label">画幅</span>
          <select v-model="videoAspect" class="wb-direct-media-rail__input">
            <option value="16:9">16:9 横屏</option>
            <option value="9:16">9:16 竖屏</option>
            <option value="1:1">1:1 方形</option>
          </select>
        </label>
        <label class="wb-direct-media-rail__field">
          <span class="wb-direct-media-rail__label">时长</span>
          <select v-model.number="videoDurationSec" class="wb-direct-media-rail__input">
            <option :value="5">约 5 秒</option>
            <option :value="10">约 10 秒</option>
            <option :value="15">约 15 秒</option>
          </select>
        </label>
      </template>
    </div>
  </aside>
</template>
