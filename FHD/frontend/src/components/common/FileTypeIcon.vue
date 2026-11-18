<template>
  <Icon
    v-if="ready"
    :icon="iconName"
    :width="size"
    :height="size"
    class="file-type-icon"
    :inline="true"
    :aria-hidden="label ? undefined : 'true'"
    :aria-label="label || undefined"
  />
  <span v-else class="file-type-icon fa fa-file-o" :style="{ fontSize: typeof size === 'number' ? `${size}px` : size }" :aria-hidden="label ? undefined : 'true'" :aria-label="label || undefined" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { ensureFileTypeIcons, fileIconName } from '@/utils/fileTypeIcon'

const props = withDefaults(
  defineProps<{
    /** 真实文件名；有扩展名时优先按扩展名取图标。 */
    name?: string
    /** 没有文件名或扩展名时按业务分类取代表图标（excel/word/pdf/image/...）。 */
    kind?: string
    size?: number | string
    /** 提供后读屏会念出用途，否则视为纯装饰。 */
    label?: string
  }>(),
  { name: '', kind: '', size: 16, label: '' },
)

const iconName = computed(() => fileIconName(props.name || '', props.kind || ''))

const ready = ref(false)
watch(iconName, async () => {
  ready.value = await ensureFileTypeIcons()
}, { immediate: true })
</script>

<style scoped>
.file-type-icon {
  flex: 0 0 auto;
  vertical-align: -0.15em;
}
</style>
