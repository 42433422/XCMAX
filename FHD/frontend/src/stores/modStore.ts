import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import * as modStoreApi from '@/api/modStore';
import type { ModInfo, ModCatalog, ModDetails } from '@/api/modStore';

export const useModStoreStore = defineStore('modStore', () => {
  const modCatalog = ref<ModCatalog | null>(null);
  const selectedMod = ref<ModInfo | null>(null);
  const modDetails = ref<ModDetails | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const installedMods = computed(() => {
    return modCatalog.value?.installed || [];
  });

  const availableMods = computed(() => {
    return modCatalog.value?.available || [];
  });

  const allMods = computed(() => {
    const installed = installedMods.value;
    const available = availableMods.value;
    
    const modMap = new Map<string, ModInfo>();
    
    available.forEach(mod => {
      modMap.set(mod.id, { ...mod });
    });
    
    installed.forEach(mod => {
      const existing = modMap.get(mod.id);
      if (existing) {
        existing.is_installed = true;
      } else {
        modMap.set(mod.id, { ...mod, is_installed: true });
      }
    });
    
    return Array.from(modMap.values());
  });

  const installedCount = computed(() => {
    return installedMods.value.length;
  });

  const availableCount = computed(() => {
    return availableMods.value.length;
  });

  async function loadCatalog() {
    loading.value = true;
    error.value = null;
    
    try {
      modCatalog.value = await modStoreApi.getModCatalog();
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载 MOD 目录失败';
      console.error('Failed to load mod catalog:', err);
    } finally {
      loading.value = false;
    }
  }

  async function loadModDetails(modId: string) {
    loading.value = true;
    error.value = null;
    
    try {
      modDetails.value = await modStoreApi.getModDetails(modId);
      return modDetails.value;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载 MOD 详情失败';
      console.error('Failed to load mod details:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function installModAction(packageFile: string) {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await modStoreApi.installMod(packageFile);
      await loadCatalog();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '安装失败';
      console.error('Failed to install mod:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function uninstallModAction(modId: string) {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await modStoreApi.uninstallMod(modId);
      await loadCatalog();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '卸载失败';
      console.error('Failed to uninstall mod:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function updateModAction(modId: string, packageFile: string) {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await modStoreApi.updateMod(modId, packageFile);
      await loadCatalog();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '更新失败';
      console.error('Failed to update mod:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function uploadModAction(file: File, activate: boolean = false) {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await modStoreApi.uploadModPackage(file, activate);
      await loadCatalog();
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '上传失败';
      console.error('Failed to upload mod:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function searchModsAction(
    query?: string,
    author?: string,
    installed?: boolean
  ) {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await modStoreApi.searchMods(query, author, installed);
      modCatalog.value = {
        installed: [],
        available: result.data,
        indexed_count: result.count,
      };
      return result;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '搜索失败';
      console.error('Failed to search mods:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function getPopularModsAction(limit: number = 10) {
    loading.value = true;
    error.value = null;
    
    try {
      const mods = await modStoreApi.getPopularMods(limit);
      modCatalog.value = {
        installed: [],
        available: mods,
        indexed_count: mods.length,
      };
      return mods;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '获取热门 MOD 失败';
      console.error('Failed to get popular mods:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function getRecentModsAction(limit: number = 10) {
    loading.value = true;
    error.value = null;
    
    try {
      const mods = await modStoreApi.getRecentMods(limit);
      modCatalog.value = {
        installed: [],
        available: mods,
        indexed_count: mods.length,
      };
      return mods;
    } catch (err) {
      error.value = err instanceof Error ? err.message : '获取最新 MOD 失败';
      console.error('Failed to get recent mods:', err);
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function checkUpdatesAction() {
    try {
      return await modStoreApi.checkUpdates();
    } catch (err) {
      console.error('Failed to check updates:', err);
      throw err;
    }
  }

  async function rateModAction(
    modId: string,
    rating: number,
    comment: string = '',
    userId: string = ''
  ) {
    try {
      const result = await modStoreApi.rateMod(modId, rating, comment, userId);
      await loadModDetails(modId);
      return result;
    } catch (err) {
      console.error('Failed to rate mod:', err);
      throw err;
    }
  }

  function clearError() {
    error.value = null;
  }

  function reset() {
    modCatalog.value = null;
    selectedMod.value = null;
    modDetails.value = null;
    loading.value = false;
    error.value = null;
  }

  return {
    modCatalog,
    selectedMod,
    modDetails,
    loading,
    error,
    installedMods,
    availableMods,
    allMods,
    installedCount,
    availableCount,
    loadCatalog,
    loadModDetails,
    installModAction,
    uninstallModAction,
    updateModAction,
    uploadModAction,
    searchModsAction,
    getPopularModsAction,
    getRecentModsAction,
    checkUpdatesAction,
    rateModAction,
    clearError,
    reset,
  };
});
