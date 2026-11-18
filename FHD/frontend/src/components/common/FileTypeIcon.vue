<template>
  <Icon
    :icon="iconName"
    :width="size"
    :height="size"
    class="file-type-icon"
    :inline="true"
    :aria-hidden="label ? undefined : 'true'"
    :aria-label="label || undefined"
  />
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { Icon } from '@iconify/vue'
import { ensureFileTypeIcons, fileIconName } from '@/utils/fileTypeIcon'

const props = withDefaults(
  defineProps<{
    /** 真实文件名；有扩展名时优先按扩展名取图标。 */
    name?: string
    /** 没有文件名时按业务分类取代表图标（excel/word/pdf/image/...）。 */
    kind?: string
    size?: number | string
    /** 提供后读屏会念出用途，否则视为纯装饰。 */
    label?: string
  }>(),
  { name: '', kind: '', size: 16, label: '' },
)

const iconName = computed(() => fileIconName(props.name || '', props.kind || ''))

watchEffect(() => {
  void ensureFileTypeIcons()
})
</script>

<style scoped>
.file-type-icon {
  flex: 0 0 auto;
  vertical-align: -0.15em;
}
</style>
