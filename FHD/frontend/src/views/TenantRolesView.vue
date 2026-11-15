<template>
  <main class="rbac-page">
    <header class="rbac-header">
      <div>
        <h1>角色与权限</h1>
        <p>管理当前企业的业务角色，并将角色分配给本企业用户。</p>
      </div>
      <button type="button" class="rbac-btn" :disabled="loading" @click="load">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }"></i>
        刷新
      </button>
    </header>

    <p v-if="error" class="rbac-message rbac-message--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="rbac-message" role="status">{{ notice }}</p>

    <section class="rbac-grid" :aria-busy="loading">
      <div class="rbac-panel rbac-roles">
        <div class="rbac-panel__heading">
          <h2>角色<span class="rbac-count">{{ roles.length }}</span></h2>
          <button type="button" class="rbac-btn rbac-btn--primary" @click="startNewRole">
            <i class="fa fa-plus"></i> 新建角色
          </button>
        </div>
        <div class="rbac-role-list">
          <button
            v-for="role in roles"
            :key="role.id"
            type="button"
            class="rbac-role"
            :class="{ 'rbac-role--active': selectedRole?.id === role.id }"
            @click="selectRole(role)"
          >
            <strong>
              {{ role.name }}
              <span v-if="role.is_system" class="rbac-tag">系统</span>
            </strong>
            <span>{{ role.permissions.length }} 项权限{{ role.is_system ? ' · 系统角色' : '' }}</span>
          </button>
          <p v-if="roles.length === 0" class="rbac-empty">暂无角色，点击右上角新建。</p>
        </div>
      </div>

      <form class="rbac-panel rbac-editor" @submit.prevent="saveRole">
        <div class="rbac-panel__heading">
          <h2>
            {{ creating ? '新建角色' : selectedRole?.name || '选择角色' }}
            <span v-if="!creating && selectedRole?.is_system" class="rbac-tag">系统角色 · 只读</span>
          </h2>
        </div>
        <div v-if="creating" class="rbac-editor__basic">
          <label>角色名称<input v-model.trim="draft.name" required maxlength="64" placeholder="例如：审核员" /></label>
          <label>说明<input v-model="draft.description" maxlength="200" placeholder="这个角色负责什么" /></label>
        </div>
        <label v-else>说明<input v-model="draft.description" maxlength="200" placeholder="这个角色负责什么" /></label>
        <fieldset>
          <legend>权限<span class="rbac-count">{{ draft.permissions.length }} / {{ permissions.length }}</span></legend>
          <div class="rbac-permission-grid">
            <label v-for="permission in permissions" :key="permission.code" class="rbac-permission">
              <input
                v-model="draft.permissions"
                type="checkbox"
                :value="permission.code"
                :disabled="!creating && selectedRole?.is_system"
              />
              <span><strong>{{ permission.name }}</strong><small>{{ permission.code }}</small></span>
            </label>
          </div>
        </fieldset>
        <div class="rbac-editor__footer">
          <span class="rbac-hint">保存后受影响用户的现有会话会被撤销。</span>
          <button type="submit" class="rbac-btn rbac-btn--primary" :disabled="saving || (!creating && (!selectedRole || selectedRole.is_system))">
            {{ saving ? '保存中…' : creating ? '创建角色' : '保存角色' }}
          </button>
        </div>
      </form>

      <div class="rbac-side">
        <section class="rbac-panel">
          <div class="rbac-panel__heading">
            <h2>用户角色</h2>
          </div>
          <label>用户
            <select v-model.number="selectedUserId">
              <option :value="0">选择用户</option>
              <option v-for="user in users" :key="user.id" :value="user.id">
                {{ user.display_name || user.username }}{{ user.is_active ? '' : '（已停用）' }}
              </option>
            </select>
          </label>
          <label>角色
            <select v-model="assignedRoleKey">
              <option value="">选择角色</option>
              <option v-for="role in assignableRoles" :key="role.key" :value="role.key">{{ role.name }}</option>
            </select>
          </label>
          <p v-if="selectedUser" class="rbac-hint">当前角色：{{ displayRole(selectedUser.role) }}</p>
          <button type="button" class="rbac-btn rbac-btn--primary" :disabled="saving || !selectedUserId || !assignedRoleKey" @click="assignRole">
            分配角色
          </button>
          <p class="rbac-hint">权限修改或角色分配会撤销受影响用户的现有会话；请重新登录后继续使用。</p>
        </section>

        <section v-if="accountProfile.tenantIsOwner" class="rbac-panel">
          <div class="rbac-panel__heading">
            <h2>邀请企业成员</h2>
          </div>
          <p class="rbac-hint">企业所有者可邀请已开通企业版的市场账号。对方首次登录时填写一次性邀请码。</p>
          <label>市场账号用户名<input v-model.trim="inviteUsername" maxlength="128" autocomplete="off" /></label>
          <button type="button" class="rbac-btn rbac-btn--primary" :disabled="saving || !inviteUsername" @click="inviteMember">生成邀请码</button>
          <div v-if="invitation" class="rbac-invitation" role="status">
            <span>发送给 {{ invitation.target_username }}（24 小时内有效）</span>
            <code>{{ invitation.code }}</code>
            <button type="button" class="rbac-btn" @click="copyInvitation">复制邀请码</button>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { rbacApi, type RbacPermission, type RbacRole, type RbacUser } from '@/api/rbac'
