<template>
  <div class="mod-details">
    <div class="mod-header">
      <div class="mod-icon-large">
        <i :class="mod.icon || 'fa fa-puzzle-piece'"></i>
      </div>
      <div class="mod-info">
        <h2 class="mod-title">{{ mod.name }}</h2>
        <p class="mod-author">by {{ mod.author || 'Unknown' }}</p>
        <div class="mod-meta">
          <span class="version">v{{ mod.version }}</span>
          <span class="badge" v-if="mod.is_installed">已安装</span>
        </div>
      </div>
    </div>

    <div class="mod-content">
      <div class="mod-section">
        <h3><i class="fa fa-file-text-o"></i> 描述</h3>
        <p class="description">{{ mod.description || '暂无描述' }}</p>
      </div>

      <div class="mod-section" v-if="mod.dependencies && Object.keys(mod.dependencies).length > 0">
        <h3><i class="fa fa-plug"></i> 依赖关系</h3>
        <div class="dependencies-list">
          <div
            v-for="(version, depId) in mod.dependencies"
            :key="depId"
            class="dependency-item"
            :class="{ satisfied: isDependencySatisfied(depId) }"
          >
            <i :class="isDependencySatisfied(depId) ? 'fa fa-check-circle' : 'fa fa-exclamation-circle'"></i>
            <span class="dep-name">{{ depId }}</span>
            <span class="dep-version">{{ version }}</span>
          </div>
        </div>
      </div>

      <div class="mod-section details-state" v-if="detailsLoading">
        <i class="fa fa-spinner fa-spin"></i> 加载中…
      </div>

      <div class="mod-section details-state details-error" v-else-if="detailsError">
        <i class="fa fa-exclamation-triangle"></i> {{ detailsError }}
        <button type="button" class="btn btn-primary btn-retry" @click="loadDetails">
          <i class="fa fa-refresh"></i> 重试
        </button>
      </div>

      <div class="mod-section" v-if="!detailsLoading && !detailsError && statistics">
        <h3><i class="fa fa-bar-chart"></i> 统计信息</h3>
        <div class="stats-grid">
          <div class="stat-item">
            <i class="fa fa-download"></i>
            <span class="stat-value">{{ statistics.total_downloads || 0 }}</span>
            <span class="stat-label">下载量</span>
          </div>
          <div class="stat-item">
            <i class="fa fa-star"></i>
            <span class="stat-value">{{ (statistics.avg_rating || 0).toFixed(1) }}</span>
            <span class="stat-label">平均评分</span>
          </div>
          <div class="stat-item">
            <i class="fa fa-users"></i>
            <span class="stat-value">{{ statistics.rating_count || 0 }}</span>
            <span class="stat-label">评分数</span>
          </div>
          <div class="stat-item">
            <i class="fa fa-refresh"></i>
            <span class="stat-value">{{ statistics.total_updates || 0 }}</span>
            <span class="stat-label">更新次数</span>
          </div>
        </div>
      </div>

      <div class="mod-section" v-if="!detailsLoading && !detailsError && ratings && ratings.length > 0">
        <h3><i class="fa fa-comments"></i> 用户评价 ({{ ratings.length }})</h3>
        <div class="ratings-list">
          <div v-for="rating in ratings" :key="rating.id" class="rating-item">
            <div class="rating-header">
              <div class="rating-stars">
                <i
                  v-for="n in 5"
                  :key="n"
                  :class="['fa', n <= rating.rating ? 'fa-star' : 'fa-star-o']"
                ></i>
              </div>
              <span class="rating-date">{{ formatDate(rating.created_at) }}</span>
            </div>
            <p class="rating-comment" v-if="rating.comment">{{ rating.comment }}</p>
            <p class="rating-user">
              <i class="fa fa-user"></i>
              {{ rating.user_id || '匿名用户' }}
            </p>
          </div>
        </div>
      </div>

      <div class="mod-section" v-if="!detailsLoading && !detailsError && (!ratings || ratings.length === 0)">
        <h3><i class="fa fa-comments"></i> 用户评价</h3>
        <p class="no-ratings">暂无评价，快来抢沙发吧！</p>
      </div>
    </div>

    <div class="mod-footer">
      <div class="rating-form" v-if="!mod.is_installed">
        <h4>评价此 MOD</h4>
        <div class="star-rating">
          <i
            v-for="n in 5"
            :key="n"
            :class="['fa', n <= userRating ? 'fa-star' : 'fa-star-o']"
            @click="userRating = n"
          ></i>
        </div>
        <textarea
          v-model="userComment"
          placeholder="写下您的评价..."
          rows="3"
          class="comment-input"
        ></textarea>
        <button class="btn btn-primary" @click="submitRating" :disabled="userRating === 0">
          提交评价
        </button>
      </div>

      <div class="action-buttons">
        <button
          v-if="!mod.is_installed"
          class="btn btn-lg btn-primary"
          @click="$emit('install', mod)"
          :disabled="mod.installationInProgress"
        >
          <i class="fa fa-download"></i>
          {{ mod.installationInProgress ? '安装中...' : '安装 MOD' }}
        </button>
        
        <button
          v-else
          class="btn btn-lg btn-secondary"
          @click="$emit('uninstall', mod)"
          :disabled="mod.uninstallationInProgress"
        >
          <i class="fa fa-trash"></i>
          {{ mod.uninstallationInProgress ? '卸载中...' : '卸载 MOD' }}
        </button>

        <button
          v-if="hasUpdate"
          class="btn btn-lg btn-warning"
          @click="$emit('update', mod)"
          :disabled="mod.updateInProgress"
        >
          <i class="fa fa-refresh"></i>
          {{ mod.updateInProgress ? '更新中...' : '更新 MOD' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue';
import { apiFetch } from '@/utils/apiBase';
import { appAlert } from '@/utils/appDialog';

export default {
  name: 'ModDetails',
  props: {
    mod: {
      type: Object,
      required: true,
    },
  },
  emits: ['install', 'uninstall', 'update'],
  setup(props) {
    const userRating = ref(0);
    const userComment = ref('');
    const statistics = ref(null);
    const ratings = ref([]);
    const detailsLoading = ref(false);
    const detailsError = ref('');

    const isDependencySatisfied = (depId) => {
      if (depId === 'xcagi') return true;
      return true;
    };

    const hasUpdate = computed(() => {
      return props.mod.is_installed && 
             props.mod.new_version && 
             props.mod.new_version !== props.mod.version;
    });

    const formatDate = (dateStr) => {
      if (!dateStr) return '';
      const date = new Date(dateStr);
      return date.toLocaleDateString('zh-CN');
    };

    const submitRating = async () => {
      if (userRating.value === 0) {
        await appAlert('请选择评分');
        return;
      }

      try {
        const formData = new FormData();
        formData.append('rating', userRating.value);
        formData.append('comment', userComment.value);
        formData.append('user_id', 'current_user');

        const response = await apiFetch(`/api/mod-store/mod/${props.mod.id}/rate`, {
          method: 'POST',
          body: formData,
        });

        const data = await response.json();

        if (data.success) {
          await appAlert('评价成功！');
          userRating.value = 0;
          userComment.value = '';
          loadDetails();
        } else {
          await appAlert(`评价失败：${data.error || data.detail}`);
        }
      } catch (error) {
        console.error('Rating submission failed:', error);
        await appAlert('评价失败，请重试');
      }
    };

    const loadDetails = async () => {
      detailsLoading.value = true;
      detailsError.value = '';
      try {
        const response = await apiFetch(`/api/mod-store/mod/${props.mod.id}/details`);
        const data = await response.json();

        if (data.success) {
          statistics.value = data.data.statistics;
          ratings.value = data.data.ratings || [];
        } else {
          detailsError.value = `加载详情失败：${data.error || data.detail || '请重试'}`;
        }
      } catch (error) {
        console.error('Failed to load mod details:', error);
        detailsError.value = `加载详情失败：${error?.message || '请重试'}`;
      } finally {
        detailsLoading.value = false;
      }
    };

    loadDetails();

    return {
      userRating,
      userComment,
      statistics,
      ratings,
      detailsLoading,
      detailsError,
      loadDetails,
      isDependencySatisfied,
      hasUpdate,
      formatDate,
      submitRating,
    };
  },
};
</script>

<style scoped>
.mod-details {
  padding: 20px;
}

.mod-header {
  display: flex;
  gap: 20px;
  align-items: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 2px solid #eee;
}

.mod-icon-large {
  width: 80px;
  height: 80px;
  background: linear-gradient(135deg, #3498db, #2980b9);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 40px;
}

.mod-title {
  font-size: 28px;
  color: #2c3e50;
  margin: 0 0 5px 0;
}

.mod-author {
  font-size: 16px;
  color: #7f8c8d;
  margin: 0 0 10px 0;
}

.mod-meta {
  display: flex;
  gap: 10px;
  align-items: center;
}

.version {
  font-size: 14px;
  color: #95a5a6;
  background: #f5f5f5;
  padding: 4px 10px;
  border-radius: 4px;
}

.badge {
  font-size: 12px;
  color: white;
  background: #27ae60;
  padding: 4px 10px;
  border-radius: 4px;
}

.mod-content {
  margin-bottom: 30px;
}

.mod-section {
  margin-bottom: 25px;
}

.mod-section h3 {
  font-size: 18px;
  color: #2c3e50;
  margin-bottom: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.mod-section h3 i {
  color: #3498db;
}

.description {
  font-size: 15px;
  color: #666;
  line-height: 1.8;
}

.dependencies-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dependency-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: #f9f9f9;
  border-radius: 6px;
  border-left: 3px solid #e74c3c;
}

.dependency-item.satisfied {
  border-left-color: #27ae60;
}

.dependency-item i {
  font-size: 16px;
}

.dependency-item.satisfied i {
  color: #27ae60;
}

.dependency-item:not(.satisfied) i {
  color: #e74c3c;
}

.dep-name {
  font-weight: 600;
  color: #2c3e50;
}

.dep-version {
  font-size: 13px;
  color: #7f8c8d;
  margin-left: auto;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 15px;
}

.stat-item {
  background: #f9f9f9;
  padding: 15px;
  border-radius: 8px;
  text-align: center;
}

.stat-item i {
  font-size: 24px;
  color: #3498db;
  margin-bottom: 8px;
}

.stat-value {
  display: block;
  font-size: 24px;
  font-weight: 600;
  color: #2c3e50;
}

.stat-label {
  display: block;
  font-size: 13px;
  color: #7f8c8d;
  margin-top: 5px;
}

.ratings-list {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.rating-item {
  background: #f9f9f9;
  padding: 15px;
  border-radius: 8px;
}

.rating-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.rating-stars {
  color: #f39c12;
}

.rating-date {
  font-size: 13px;
  color: #95a5a6;
}

.rating-comment {
  font-size: 14px;
  color: #666;
  line-height: 1.6;
  margin-bottom: 10px;
}

.rating-user {
  font-size: 13px;
  color: #7f8c8d;
}

.rating-user i {
  margin-right: 5px;
}

.no-ratings {
  text-align: center;
  color: #95a5a6;
  padding: 30px;
}

.details-state {
  text-align: center;
  color: #7f8c8d;
  padding: 30px;
}

.details-state.details-error {
  color: #e74c3c;
}

.btn-retry {
  display: inline-flex;
  margin-top: 12px;
}

.mod-footer {
  border-top: 2px solid #eee;
  padding-top: 20px;
}

.rating-form {
  margin-bottom: 20px;
}

.rating-form h4 {
  font-size: 16px;
  color: #2c3e50;
  margin-bottom: 10px;
}

.star-rating {
  display: flex;
  gap: 5px;
  margin-bottom: 10px;
}

.star-rating i {
  font-size: 24px;
  color: #f39c12;
  cursor: pointer;
  transition: transform 0.2s;
}

.star-rating i:hover {
  transform: scale(1.2);
}

.comment-input {
  width: 100%;
  padding: 10px;
  border: 2px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  resize: vertical;
  font-family: inherit;
}

.comment-input:focus {
  outline: none;
  border-color: #3498db;
}

.action-buttons {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-lg {
  padding: 12px 24px;
  font-size: 16px;
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

.btn-warning {
  background: #f39c12;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #e67e22;
}
</style>
