import { api } from './core'
import type { ApiResponse } from '@/types/api'

export type RbacPermission = { id: number; code: string; name: string; description: string; module: string }
export type RbacRole = {
  id: number
  key: string
  name: string
  description: string
  is_system: boolean
  permissions: RbacPermission[]
  sessions_revoked?: number
}
export type RbacUser = {
  id: number
  username: string
  display_name: string
  role: string
  is_active: boolean
}
export type RoleAssignment = { user_id: number; role: string; display_role: string; sessions_revoked: number }

const data = async <T>(request: Promise<ApiResponse<T>>): Promise<T> => {
  const response = await request
  if (response?.success !== true || response.data === undefined) {
    throw new Error(response?.message || '角色权限请求失败')
  }
  return response.data
}

export const rbacApi = {
  listRoles: () => data(api.get<ApiResponse<RbacRole[]>>('/api/rbac/roles')),
  listPermissions: () => data(api.get<ApiResponse<RbacPermission[]>>('/api/rbac/permissions')),
  listUsers: () => data(api.get<ApiResponse<RbacUser[]>>('/api/rbac/users')),
  createRole: (body: { name: string; description: string; permissions: string[] }) =>
    data(api.post<ApiResponse<RbacRole>>('/api/rbac/roles', body)),
  updateRole: (id: number, body: { description: string; permissions: string[] }) =>
    data(api.put<ApiResponse<RbacRole>>(`/api/rbac/roles/${id}`, body)),
  assignRole: (userId: number, role: string) =>
    data(api.put<ApiResponse<RoleAssignment>>(`/api/rbac/users/${userId}/role`, { role })),
  inviteMember: (targetUsername: string) =>
    data(api.post<ApiResponse<{ code: string; target_username: string; expires_at: string }>>(
      '/api/rbac/invitations', { target_username: targetUsername },
    )),
}