import { useAccountProfileStore } from '@/stores/accountProfile'

const accountProfile = useAccountProfileStore()

const roles = ref<RbacRole[]>([])
const permissions = ref<RbacPermission[]>([])
const users = ref<RbacUser[]>([])
const selectedRole = ref<RbacRole | null>(null)
const creating = ref(false)
const selectedUserId = ref(0)
const assignedRoleKey = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const inviteUsername = ref('')
const invitation = ref<{ code: string; target_username: string; expires_at: string } | null>(null)
const draft = reactive({ name: '', description: '', permissions: [] as string[] })
const assignableRoles = computed(() => roles.value.filter((role) => role.key !== 'admin'))
const selectedUser = computed(() => users.value.find((user) => user.id === selectedUserId.value))

function displayRole(key: string) {
  return roles.value.find((role) => role.key === key)?.name || key
}

function selectRole(role: RbacRole) {
  creating.value = false
  selectedRole.value = role
  draft.name = role.name
  draft.description = role.description
  draft.permissions = role.permissions.map((permission) => permission.code)
}

function startNewRole() {
  creating.value = true
  selectedRole.value = null
  draft.name = ''
  draft.description = ''
  draft.permissions = []
}

async function load() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const [nextRoles, nextPermissions, nextUsers] = await Promise.all([
      rbacApi.listRoles(), rbacApi.listPermissions(), rbacApi.listUsers(),
    ])
    roles.value = nextRoles
    permissions.value = nextPermissions
    users.value = nextUsers
    const current = selectedRole.value && nextRoles.find((role) => role.id === selectedRole.value?.id)
    if (current) selectRole(current)
    else if (nextRoles.length && !creating.value) selectRole(nextRoles[0])
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法加载角色权限，请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function saveRole() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const wasCreating = creating.value
    const body = { description: draft.description, permissions: [...draft.permissions] }
    const saved = wasCreating
      ? await rbacApi.createRole({ ...body, name: draft.name })
      : await rbacApi.updateRole(selectedRole.value!.id, body)
    await load()
    const current = roles.value.find((role) => role.id === saved.id)
    if (current) selectRole(current)
    notice.value = wasCreating
      ? '角色已创建。'
      : `角色权限已更新；${saved.sessions_revoked || 0} 个现有会话已撤销，受影响用户需要重新登录。`
    creating.value = false
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败。'
  } finally {
    saving.value = false
  }
}

