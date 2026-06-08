import { ref } from 'vue'

export function useWechatGroupBridge() {
  const feed = ref<unknown[]>([])
  const loading = ref(false)
  const syncing = ref(false)

  async function loadFeed(_marketUserId?: number, _limit?: number, _opts?: { sync?: boolean }) {
    loading.value = false
  }

  async function syncGroups() {
    syncing.value = false
  }

  function formatFeedItem(item: unknown) {
    return item
  }

  return {
    feed,
    loading,
    syncing,
    loadFeed,
    syncGroups,
    formatFeedItem,
  }
}
