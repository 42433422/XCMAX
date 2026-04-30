<template>
  <div class="mod-store">
    <section class="modstore-primary">
      <h1 class="store-title">
        <i class="fa fa-puzzle-piece"></i>
        MOD 扩展
      </h1>
      <p class="lead">
        制作、校验 manifest、与运行时 <code>mods</code> 目录推送/拉回，请以独立
        <strong>MODstore</strong> 为准（当前：
        <span class="mono">{{ modstoreWebUrl }}</span>，可在环境变量
        <code>VITE_MODSTORE_WEB_URL</code> 中修改）。
      </p>
      <div class="panel-tabs panel-tabs-main">
        <button
          type="button"
          :class="['tab', { active: activePanel === 'modstore' }]"
          @click="activePanel = 'modstore'"
        >
          MODstore（推荐）
        </button>
        <button
          type="button"
          :class="['tab', { active: activePanel === 'legacy' }]"
          @click="activateLegacy"
        >
          本机 .xcmod 简易目录
        </button>
      </div>
    </section>

    <div v-show="activePanel === 'modstore'" class="modstore-frame-wrap">
      <div class="frame-toolbar">
        <a
          :href="modstoreWebUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="btn btn-primary"
        >
          <i class="fa fa-external-link"></i>
          新窗口打开 MODstore
        </a>
      </div>
      <iframe :src="modstoreWebUrl" class="modstore-iframe" title="MODstore" />
    </div>

    <div v-show="activePanel === 'legacy'" class="legacy-store">
    <!-- 顶部导航与搜索 -->
    <div class="store-header">
      <h2 class="legacy-heading">
        <i class="fa fa-shopping-cart"></i>
        本机简易 MOD 目录（XCAGI /api/mod-store）
      </h2>
      
      <div class="search-bar">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索 MOD..."
          class="search-input"
          @keyup.enter="searchMods"
        />
        <button class="search-btn" @click="searchMods">
          <i class="fa fa-search"></i>
          搜索
        </button>
      </div>
      
      <div class="filter-bar">
        <label class="filter-label">
          <input type="checkbox" v-model="filterInstalled" @change="applyFilters" />
          仅显示已安装
        </label>
        
        <select v-model="sortBy" @change="applyFilters" class="sort-select">
          <option value="name">按名称</option>
          <option value="downloads">按下载量</option>
          <option value="rating">按评分</option>
          <option value="created_at">最新上架</option>
        </select>
      </div>
    </div>

    <!-- 标签页切换 -->
    <div class="tabs">
      <button
        :class="['tab', { active: currentTab === 'all' }]"
        @click="switchTab('all')"
      >
        全部 MOD
      </button>
      <button
        :class="['tab', { active: currentTab === 'popular' }]"
        @click="switchTab('popular')"
      >
        <i class="fa fa-fire"></i>
        热门
      </button>
      <button
        :class="['tab', { active: currentTab === 'recent' }]"
        @click="switchTab('recent')"
      >
        <i class="fa fa-clock-o"></i>
        最新
      </button>
      <button
        :class="['tab', { active: currentTab === 'installed' }]"
        @click="switchTab('installed')"
      >
        <i class="fa fa-check-circle"></i>
        已安装
      </button>
    </div>

    <!-- MOD 列表 -->
    <div class="mod-grid" v-if="filteredMods.length > 0">
      <div
        v-for="mod in filteredMods"
        :key="mod.id"
        class="mod-card"
        :class="{ installed: mod.is_installed }"
      >
        <div class="mod-card-header">
          <div class="mod-icon">
            <i :class="mod.icon || 'fa fa-puzzle-piece'"></i>
          </div>
          <div class="mod-basic">
            <h3 class="mod-name">{{ mod.name }}</h3>
            <p class="mod-author">by {{ mod.author || 'Unknown' }}</p>
          </div>
          <div class="mod-version">
            v{{ mod.version }}
          </div>
        </div>

        <p class="mod-description">{{ mod.description || '暂无描述' }}</p>

        <div class="mod-stats">
          <span class="stat" v-if="mod.download_count || mod.total_downloads">
            <i class="fa fa-download"></i>
            {{ mod.download_count || mod.total_downloads || 0 }}
          </span>
          <span class="stat" v-if="mod.avg_rating || mod.rating_count">
            <i class="fa fa-star"></i>
            {{ (mod.avg_rating || 0).toFixed(1) }}
            ({{ mod.rating_count || 0 }})
          </span>
        </div>

        <div class="mod-actions">
          <button
            v-if="!mod.is_installed"
            class="btn btn-primary"
            @click="installMod(mod)"
            :disabled="mod.installationInProgress"
          >
            <i class="fa fa-download"></i>
            {{ mod.installationInProgress ? '安装中...' : '安装' }}
          </button>
          
          <button
            v-else
            class="btn btn-secondary"
            @click="uninstallMod(mod)"
            :disabled="mod.uninstallationInProgress"
          >
            <i class="fa fa-trash"></i>
            {{ mod.uninstallationInProgress ? '卸载中...' : '卸载' }}
          </button>

          <button
            class="btn btn-info"
            @click="viewDetails(mod)"
          >
            <i class="fa fa-info-circle"></i>
            详情
          </button>

          <button
            v-if="hasUpdate(mod)"
            class="btn btn-warning"
            @click="updateMod(mod)"
            :disabled="mod.updateInProgress"
          >
            <i class="fa fa-refresh"></i>
            {{ mod.updateInProgress ? '更新中...' : '更新' }}
          </button>
        </div>

        <div class="mod-tags" v-if="mod.dependencies && Object.keys(mod.dependencies).length > 0">
          <span class="tag">
            <i class="fa fa-plug"></i>
            {{ Object.keys(mod.dependencies).length }} 依赖
          </span>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <i class="fa fa-inbox"></i>
      <p>暂无 MOD</p>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-overlay">
      <i class="fa fa-spinner fa-spin"></i>
      <p>加载中...</p>
    </div>

    <!-- MOD 详情对话框 -->
    <Modal
      v-if="selectedMod"
      :title="selectedMod.name"
      @close="selectedMod = null"
    >
      <ModDetails :mod="selectedMod" @install="installMod" @uninstall="uninstallMod" />
    </Modal>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue';
