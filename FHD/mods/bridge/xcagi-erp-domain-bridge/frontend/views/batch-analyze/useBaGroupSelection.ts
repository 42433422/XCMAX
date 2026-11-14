import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useBatchAnalyzeStore, type SheetGroup } from '@/stores/batchAnalyze'
import { useBatchAnalyze } from '@/composables/useBatchAnalyze'
import { appPrompt } from '@/utils/appDialog'

// 拆分自 BatchAnalyzeView.vue script（原第 531–532、893–966 行）；逻辑逐字迁移，行为不变。
export function useBaGroupSelection() {
  const store = useBatchAnalyzeStore()
  const { groups } = storeToRefs(store)

  const selectedGroupIds = ref<string[]>([])
  const selectAllGroups = ref(false)

  function toggleGroupSelect(groupId: string) {
    const idx = selectedGroupIds.value.indexOf(groupId)
    if (idx === -1) {
      selectedGroupIds.value.push(groupId)
    } else {
      selectedGroupIds.value.splice(idx, 1)
    }
    selectAllGroups.value = selectedGroupIds.value.length === groups.value.length
  }

  function toggleSelectAll() {
    if (selectAllGroups.value) {
      selectedGroupIds.value = groups.value.map(g => g.id)
    } else {
      selectedGroupIds.value = []
    }
  }

  async function mergeSelectedGroups() {
    if (selectedGroupIds.value.length < 2) return

    const groupsToMerge = groups.value.filter(g => selectedGroupIds.value.includes(g.id))
    if (groupsToMerge.length < 2) return

    const newName = await appPrompt('请输入合并后的分组名称：', `合并分组_${groupsToMerge.length}`, { title: '合并分组' })
    if (newName === null || !String(newName).trim()) return

    const allSheets: any[] = []
    for (const g of groupsToMerge) {
      allSheets.push(...g.matchedSheets)
    }

    const allFields = new Set<string>()
    for (const sheet of allSheets) {
      sheet.fields.forEach((f: string) => allFields.add(f))
    }

    const commonFields: string[] = []
    const differenceFields: string[] = []

    for (const field of allFields) {
      const appearsInAll = allSheets.every((sheet: any) =>
        sheet.fields.includes(field)
      )
      if (appearsInAll) {
        commonFields.push(field)
      } else {
        differenceFields.push(field)
      }
    }

    const { inferTemplateTypeByFields } = useBatchAnalyze()
    const { templateType, scopeKey, matchScore } = inferTemplateTypeByFields(Array.from(allFields))

    const mergedGroup: SheetGroup = {
      id: `group_${Date.now()}`,
      name: String(newName).trim(),
      category: scopeKey,
      matchedSheets: allSheets,
      commonFields,
      differenceFields,
      recommendedTemplateId: '',
      recommendedTemplateName: '',
      matchScore: Math.round(matchScore * 100),
      templateType
    }

    const updatedGroups = groups.value.filter(g => !selectedGroupIds.value.includes(g.id))
    updatedGroups.push(mergedGroup)

    store.setGroups(updatedGroups)
    selectedGroupIds.value = []
    selectAllGroups.value = false
  }

  return {
    selectedGroupIds,
    selectAllGroups,
    toggleGroupSelect,
    toggleSelectAll,
    mergeSelectedGroups,
  }
}
