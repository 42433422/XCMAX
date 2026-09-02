<script setup lang="ts">
import type { TraditionalModeCtx } from './assemble'

// 拆分自 TraditionalModeView.vue 模板（原第 69–188 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: TraditionalModeCtx }>()

const {
  viewMode, loading, files, sortedFiles, selectedFile, changedFiles,
  toggleSort, sortKey, sortAsc, selectFile, onFileDoubleClick, showContextMenu,
  isImageFile, getImageUrl, openImagePreview, openFileByRead,
  getFileIcon, formatSize, formatTime,
} = props.tm
</script>

<template>
    <div class="file-list-container explorer-list-host">
      <table v-show="viewMode === 'details'" class="file-table explorer-detail-table">
        <thead>
          <tr>
            <th class="col-name sortable" scope="col" @click="toggleSort('name')">
              名称<span class="sort-glyph" v-if="sortKey === 'name'">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
            </th>
            <th class="col-size sortable" scope="col" @click="toggleSort('size')">
              大小<span class="sort-glyph" v-if="sortKey === 'size'">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
            </th>
            <th class="col-time sortable" scope="col" @click="toggleSort('modified')">
              修改日期<span class="sort-glyph" v-if="sortKey === 'modified'">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
            </th>
            <th class="col-type sortable" scope="col" @click="toggleSort('type')">
              类型<span class="sort-glyph" v-if="sortKey === 'type'">{{ sortAsc ? ' ▲' : ' ▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && files.length === 0">
            <td colspan="4" class="text-center">加载中...</td>
          </tr>
          <tr v-else-if="files.length === 0">
            <td colspan="4" class="text-center empty-hint">此文件夹为空</td>
          </tr>
          <template v-for="file in sortedFiles" :key="file.name">
            <tr
              :class="['file-row', { selected: selectedFile?.name === file.name, 'is-dir': file.is_dir }]"
              @click="selectFile(file)"
              @dblclick="onFileDoubleClick(file)"
              @contextmenu.prevent="showContextMenu($event, file)"
            >
              <td class="name-cell">
                <span v-if="changedFiles.has(file.name)" class="changed-badge">⚠️</span>
                <template v-if="file.is_dir">
                  <span class="icon">📁</span>
                  <span>{{ file.name }}</span>
                </template>
                <template v-else-if="isImageFile(file)">
                  <img
                    :data-src="getImageUrl(file)"
                    :alt="file.name"
                    class="thumbnail lazy-thumb"
                    @click.stop="openImagePreview(file)"
                  >
                </template>
                <template v-else>
                  <span
                    class="icon icon-read-open"
                    title="单击：读取文件（Excel 在网页中打开，其它文件下载）"
                    role="button"
                    tabindex="0"
                    @click.stop="openFileByRead(file)"
                    @keydown.enter.prevent="openFileByRead(file)"
                    @keydown.space.prevent="openFileByRead(file)"
                  >{{ getFileIcon(file) }}</span>
                  <span>{{ file.name }}</span>
                </template>
              </td>
              <td>{{ formatSize(file.size) }}</td>
              <td>{{ formatTime(file.modified_time) }}</td>
              <td><span class="type-tag">{{ file.is_dir ? '文件夹' : (file.type || '文件') }}</span></td>
            </tr>
          </template>
        </tbody>
      </table>

      <div
        v-show="viewMode !== 'details'"
        class="explorer-icon-view"
        :class="{ 'mode-icons': viewMode === 'icons', 'mode-large': viewMode === 'large' }"
      >
        <div v-if="loading && files.length === 0" class="icon-view-state">加载中...</div>
        <div v-else-if="files.length === 0" class="icon-view-state empty-hint">此文件夹为空</div>
        <div v-else class="icon-grid" role="list">
          <div
            v-for="file in sortedFiles"
            :key="file.name"
            class="icon-tile"
            role="listitem"
            :class="{ selected: selectedFile?.name === file.name, 'is-dir': file.is_dir }"
            @click="selectFile(file)"
            @dblclick="onFileDoubleClick(file)"
            @contextmenu.prevent="showContextMenu($event, file)"
          >
            <span v-if="changedFiles.has(file.name)" class="tile-changed" title="有变更">⚠</span>
            <div class="tile-visual">
              <template v-if="file.is_dir">
                <span class="tile-folder-glyph" aria-hidden="true">📁</span>
              </template>
              <template v-else-if="isImageFile(file)">
                <img
                  :data-src="getImageUrl(file)"
                  :alt="file.name"
                  class="tile-thumb lazy-thumb"
                  @click.stop="openImagePreview(file)"
                >
              </template>
              <template v-else>
                <div
                  class="tile-visual-file-hit"
                  title="单击：读取文件（Excel 用 /read 在网页中编辑，其它文件下载）"
                  role="button"
                  tabindex="0"
                  @click.stop="openFileByRead(file)"
                  @keydown.enter.prevent="openFileByRead(file)"
                  @keydown.space.prevent="openFileByRead(file)"
                >
                  <span class="tile-file-glyph" aria-hidden="true">{{ getFileIcon(file) }}</span>
                </div>
              </template>
            </div>
            <div
              class="tile-name"
              :title="file.is_dir ? file.name : (file.name + '（单击图标/双击：读取打开；Excel 网页编辑）')"
            >{{ file.name }}</div>
          </div>
        </div>
      </div>
    </div>
</template>

<style scoped src="./traditional-mode.css"></style>