import { apiFetch } from '@/utils/apiBase';
import Modal from '@/components/Modal.vue';
import ModDetails from './ModDetails.vue';
import { appAlert, appConfirm } from '@/utils/appDialog';

export default {
  name: 'ModStore',
  components: {
    Modal,
    ModDetails,
  },
  setup() {
    const modstoreWebUrl = String(
      import.meta.env.VITE_MODSTORE_WEB_URL || 'http://127.0.0.1:5174',
    ).replace(/\/$/, '');
    const activePanel = ref('modstore');
    const legacyPrimed = ref(false);

    const allMods = ref([]);
    const filteredMods = ref([]);
    const searchQuery = ref('');
    const filterInstalled = ref(false);
    const sortBy = ref('name');
    const currentTab = ref('all');
    const loading = ref(false);
    const selectedMod = ref(null);

    function activateLegacy() {
      activePanel.value = 'legacy';
      if (!legacyPrimed.value) {
        legacyPrimed.value = true;
        loadMods();
      }
    }

    const loadMods = async () => {
      loading.value = true;
      try {
        const response = await apiFetch('/api/mod-store/catalog');
        const data = await response.json();
        
        if (data.success) {
          allMods.value = data.data.available || [];
          applyFilters();
        }
      } catch (error) {
        console.error('Failed to load mods:', error);
      } finally {
        loading.value = false;
      }
    };

    const searchMods = async () => {
      if (!searchQuery.value.trim()) {
        loadMods();
        return;
      }

      loading.value = true;
      try {
        const params = new URLSearchParams({
          q: searchQuery.value,
          installed: filterInstalled.value,
          limit: 50,
        });

        const response = await apiFetch(`/api/mod-store/search?${params}`);
        const data = await response.json();

        if (data.success) {
          allMods.value = data.data || [];
          applyFilters();
        }
      } catch (error) {
        console.error('Search failed:', error);
      } finally {
        loading.value = false;
      }
    };

    const applyFilters = () => {
      let mods = [...allMods.value];

      if (filterInstalled.value) {
        mods = mods.filter(mod => mod.is_installed);
      }

      if (sortBy.value === 'downloads') {
        mods.sort((a, b) => (b.total_downloads || b.download_count || 0) - (a.total_downloads || a.download_count || 0));
      } else if (sortBy.value === 'rating') {
        mods.sort((a, b) => (b.avg_rating || 0) - (a.avg_rating || 0));
      } else if (sortBy.value === 'created_at') {
        mods.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      } else {
        mods.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      }

      filteredMods.value = mods;
    };

    const switchTab = async (tab) => {
      currentTab.value = tab;
      loading.value = true;

      try {
        if (tab === 'popular') {
          const response = await apiFetch('/api/mod-store/popular?limit=50');
          const data = await response.json();
          if (data.success) {
            allMods.value = data.data || [];
            applyFilters();
          }
        } else if (tab === 'recent') {
          const response = await apiFetch('/api/mod-store/recent?limit=50');
          const data = await response.json();
          if (data.success) {
            allMods.value = data.data || [];
            applyFilters();
          }
        } else if (tab === 'installed') {
          filterInstalled.value = true;
          applyFilters();
        } else {
          await loadMods();
        }
      } catch (error) {
        console.error('Failed to switch tab:', error);
      } finally {
        loading.value = false;
      }
    };

    const installMod = async (mod) => {
      mod.installationInProgress = true;
      try {
        const formData = new FormData();
        formData.append('package_file', mod.package_file);
        formData.append('activate', 'true');
        formData.append('verify_signature', 'true');

        const response = await apiFetch('/api/mod-store/install', {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (data.success) {
          mod.is_installed = true;
          await appAlert(`MOD ${mod.name} 安装成功！`);
          loadMods();
        } else {
          await appAlert(`安装失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Installation failed:', error);
        await appAlert('安装失败，请重试');
      } finally {
        mod.installationInProgress = false;
      }
    };

    const uninstallMod = async (mod) => {
      if (!(await appConfirm(`确定要卸载 MOD "${mod.name}" 吗？`, { danger: true }))) {
        return;
      }

      mod.uninstallationInProgress = true;
      try {
        const formData = new FormData();
        formData.append('mod_id', mod.id);
        formData.append('remove_files', 'true');

        const response = await apiFetch('/api/mod-store/uninstall', {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (data.success) {
          mod.is_installed = false;
          await appAlert(`MOD ${mod.name} 卸载成功！`);
          loadMods();
        } else {
          await appAlert(`卸载失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Uninstallation failed:', error);
        await appAlert('卸载失败，请重试');
      } finally {
        mod.uninstallationInProgress = false;
      }
    };

    const updateMod = async (mod) => {
      mod.updateInProgress = true;
      try {
        const formData = new FormData();
        formData.append('mod_id', mod.id);
        formData.append('package_file', mod.package_file);
        formData.append('verify_signature', 'true');

        const response = await apiFetch('/api/mod-store/update', {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (data.success) {
          mod.version = data.data.version;
          await appAlert(`MOD ${mod.name} 更新成功！`);
          loadMods();
        } else {
          await appAlert(`更新失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Update failed:', error);
        await appAlert('更新失败，请重试');
      } finally {
        mod.updateInProgress = false;
      }
    };

    const hasUpdate = (mod) => {
      return mod.is_installed && mod.new_version && mod.new_version !== mod.version;
    };

    const viewDetails = (mod) => {
      selectedMod.value = mod;
    };

    return {
      modstoreWebUrl,
      activePanel,
      activateLegacy,
      allMods,
      filteredMods,
      searchQuery,
      filterInstalled,
      sortBy,
      currentTab,
      loading,
      selectedMod,
      searchMods,
      applyFilters,
      switchTab,
      installMod,
      uninstallMod,
      updateMod,
      hasUpdate,
      viewDetails,
    };
  },
};
</script>

<style scoped>
.mod-store {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.modstore-primary {
  margin-bottom: 16px;
}

.lead {
  color: #555;
  line-height: 1.6;
  margin: 0 0 12px;
  font-size: 14px;
}

.lead .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  color: #2c3e50;
}

.panel-tabs-main {
  margin-bottom: 12px;
}

.modstore-frame-wrap {
  margin-bottom: 24px;
}

.frame-toolbar {
  margin-bottom: 8px;
}

.modstore-iframe {
  width: 100%;
  min-height: calc(100vh - 220px);
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #fff;
}

.legacy-store {
  padding-top: 8px;
  border-top: 1px dashed #e0e0e0;
}

.legacy-heading {
  font-size: 22px;
  color: #2c3e50;
  margin: 16px 0 20px;
}

.store-header {
  margin-bottom: 30px;
}

.store-title {
  font-size: 28px;
  color: #2c3e50;
  margin-bottom: 20px;
}

.store-title i {
  color: #3498db;
  margin-right: 10px;
}

.search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 15px;
}

.search-input {
  flex: 1;
  padding: 10px 15px;
  border: 2px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.search-input:focus {
  outline: none;
  border-color: #3498db;
}

.search-btn {
  padding: 10px 20px;
  background: #3498db;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.search-btn:hover {
  background: #2980b9;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 20px;
}

.filter-label {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}

.sort-select {
  padding: 8px 12px;
  border: 2px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.tabs {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  border-bottom: 2px solid #eee;
  padding-bottom: 10px;
}

.tab {
  padding: 8px 16px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  transition: all 0.3s;
}

.tab:hover {
  background: #f5f5f5;
}

.tab.active {
  background: #3498db;
  color: white;
}

.tab i {
  margin-right: 5px;
}

.mod-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
}

.mod-card {
  background: white;
  border: 2px solid #eee;
  border-radius: 8px;
  padding: 20px;
  transition: all 0.3s;
  position: relative;
}

.mod-card:hover {
  border-color: #3498db;
  box-shadow: 0 4px 12px rgba(52, 152, 219, 0.2);
  transform: translateY(-2px);
}

.mod-card.installed {
  border-color: #27ae60;
  background: #f0fff4;
}

.mod-card-header {
  display: flex;
  align-items: flex-start;
  gap: 15px;
  margin-bottom: 15px;
}

.mod-icon {
  width: 50px;
  height: 50px;
  background: #3498db;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 24px;
}

.mod-name {
  font-size: 18px;
  color: #2c3e50;
  margin: 0 0 5px 0;
}

.mod-author {
  font-size: 13px;
  color: #7f8c8d;
  margin: 0;
}

.mod-version {
  position: absolute;
  top: 20px;
  right: 20px;
  font-size: 12px;
  color: #95a5a6;
  background: #f5f5f5;
  padding: 4px 8px;
  border-radius: 4px;
}

.mod-description {
  font-size: 14px;
  color: #666;
  margin-bottom: 15px;
  line-height: 1.6;
  min-height: 60px;
}

.mod-stats {
  display: flex;
  gap: 15px;
  margin-bottom: 15px;
}

.stat {
  font-size: 13px;
  color: #7f8c8d;
  display: flex;
  align-items: center;
  gap: 5px;
}

.stat i {
  color: #f39c12;
}

.mod-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 5px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: #3498db;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #2980b9;
}

.btn-secondary {
  background: #e74c3c;
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background: #c0392b;
}

.btn-info {
  background: #95a5a6;
  color: white;
}

.btn-info:hover:not(:disabled) {
  background: #7f8c8d;
}

.btn-warning {
  background: #f39c12;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #e67e22;
}

.mod-tags {
  margin-top: 15px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tag {
  font-size: 12px;
  color: #7f8c8d;
  background: #f5f5f5;
  padding: 4px 8px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #95a5a6;
}

.empty-state i {
  font-size: 48px;
  margin-bottom: 15px;
}

.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
  z-index: 1000;
}

.loading-overlay i {
  font-size: 48px;
  margin-bottom: 15px;
}
</style>
