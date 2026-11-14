import { ref, type Ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import type { LeField, LeGrid } from './leTypes'
import { asRecord, labelCanvasSize, normalizeLabelFields, normalizeLabelGrid } from './leTemplateData'

/** /api/templates/analyze 返回（宽松契约） */
interface LeAnalyzeResponse {
  success?: boolean
  message?: string
  fields?: unknown
  preview_data?: {
    grid?: unknown
    image_size?: { width?: number | string; height?: number | string; [key: string]: unknown }
    [key: string]: unknown
  } | null
  [key: string]: unknown
}

// 拆分自 LabelEditorView.vue script（原 data 中识别状态 + methods 中 triggerFileInput/onFileSelected）；
// 逻辑逐字迁移，行为不变。
export function useLeAnalyzeUpload(deps: {
  fields: Ref<LeField[]>
  grid: Ref<LeGrid | null>
  uploadedImage: Ref<string | null>
  canvasWidth: Ref<number>
  canvasHeight: Ref<number>
  templateName: Ref<string>
  drawCanvas: () => void
}) {
  const { fields, grid, uploadedImage, canvasWidth, canvasHeight, templateName, drawCanvas } = deps

  const fileInput = ref<HTMLInputElement | null>(null)
  const isAnalyzing = ref(false)
  const analyzeError = ref('')
  const analyzeStage = ref('')

  function triggerFileInput() {
    const input = fileInput.value
    if (!input) {
      console.warn('fileInput 未就绪，无法打开文件选择器')
      return
    }
    analyzeError.value = ''
    analyzeStage.value = ''
    // 允许重复选择同一文件时也触发 change 事件
    input.value = ''
    input.click()
  }

  async function onFileSelected(e: Event) {
    const input = e?.target as HTMLInputElement | null
    const file = input?.files?.[0]
    if (!file || isAnalyzing.value) return

    isAnalyzing.value = true
    analyzeError.value = ''
    analyzeStage.value = '正在读取图片...'

    const reader = new FileReader()
    reader.onload = async (event) => {
      // FileReader.result 兼容 string | ArrayBuffer | null；原实现假定 dataURL 字符串
      const nextImage = (event.target as FileReader | null)?.result as string | null

      // 进入独立页面后，直接调用后端识别流程（OCR + 网格）
      isAnalyzing.value = true
      analyzeStage.value = '正在上传并识别...'
      try {
        const formData = new FormData()
        formData.append('file', file)
        formData.append('template_name', templateName.value || '标签模板')
        const res = await templatePreviewApi.analyzeTemplate(formData) as LeAnalyzeResponse
        analyzeStage.value = '正在解析识别结果...'

        if (res?.success) {
          const incomingFields = normalizeLabelFields(res.fields)
          if (!incomingFields.length) throw new Error('未识别到有效字段，可重试或手动添加字段。')
          const nextGrid = normalizeLabelGrid(res.preview_data?.grid)
          const size = labelCanvasSize(asRecord(res.preview_data))
          fields.value = incomingFields
          grid.value = nextGrid
          canvasWidth.value = size.width
          canvasHeight.value = size.height
          uploadedImage.value = nextImage
          drawCanvas()
          analyzeStage.value = '识别完成'
        } else {
          throw new Error(res?.message || '识别失败，可重试或手动标注字段')
        }
      } catch (err) {
        analyzeError.value = `识别失败：${err instanceof Error ? (err.message || '未知错误') : String(err)}`
        analyzeStage.value = '识别失败'
        if (!fields.value.length) uploadedImage.value = nextImage
        drawCanvas()
      } finally {
        isAnalyzing.value = false
      }
    }
    reader.onerror = () => {
      analyzeError.value = '图片读取失败，请重新选择文件。编辑内容已保留。'
      analyzeStage.value = '识别失败'
      isAnalyzing.value = false
    }
    reader.readAsDataURL(file)
    // 允许下一次继续选择同一文件
    if (input) {
      input.value = ''
    }
  }

  return {
    fileInput,
    isAnalyzing,
    analyzeError,
    analyzeStage,
    triggerFileInput,
    onFileSelected,
  }
}
