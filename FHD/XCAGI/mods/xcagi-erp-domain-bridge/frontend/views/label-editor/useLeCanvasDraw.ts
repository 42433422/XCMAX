import { ref, type Ref } from 'vue'
import type { LeField, LeGrid } from './leTypes'

// 拆分自 LabelEditorView.vue script（原 data 中 canvas 相关状态 + methods 中 initCanvas/getDefaultFields/draw* 方法）；
// 逻辑逐字迁移，行为不变。
export function useLeCanvasDraw(deps: {
  fields: Ref<LeField[]>
  grid: Ref<LeGrid | null>
  uploadedImage: Ref<string | null>
  selectedFieldId: Ref<number | null>
  hoverFieldId: Ref<number | null>
  showGrid: Ref<boolean>
  showMerge: Ref<boolean>
}) {
  const { fields, grid, uploadedImage, selectedFieldId, hoverFieldId, showGrid } = deps

  const labelCanvas = ref<HTMLCanvasElement | null>(null)
  const canvasWidth = ref(900)
  const canvasHeight = ref(600)
  const ctx = ref<CanvasRenderingContext2D | null>(null)

  function initCanvas() {
    if (labelCanvas.value) {
      ctx.value = labelCanvas.value.getContext('2d')
    }
  }

  function getDefaultFields(): LeField[] {
    return [
      {
        id: 1,
        label: '产品名称',
        value: '示例产品',
        type: 'fixed',
        position: { left: 50, top: 50, width: 200, height: 30 }
      },
      {
        id: 2,
        label: '规格',
        value: 'XXX',
        type: 'dynamic',
        position: { left: 300, top: 50, width: 150, height: 30 }
      },
      {
        id: 3,
        label: '数量',
        value: '100',
        type: 'dynamic',
        position: { left: 500, top: 50, width: 100, height: 30 }
      },
      {
        id: 4,
        label: '日期',
        value: '2024-01-01',
        type: 'dynamic',
        position: { left: 50, top: 120, width: 200, height: 30 }
      }
    ]
  }

  function drawCanvas() {
    if (!ctx.value) return

    ctx.value!.clearRect(0, 0, canvasWidth.value, canvasHeight.value)

    if (uploadedImage.value) {
      const img = new Image()
      img.onload = () => {
        ctx.value!.drawImage(img, 0, 0, canvasWidth.value, canvasHeight.value)
        drawGridOverlay()
        drawFields()
      }
      img.src = uploadedImage.value
    } else {
      ctx.value!.fillStyle = '#ffffff'
      ctx.value!.fillRect(0, 0, canvasWidth.value, canvasHeight.value)
      drawBorder()
      drawGridOverlay()
      drawFields()
    }
  }

  function drawBorder() {
    ctx.value!.strokeStyle = '#000000'
    ctx.value!.lineWidth = 3
    ctx.value!.strokeRect(0, 0, canvasWidth.value, canvasHeight.value)
  }

  function drawGridOverlay() {
    if (!showGrid.value || !grid.value) return

    ctx.value!.strokeStyle = '#cccccc'
    ctx.value!.lineWidth = 1
    ctx.value!.setLineDash([5, 5])

    if (grid.value.horizontal_lines) {
      grid.value.horizontal_lines.forEach((y) => {
        ctx.value!.beginPath()
        ctx.value!.moveTo(0, y)
        ctx.value!.lineTo(canvasWidth.value, y)
        ctx.value!.stroke()
      })
    }

    if (grid.value.vertical_lines) {
      grid.value.vertical_lines.forEach((x) => {
        ctx.value!.beginPath()
        ctx.value!.moveTo(x, 0)
        ctx.value!.lineTo(x, canvasHeight.value)
        ctx.value!.stroke()
      })
    }

    ctx.value!.setLineDash([])
  }

  function drawFields() {
    fields.value.forEach((field) => {
      drawField(field)
    })
  }

  function drawField(field: LeField) {
    const posX = field.position.left || 0
    const posY = field.position.top || 0
    const width = field.position.width || 100
    const height = field.position.height || 30

    const isSelected = field.id === selectedFieldId.value
    const isHover = field.id === hoverFieldId.value

    if (field.type === 'fixed') {
      ctx.value!.fillStyle = isHover ? '#bbdefb' : '#e3f2fd'
    } else {
      ctx.value!.fillStyle = isHover ? '#c8e6c9' : '#e8f5e9'
    }

    if (isSelected) {
      ctx.value!.strokeStyle = '#ff9800'
      ctx.value!.lineWidth = 3
    } else if (field.type === 'fixed') {
      ctx.value!.strokeStyle = '#2196f3'
      ctx.value!.lineWidth = 2
    } else {
      ctx.value!.strokeStyle = '#4caf50'
      ctx.value!.lineWidth = 2
    }

    ctx.value!.fillRect(posX, posY, width, height)
    ctx.value!.strokeRect(posX, posY, width, height)

    ctx.value!.fillStyle = '#000000'
    ctx.value!.font = 'bold 14px Arial'
    const displayValue = field.type === 'dynamic' && !field.value ? 'X' : (field.value || 'X')
    const text = `${field.label}: ${displayValue}`
    ctx.value!.fillText(text, posX + 5, posY + 20)
  }

  return {
    labelCanvas,
    canvasWidth,
    canvasHeight,
    ctx,
    initCanvas,
    getDefaultFields,
    drawCanvas,
  }
}
