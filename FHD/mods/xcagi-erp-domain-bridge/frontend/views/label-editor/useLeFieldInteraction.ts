import { ref, type Ref } from 'vue'
import type { LeField, LeFieldId } from './leTypes'

// 拆分自 LabelEditorView.vue script（原 data 中拖拽相关状态 + methods 中鼠标交互与字段增删方法）；
// 逻辑逐字迁移，行为不变。
export function useLeFieldInteraction(deps: {
  fields: Ref<LeField[]>
  selectedField: Ref<LeField | null>
  selectedFieldId: Ref<LeFieldId | null>
  hoverFieldId: Ref<LeFieldId | null>
  labelCanvas: Ref<HTMLCanvasElement | null>
  drawCanvas: () => void
}) {
  const { fields, selectedField, selectedFieldId, hoverFieldId, labelCanvas, drawCanvas } = deps

  const isDragging = ref(false)
  const dragOffset = ref({ x: 0, y: 0 })

  function canvasPoint(e: MouseEvent) {
    const canvas = labelCanvas.value!
    const rect = canvas.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) * (rect.width ? canvas.width / rect.width : 1),
      y: (e.clientY - rect.top) * (rect.height ? canvas.height / rect.height : 1),
    }
  }

  function getFieldAtPosition(mouseX: number, mouseY: number) {
    for (let i = fields.value.length - 1; i >= 0; i--) {
      const field = fields.value[i]
      const posX = field.position.left || 0
      const posY = field.position.top || 0
      const width = field.position.width || 100
      const height = field.position.height || 30

      if (mouseX >= posX && mouseX <= posX + width &&
          mouseY >= posY && mouseY <= posY + height) {
        return field
      }
    }
    return null
  }

  function handleCanvasClick(e: MouseEvent) {
    const { x, y } = canvasPoint(e)

    const field = getFieldAtPosition(x, y)

    if (field) {
      selectedField.value = field
      selectedFieldId.value = field.id
      drawCanvas()
    } else {
      selectedField.value = null
      selectedFieldId.value = null
      drawCanvas()
    }
  }

  function handleMouseMove(e: MouseEvent) {
    const { x, y } = canvasPoint(e)

    const field = getFieldAtPosition(x, y)

    if (field && field.id !== hoverFieldId.value) {
      hoverFieldId.value = field ? field.id : null
      labelCanvas.value!.style.cursor = field ? 'pointer' : 'default'
      drawCanvas()
    }

    if (isDragging.value && selectedField.value) {
      const newX = Math.max(0, Math.round(x - dragOffset.value.x))
      const newY = Math.max(0, Math.round(y - dragOffset.value.y))

      selectedField.value.position.left = newX
      selectedField.value.position.top = newY

      drawCanvas()
    }
  }

  function handleMouseDown(e: MouseEvent) {
    const { x, y } = canvasPoint(e)

    const field = getFieldAtPosition(x, y)

    if (field) {
      selectedField.value = field
      selectedFieldId.value = field.id
      dragOffset.value.x = x - (field.position.left || 0)
      dragOffset.value.y = y - (field.position.top || 0)
      isDragging.value = true
      drawCanvas()
    }
  }

  function handleMouseUp() {
    if (isDragging.value) {
      isDragging.value = false
      onFieldChange()
    }
  }

  function handleMouseLeave() {
    hoverFieldId.value = null
    isDragging.value = false
    drawCanvas()
  }

  function onFieldChange() {
    drawCanvas()
  }

  function selectField(field: LeField) {
    selectedField.value = field
    selectedFieldId.value = field.id
    drawCanvas()
  }

  function addField() {
    const newId = Math.max(0, ...fields.value.map((f) => typeof f.id === 'number' ? f.id : 0)) + 1
    fields.value.push({
      id: newId,
      label: '新字段',
      value: '',
      type: 'dynamic',
      position: { left: 50, top: 50 + newId * 40, width: 150, height: 30 }
    })
    drawCanvas()
  }

  function deleteField(index: number) {
    const field = fields.value[index]
    if (field.id === selectedFieldId.value) {
      selectedField.value = null
      selectedFieldId.value = null
    }
    fields.value.splice(index, 1)
    drawCanvas()
  }

  return {
    isDragging,
    dragOffset,
    getFieldAtPosition,
    handleCanvasClick,
    handleMouseMove,
    handleMouseDown,
    handleMouseUp,
    handleMouseLeave,
    onFieldChange,
    selectField,
    addField,
    deleteField,
  }
}
