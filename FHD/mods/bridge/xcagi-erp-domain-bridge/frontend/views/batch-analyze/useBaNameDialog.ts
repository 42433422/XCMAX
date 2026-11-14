import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useBatchAnalyzeStore, type SheetGroup } from '@/stores/batchAnalyze'

// 拆分自 BatchAnalyzeView.vue script（原第 509–515、968–991 行）；逻辑逐字迁移，行为不变。
export function useBaNameDialog() {
  const store = useBatchAnalyzeStore()
  const { groups } = storeToRefs(store)

  const showNameInputDialog = ref(false)
  const nameInputDialogConfig = ref({
    title: '重命名分组',
    message: '请输入新的分组名称：',
    placeholder: '分组名称'
  })
  const nameInputTargetGroup = ref<SheetGroup | null>(null)

  function editGroupName(group: SheetGroup) {
    nameInputTargetGroup.value = group
    nameInputDialogConfig.value = {
      title: '重命名分组',
      message: '请输入新的分组名称：',
      placeholder: '分组名称'
    }
    showNameInputDialog.value = true
  }

  function handleNameInputConfirm(newName: string) {
    if (!newName || !nameInputTargetGroup.value) return
    if (newName === nameInputTargetGroup.value.name) return

    const updatedGroups = groups.value.map(g => {
      if (g.id === nameInputTargetGroup.value!.id) {
        return { ...g, name: newName }
      }
      return g
    })

    store.setGroups(updatedGroups)
    nameInputTargetGroup.value = null
  }

  return {
    showNameInputDialog,
    nameInputDialogConfig,
    editGroupName,
    handleNameInputConfirm,
  }
}