async function assignRole() {
  if (saving.value || !selectedUserId.value || !assignedRoleKey.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await rbacApi.assignRole(selectedUserId.value, assignedRoleKey.value)
    await load()
    notice.value = `用户角色已更新；${result.sessions_revoked} 个现有会话已撤销，用户需要重新登录。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '角色分配失败。'
  } finally {
    saving.value = false
  }
}

async function inviteMember() {
  if (saving.value || !inviteUsername.value) return
  saving.value = true
  error.value = ''
  invitation.value = null
  try {
    invitation.value = await rbacApi.inviteMember(inviteUsername.value)
    notice.value = '邀请码已生成，仅显示一次。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法生成邀请码。'
  } finally {
    saving.value = false
  }
}

async function copyInvitation() {
  if (!invitation.value) return
  await navigator.clipboard.writeText(invitation.value.code)
  notice.value = '邀请码已复制。'
}

onMounted(async () => {
  await accountProfile.refreshFromServer()
  await load()
})
</script>

<style scoped>
.rbac-page {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 28px 32px;
  background: #f5f7fa;
  color: var(--text-primary, #18202c);
}

.rbac-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.rbac-header h1 {
  margin: 0 0 6px 0;
  font-size: 22px;
}

.rbac-header p {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary, #6b7280);
}

.rbac-grid {
  display: grid;
  grid-template-columns: minmax(240px, 0.85fr) minmax(380px, 1.6fr) minmax(280px, 1fr);
  gap: 16px;
  align-items: start;
}

.rbac-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.rbac-panel {
  display: grid;
  gap: 14px;
  min-width: 0;
  padding: 18px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(31, 41, 55, 0.04);
}

.rbac-panel__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.rbac-panel__heading h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.rbac-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  padding: 0 7px;
  border-radius: 10px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
}

.rbac-tag {
  padding: 1px 8px;
  border-radius: 10px;
  background: #f3f4f6;
  color: #6b7280;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

/* 角色列表 */
.rbac-role-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 4px;
}

.rbac-role-list::-webkit-scrollbar {
  width: 6px;
}

.rbac-role-list::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}

.rbac-role {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  text-align: left;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafbfc;
  color: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.rbac-role:hover {
  border-color: #c7d2fe;
  background: #f8fafc;
}

.rbac-role--active {
  border-color: #2563eb;
  background: #eff6ff;
}

.rbac-role strong {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #1f2937;
}

.rbac-role span {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
}

.rbac-empty {
  margin: 0;
  padding: 28px 12px;
  text-align: center;
  font-size: 13px;
  color: #9ca3af;
}

/* 角色编辑器 */
.rbac-editor > label,
.rbac-panel > label,
.rbac-editor__basic label {
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: #4b5563;
}

.rbac-editor__basic {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.rbac-page input:not([type=checkbox]),
.rbac-page select {
  width: 100%;
  min-height: 38px;
  padding: 7px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 7px;
  background: #fff;
  color: inherit;
  font-size: 13px;
  transition: border-color 0.15s;
}

.rbac-page input:not([type=checkbox]):focus,
.rbac-page select:focus {
  outline: none;
  border-color: #2563eb;
}

.rbac-editor fieldset {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 12px;
  max-height: 46vh;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}

.rbac-editor legend {
  padding: 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.rbac-editor legend .rbac-count {
  margin-left: 8px;
  font-weight: 500;
}

.rbac-permission-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.rbac-permission {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.rbac-permission:hover {
  background: #f8fafc;
}

.rbac-permission input {
  margin-top: 2px;
  accent-color: #2563eb;
}

.rbac-permission span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.rbac-permission strong {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
}

.rbac-permission small {
  color: var(--text-secondary, #9ca3af);
  font-size: 11px;
  font-family: monospace;
}

.rbac-editor__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

/* 按钮与提示 */
.rbac-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 7px 14px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
  color: #4b5563;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.rbac-btn:hover:not(:disabled) {
  border-color: #2563eb;
  color: #2563eb;
}

.rbac-btn--primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #fff;
}

.rbac-btn--primary:hover:not(:disabled) {
  border-color: #1d4ed8;
  background: #1d4ed8;
  color: #fff;
}

.rbac-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.rbac-page button {
  cursor: pointer;
}

.rbac-page button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.rbac-message {
  margin: 0 0 14px 0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  background: #f0fdf4;
  color: #047857;
  border: 1px solid #d1fae5;
}

.rbac-message--error {
  color: #b42318;
  background: #fef2f2;
  border-color: #fecaca;
}

.rbac-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary, #6b7280);
}

.rbac-invitation {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px dashed #c7d2fe;
  border-radius: 8px;
  background: #f8faff;
  overflow-wrap: anywhere;
  font-size: 13px;
}

.rbac-invitation code {
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e0e7ff;
  font-size: 13px;
  color: #1d4ed8;
}

@media (max-width: 1280px) {
  .rbac-grid {
    grid-template-columns: minmax(220px, 0.8fr) minmax(0, 1.4fr);
  }

  .rbac-side {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .rbac-page {
    padding: 16px;
  }

  .rbac-grid,
  .rbac-side {
    grid-template-columns: minmax(0, 1fr);
  }

  .rbac-editor__basic,
  .rbac-permission-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .rbac-editor__footer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
