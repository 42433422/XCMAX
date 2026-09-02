<template>
  <div class="kb-mgr">
    <header class="kb-header">
      <div>
        <h1 class="page-title">知识库</h1>
        <p class="kb-sub">
          上传资料形成集合，AI 员工与工作流会按权限自动检索；可分享给员工、工作流或其他用户。
        </p>
      </div>
      <button class="btn btn-primary-solid" type="button" @click="openCreateModal">+ 新建集合</button>
    </header>

    <section class="kb-status" v-if="status">
      <div class="kb-status__item">
        <span class="kb-status__label">引擎</span>
        <span class="kb-status__value">
          {{ status.engine?.backend || '-' }}
          <span class="kb-status__hint" v-if="status.engine?.persist_dir">· {{ status.engine.persist_dir }}</span>
        </span>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">Embedding</span>
        <span class="kb-status__value">
          {{ status.embedding?.model || '-' }} · dim {{ status.embedding?.dim || 0 }}
          <span class="kb-status__hint" v-if="!status.embedding?.configured">（未配置 API Key）</span>
        </span>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">我的集合</span>
        <span class="kb-status__value">{{ status.owned_collections || 0 }} 个</span>
      </div>
    </section>

    <div v-if="loading && !collections.length" class="kb-loading">加载中…</div>
    <div v-if="error" class="flash flash-err">{{ error }}</div>

    <section v-for="group in groupedCollections" :key="group.key" class="kb-section">
      <h2 class="kb-section__title">
        {{ group.title }}
        <span class="kb-section__count">· {{ group.items.length }}</span>
      </h2>
      <div v-if="!group.items.length" class="kb-empty">{{ group.empty }}</div>
      <div v-else class="kb-grid">
        <article
          v-for="coll in group.items"
          :key="coll.id"
          class="kb-card"
          :class="{ 'kb-card--open': openedId === coll.id }"
        >
          <header class="kb-card__head" @click="toggleCollection(coll)">
            <h3 class="kb-card__title">{{ coll.name }}</h3>
            <span class="kb-card__meta">
              {{ ownerKindLabel(coll.owner_kind) }}
              · {{ coll.chunk_count || 0 }} chunks
              · {{ visibilityLabel(coll.visibility) }}
            </span>
          </header>
          <p v-if="coll.description" class="kb-card__desc">{{ coll.description }}</p>

          <div v-if="openedId === coll.id" class="kb-card__body">
            <div class="kb-card__actions">
              <label class="btn btn-default kb-upload-btn">
                <input
                  type="file"
                  class="kb-upload-input"
                  :disabled="!canWrite(coll) || uploading"
                  :accept="ACCEPT"
                  @change="onPickFile($event, coll)"
                />
                <span>{{ uploading && uploadingCollId === coll.id ? '上传中…' : '+ 上传文档' }}</span>
              </label>
              <button
                class="btn btn-default"
                type="button"
                :disabled="!canAdmin(coll)"
                @click="openShareModal(coll)"
              >
                共享 / 授权
              </button>
              <button
                class="btn btn-danger"
                type="button"
                :disabled="!canAdmin(coll)"
                @click="deleteCollection(coll)"
              >
                删除集合
              </button>
            </div>

            <div v-if="docsByColl[coll.id]?.error" class="flash flash-err">
              {{ docsByColl[coll.id].error }}
            </div>
            <div v-if="!docsByColl[coll.id]?.docs?.length" class="kb-empty">
              暂无文档
            </div>
            <ul v-else class="kb-docs">
              <li v-for="doc in docsByColl[coll.id].docs" :key="doc.doc_id" class="kb-doc">
                <div class="kb-doc__name">{{ doc.filename || '(未命名)' }}</div>
                <div class="kb-doc__meta">
                  {{ formatBytes(doc.size_bytes) }} · {{ doc.chunk_count }} chunks
                  · {{ formatDate(doc.created_at) }}
                </div>
                <button
                  class="btn btn-link kb-doc__del"
                  type="button"
                  :disabled="!canWrite(coll)"
                  @click="deleteDoc(coll, doc)"
                >
                  删除
                </button>
              </li>
            </ul>
          </div>
        </article>
      </div>
    </section>

    <!-- 创建集合 -->
    <div v-if="showCreate" class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal__panel">
        <header class="kb-modal__head">
          <h3>新建集合</h3>
          <button class="btn btn-link" type="button" @click="showCreate = false">×</button>
        </header>
        <div class="kb-modal__body">
          <label class="kb-field">
            <span class="kb-field__label">名称</span>
            <input
              class="input"
              v-model.trim="createForm.name"
              maxlength="64"
              placeholder="如：业务 SOP / 产品手册"
            />
          </label>
          <label class="kb-field">
            <span class="kb-field__label">说明（可选）</span>
            <textarea class="input" v-model.trim="createForm.description" maxlength="500" rows="3"></textarea>
          </label>
          <label class="kb-field">
            <span class="kb-field__label">可见性</span>
            <select class="input" v-model="createForm.visibility">
              <option value="private">仅自己</option>
              <option value="shared">仅授权用户</option>
              <option value="public">所有登录用户可读</option>
            </select>
          </label>
          <div v-if="createError" class="flash flash-err">{{ createError }}</div>
        </div>
        <footer class="kb-modal__foot">
          <button class="btn btn-default" type="button" @click="showCreate = false">取消</button>
          <button
            class="btn btn-primary-solid"
            type="button"
            :disabled="!createForm.name || creating"
            @click="submitCreate"
          >
            {{ creating ? '创建中…' : '创建' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 共享 -->
    <div v-if="showShare" class="kb-modal" role="dialog" aria-modal="true">
      <div class="kb-modal__panel">
        <header class="kb-modal__head">
          <h3>共享 / 授权 · {{ shareForm.coll?.name }}</h3>
          <button class="btn btn-link" type="button" @click="closeShareModal">×</button>
        </header>
        <div class="kb-modal__body">
          <label class="kb-field">
            <span class="kb-field__label">授权给（owner kind）</span>
            <select class="input" v-model="shareForm.grantee_kind">
              <option value="user">用户</option>
              <option value="employee">AI 员工</option>
              <option value="workflow">工作流</option>
              <option value="org">组织</option>
            </select>
          </label>
          <label class="kb-field">
            <span class="kb-field__label">对应 ID</span>
            <input
              class="input"
              v-model.trim="shareForm.grantee_id"
              :placeholder="granteeIdPlaceholder"
              maxlength="64"
            />
          </label>
          <label class="kb-field">
            <span class="kb-field__label">权限</span>
            <select class="input" v-model="shareForm.permission">
              <option value="read">只读</option>
              <option value="write">可写</option>
              <option value="admin">管理员</option>
            </select>
          </label>
          <div v-if="shareError" class="flash flash-err">{{ shareError }}</div>
        </div>
        <footer class="kb-modal__foot">
          <button class="btn btn-default" type="button" @click="closeShareModal">取消</button>
          <button
            class="btn btn-primary-solid"
            type="button"
            :disabled="!shareForm.grantee_id || sharing"
            @click="submitShare"
          >
            {{ sharing ? '保存中…' : '保存授权' }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：集合/文档/共享全部逻辑在 ./knowledge-manager/，样式在 ./knowledge-manager/knowledgeManager.css。
import { useKnowledgeManager } from './knowledge-manager/useKnowledgeManager'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  ACCEPT, status, collections, docsByColl, loading, error, openedId,
  uploading, uploadingCollId, showCreate, creating, createError, createForm,
  showShare, sharing, shareError, shareForm,
  groupedCollections, granteeIdPlaceholder,
  ownerKindLabel, visibilityLabel, canAdmin, canWrite, formatBytes, formatDate,
  loadStatus, loadCollections, loadDocs, toggleCollection,
  openCreateModal, submitCreate, openShareModal, closeShareModal, submitShare,
  deleteCollection, deleteDoc, onPickFile,
} = useKnowledgeManager()
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./knowledge-manager/knowledgeManager.css"></style>
