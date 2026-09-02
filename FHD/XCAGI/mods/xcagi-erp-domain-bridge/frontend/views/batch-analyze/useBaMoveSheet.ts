import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useBatchAnalyzeStore, type SheetGroup } from '@/stores/batchAnalyze'
import { appPrompt } from '@/utils/appDialog'

// 拆分自 BatchAnalyzeView.vue script（原第 526–537、793–891 行）；逻辑逐字迁移，行为不变。
export function useBaMoveSheet() {
  const store = useBatchAnalyzeStore()
  const { groups } = storeToRefs(store)

  const showMoveModal = ref(false)
  const moveSourceSheet = ref<any>(null)
  const moveSourceGroup = ref<any>(null)
  const moveSourceIndex = ref(-1)

  const moveTargetGroups = computed(() => {
    if (!moveSourceGroup.value) return groups.value
    return groups.value.filter(g => g.id !== moveSourceGroup.value.id)
  })

  function showMoveSheetDialog(group: SheetGroup, sheet: any, index: number) {
    moveSourceGroup.value = group
    moveSourceSheet.value = sheet
    moveSourceIndex.value = index
    showMoveModal.value = true
  }

  function closeMoveModal() {
    showMoveModal.value = false
    moveSourceSheet.value = null
    moveSourceGroup.value = null
    moveSourceIndex.value = -1
  }

  function moveSheetToGroup(targetGroupId: string) {
    if (!moveSourceSheet.value || !moveSourceGroup.value) return

    const sourceGroupIndex = groups.value.findIndex(g => g.id === moveSourceGroup.value.id)
    const targetGroupIndex = groups.value.findIndex(g => g.id === targetGroupId)
    if (sourceGroupIndex === -1 || targetGroupIndex === -1) return

    const sheet = moveSourceSheet.value
    const updatedGroups = [...groups.value]

    updatedGroups[sourceGroupIndex] = recalculateGroupFields({
      ...updatedGroups[sourceGroupIndex],
      matchedSheets: updatedGroups[sourceGroupIndex].matchedSheets.filter((_: any, i: number) => i !== moveSourceIndex.value)
    })

    updatedGroups[targetGroupIndex] = recalculateGroupFields({
      ...updatedGroups[targetGroupIndex],
      matchedSheets: [...updatedGroups[targetGroupIndex].matchedSheets, sheet]
    })

    store.setGroups(updatedGroups)
    closeMoveModal()
  }

  async function createNewGroupAndMove() {
    if (!moveSourceSheet.value) return

    const newGroupName = await appPrompt('请输入新分组名称：', '', { title: '新分组' })
    if (newGroupName === null || !String(newGroupName).trim()) return

    const sourceGroupIndex = groups.value.findIndex(g => g.id === moveSourceGroup.value?.id)

    const newGroup: SheetGroup = {
      id: `group_${Date.now()}`,
      name: String(newGroupName).trim(),
      category: '',
      matchedSheets: [moveSourceSheet.value],
      commonFields: moveSourceSheet.value.fields,
      differenceFields: [],
      recommendedTemplateId: '',
      recommendedTemplateName: '',
      matchScore: 100,
      templateType: '通用'
    }

    const updatedGroups = [...groups.value]

    if (sourceGroupIndex !== -1) {
      updatedGroups[sourceGroupIndex] = recalculateGroupFields({
        ...updatedGroups[sourceGroupIndex],
        matchedSheets: updatedGroups[sourceGroupIndex].matchedSheets.filter((_: any, i: number) => i !== moveSourceIndex.value)
      })
    }

    updatedGroups.push(newGroup)
    store.setGroups(updatedGroups)
    closeMoveModal()
  }

  function recalculateGroupFields(group: SheetGroup): SheetGroup {
    if (group.matchedSheets.length === 0) {
      return { ...group, commonFields: [], differenceFields: [] }
    }

    const allFields = new Set<string>()
    for (const sheet of group.matchedSheets) {
      sheet.fields.forEach((f: string) => allFields.add(f))
    }

    const commonFields: string[] = []
    const differenceFields: string[] = []

    for (const field of allFields) {
      const appearsInAll = group.matchedSheets.every((sheet: any) =>
        sheet.fields.includes(field)
      )
      if (appearsInAll) {
        commonFields.push(field)
      } else {
        differenceFields.push(field)
      }
    }

    return { ...group, commonFields, differenceFields }
  }

  return {
    showMoveModal,
    moveSourceSheet,
    moveSourceGroup,
    moveTargetGroups,
    showMoveSheetDialog,
    closeMoveModal,
    moveSheetToGroup,
    createNewGroupAndMove,
    recalculateGroupFields,
  }
}
