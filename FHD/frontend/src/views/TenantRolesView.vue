<template>
  <main class="rbac-page">
    <header class="rbac-header">
      <div>
        <h1>角色与权限</h1>
        <p>管理当前企业的业务角色，并将角色分配给本企业用户。</p>
      </div>
      <button type="button" :disabled="loading" @click="load">刷新</button>
    </header>

    <p v-if="error" class="rbac-message rbac-message--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="rbac-message" role="status">{{ notice }}</p>

    <section class="rbac-grid" :aria-busy="loading">
      <div class="rbac-panel">
        <div class="rbac-panel__heading">
          <h2>角色</h2>
          <button type="button" @click="startNewRole">新建角色</button>
        </div>
        <button
          v-for="role in roles"
          :key="role.id"
          type="button"
          class="rbac-role"
          :class="{ 'rbac-role--active': selectedRole?.id === role.id }"
          @click="selectRole(role)"
        >
          <strong>{{ role.name }}</strong>
          <span>{{ role.permissions.length }} 项权限{{ role.is_system ? ' · 系统角色' : '' }}</span>
        </button>
      </div>

      <form class="rbac-panel rbac-editor" @submit.prevent="saveRole">
        <h2>{{ creating ? '新建角色' : selectedRole?.name || '选择角色' }}</h2>
        <label v-if="creating">角色名称<input v-model.trim="draft.name" required maxlength="64" /></label>
        <label>说明<input v-model="draft.description" maxlength="200" /></label>
        <fieldset>
          <legend>权限</legend>
          <label v-for="permission in permissions" :key="permission.code" class="rbac-permission">
            <input
              v-model="draft.permissions"
              type="checkbox"
              :value="permission.code"
              :disabled="!creating && selectedRole?.is_system"
            />
            <span><strong>{{ permission.name }}</strong><small>{{ permission.code }}</small></span>
          </label>
        </fieldset>
        <button type="submit" :disabled="saving || (!creating && (!selectedRole || selectedRole.is_system))">
          {{ saving ? '保存中…' : creating ? '创建角色' : '保存角色' }}
        </button>
      </form>

      <section class="rbac-panel">
        <h2>用户角色</h2>
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
        <button type="button" :disabled="saving || !selectedUserId || !assignedRoleKey" @click="assignRole">
          分配角色
        </button>
        <p class="rbac-hint">权限修改或角色分配会撤销受影响用户的现有会话；请重新登录后继续使用。</p>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { rbacApi, type RbacPermission, type RbacRole, type RbacUser } from '@/api/rbac'

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

onMounted(load)
</script>

<style scoped>
.rbac-page { padding: 28px; color: var(--text-primary, #18202c); }
.rbac-header, .rbac-panel__heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.rbac-header h1, .rbac-panel h2 { margin: 0; }
.rbac-header p, .rbac-hint { color: var(--text-secondary, #697386); }
.rbac-grid { display: grid; grid-template-columns: minmax(220px, 0.8fr) minmax(320px, 1.3fr) minmax(250px, 1fr); gap: 16px; align-items: start; }
.rbac-panel { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--border-color, #dce2eb); border-radius: 12px; background: var(--surface, #fff); }
.rbac-role { display: grid; gap: 4px; padding: 10px; text-align: left; border: 1px solid var(--border-color, #dce2eb); border-radius: 8px; background: transparent; color: inherit; }
.rbac-role--active { border-color: #316ce6; background: #f2f6ff; }
.rbac-role span, .rbac-permission small { color: var(--text-secondary, #697386); font-size: 12px; }
.rbac-editor > label, .rbac-panel > label { display: grid; gap: 6px; }
.rbac-page input:not([type=checkbox]), .rbac-page select { min-height: 38px; padding: 7px 9px; border: 1px solid var(--border-color, #dce2eb); border-radius: 7px; background: var(--surface, #fff); color: inherit; }
.rbac-editor fieldset { display: grid; gap: 8px; max-height: 48vh; overflow: auto; border: 1px solid var(--border-color, #dce2eb); border-radius: 8px; }
.rbac-permission { display: flex; gap: 9px; align-items: start; padding: 5px; }
.rbac-permission span { display: grid; gap: 3px; }
.rbac-page button { min-height: 36px; padding: 7px 12px; border: 1px solid var(--border-color, #c8d0dc); border-radius: 7px; background: var(--surface, #fff); color: inherit; cursor: pointer; }
.rbac-page button:disabled { cursor: not-allowed; opacity: 0.55; }
.rbac-message--error { color: #b42318; }
.rbac-hint { margin: 0; font-size: 13px; line-height: 1.5; }
@media (max-width: 1000px) { .rbac-grid { grid-template-columns: 1fr; } }
</style>
