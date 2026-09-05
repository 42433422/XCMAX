import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLeCanvasDraw } from './useLeCanvasDraw'
import { useLeFieldInteraction } from './useLeFieldInteraction'
import { useLeAnalyzeUpload } from './useLeAnalyzeUpload'
import { useLeSave } from './useLeSave'
import { useLeTemplate } from './useLeTemplate'
import type { LeField, LeFieldId, LeGrid } from './leTypes'

// 组装 LabelEditorView 的全部状态与动作（拆分自原 Options API script，逻辑逐字迁移，行为不变）。
export function assembleLabelEditor() {
  const route = useRoute()
  const router = useRouter()

  // 原组件 data 中的共享状态
  const fields = ref<LeField[]>([])
  const grid = ref<LeGrid | null>(null)
  const imageSize = ref({ width: 900, height: 600 })
  const selectedField = ref<LeField | null>(null)
  const selectedFieldId = ref<LeFieldId | null>(null)
  const hoverFieldId = ref<LeFieldId | null>(null)
  const scale = ref(1)
  const zoom = ref(1)
  const showGrid = ref(true)
  const showMerge = ref(true)
  const uploadedImage = ref<string | null>(null)
  const templateName = ref('标签模板')

  const draw = useLeCanvasDraw({
    fields, grid, uploadedImage, selectedFieldId, hoverFieldId, showGrid, showMerge,
  })
  const { canvasWidth, canvasHeight } = draw

  const interaction = useLeFieldInteraction({
    fields, selectedField, selectedFieldId, hoverFieldId,
    labelCanvas: draw.labelCanvas,
    drawCanvas: draw.drawCanvas,
  })

  const analyze = useLeAnalyzeUpload({
    fields, grid, uploadedImage, canvasWidth, canvasHeight, templateName,
    drawCanvas: draw.drawCanvas,
  })

  const template = useLeTemplate({
    route, fields, grid, uploadedImage, canvasWidth, canvasHeight, templateName,
    drawCanvas: draw.drawCanvas,
    clearSelection: () => {
      selectedField.value = null
      selectedFieldId.value = null
      hoverFieldId.value = null
    },
  })
  const canSave = computed(() => template.templateReady.value && !template.loadingTemplate.value
    && !analyze.isAnalyzing.value && fields.value.length > 0)
  const save = useLeSave({
    fields, grid, uploadedImage, canvasWidth, canvasHeight, templateName, router,
    sourceTemplate: template.sourceTemplate, canSave,
  })

  // 原 mounted 钩子
  onMounted(async () => {
    draw.initCanvas()
    await template.loadTemplate()
    const autoUpload = !route.query.templateId && route.query.autoUpload === '1'
    if (autoUpload) {
      nextTick(() => {
        analyze.triggerFileInput()
      })
    }

    draw.drawCanvas()
  })
  watch(() => route.query.templateId, () => { void template.loadTemplate() })

  // 原 watch 配置
  watch(fields, () => {
    draw.drawCanvas()
  }, { deep: true })
  watch(showGrid, () => {
    draw.drawCanvas()
  })
  watch(showMerge, () => {
    draw.drawCanvas()
  })
  watch(zoom, () => {
    draw.drawCanvas()
  })

  return {
    // 原组件 data 中的其余状态
    zoom,
    scale,
    imageSize,
    selectedField,
    templateName,
    fields,
    grid,
    uploadedImage,
    selectedFieldId,
    hoverFieldId,
    showGrid,
    showMerge,
    canSave,
    ...template,
    // canvas 绘制
    ...draw,
    // 交互与字段编辑
    ...interaction,
    // 上传识别
    ...analyze,
    // 保存
    ...save,
  }
}

export type LabelEditorCtx = ReturnType<typeof assembleLabelEditor>
