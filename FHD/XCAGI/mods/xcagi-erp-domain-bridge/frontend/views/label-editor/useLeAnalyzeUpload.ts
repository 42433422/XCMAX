import { ref, type Ref } from 'vue'

// 拆分自 LabelEditorView.vue script（原 data 中识别状态 + methods 中 triggerFileInput/onFileSelected）；
// 逻辑逐字迁移，行为不变。
export function useLeAnalyzeUpload(deps: {
  fields: Ref<any[]>
  grid: Ref<any>
  uploadedImage: Ref<any>
  canvasWidth: Ref<number>
  canvasHeight: Ref<number>
  templateName: Ref<string>
  drawCanvas: () => void
  getDefaultFields: () => any[]
}) {
  const { fields, grid, uploadedImage, canvasWidth, canvasHeight, templateName, drawCanvas, getDefaultFields } = deps

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
    if (!file) return

    analyzeError.value = ''
    analyzeStage.value = '正在读取图片...'

    const reader = new FileReader()
    reader.onload = async (event) => {
      uploadedImage.value = (event.target as FileReader | null)?.result
      drawCanvas()

      // 进入独立页面后，直接调用后端识别流程（OCR + 网格）
      isAnalyzing.value = true
      analyzeStage.value = '正在上传并识别...'
      try {
        const formData = new FormData()
        formData.append('file', file)
        formData.append('template_name', templateName.value || '标签模板')
        const response = await fetch('/api/templates/analyze', {
          method: 'POST',
          body: formData
        })
        analyzeStage.value = '正在解析识别结果...'
        const res = await response.json()

        if (res?.success) {
          const incomingFields = Array.isArray(res.fields) ? res.fields : []
          fields.value = incomingFields.map((field: any, idx: number) => ({
            id: field.id || idx + 1,
            label: field.label || `字段${idx + 1}`,
            value: field.value || '',
            type: field.type || 'dynamic',
            position: {
              left: Number(field?.position?.left ?? 20),
              top: Number(field?.position?.top ?? 20 + idx * 36),
              width: Number(field?.position?.width ?? 180),
              height: Number(field?.position?.height ?? 30)
            }
          }))
          grid.value = res?.preview_data?.grid || null

          if (res?.preview_data?.image_size) {
            const width = Number(res.preview_data.image_size.width || canvasWidth.value)
            const height = Number(res.preview_data.image_size.height || canvasHeight.value)
            canvasWidth.value = Math.max(300, Math.min(width, 1600))
            canvasHeight.value = Math.max(200, Math.min(height, 1200))
          }

          if (!fields.value.length) {
            fields.value = getDefaultFields()
          }
          drawCanvas()
          analyzeStage.value = '识别完成'
        } else {
          analyzeError.value = res?.message || '识别失败，已保留原图，可手动标注字段'
          analyzeStage.value = '识别失败'
          fields.value = getDefaultFields()
          drawCanvas()
        }
      } catch (err: any) {
        analyzeError.value = `识别失败：${err?.message || '未知错误'}`
        analyzeStage.value = '识别失败'
        fields.value = getDefaultFields()
        drawCanvas()
      } finally {
        isAnalyzing.value = false
      }
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
