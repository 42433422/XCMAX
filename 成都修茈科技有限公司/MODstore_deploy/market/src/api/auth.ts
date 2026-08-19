import {
  req,
  authRequest,
  requestBlob,
  setTokensFromAuthResponse,
  type AuthResponse,
} from './shared'

export interface MeResponse extends Record<string, unknown> {
  ok?: boolean
  success?: boolean
  username?: string
  email?: string
}

export interface PasswordResetResponse extends Record<string, unknown> {
  ok?: boolean
  success?: boolean
  message?: string
}

export const auth = {
  register: async (username: string, password: string, email: string, verificationCode = '') => {
    const res = await authRequest('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, email, verification_code: verificationCode }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  login: async (username: string, password: string) => {
    const res = await authRequest('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  loginWithCode: async (email: string, code: string) => {
    const res = await authRequest('/api/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  sendPhoneCode: (phone: string) =>
    req('/api/auth/send-phone-code', { method: 'POST', body: JSON.stringify({ phone }) }),
  loginWithPhoneCode: async (phone: string, code: string) => {
    const res = await authRequest('/api/auth/login-with-phone-code', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    })
    setTokensFromAuthResponse(res as AuthResponse)
    return res
  },
  me: () => req<MeResponse>('/api/auth/me'),
  accountBootstrap: () => req('/api/account/bootstrap'),
  sendVerificationCode: (email: string) =>
    req('/api/auth/send-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendRegisterVerificationCode: (email: string) =>
    req('/api/auth/send-register-code', { method: 'POST', body: JSON.stringify({ email }) }),
  sendResetPasswordCode: (email: string) =>
    req<PasswordResetResponse>('/api/auth/send-reset-password-code', { method: 'POST', body: JSON.stringify({ email }) }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    req<PasswordResetResponse>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password: newPassword }),
    }),
  submitLandingContact: (data: {
    name: string
    email: string
    phone?: string
    company?: string
    message?: string
    source?: string
    campaign?: string
    medium?: string
    content?: string
    privacy_agreed?: boolean
    privacy_version?: string
    privacy_url?: string
    cs_uid?: number
    cs_t?: string
  }) =>
    req('/api/public/contact', {
      method: 'POST',
      body: JSON.stringify({
        name: data.name,
        email: data.email,
        phone: data.phone ?? '',
        company: data.company ?? '',
        message: data.message ?? '',
        source: data.source ?? 'home',
        campaign: data.campaign ?? '',
        medium: data.medium ?? '',
        content: data.content ?? '',
        privacy_agreed: data.privacy_agreed ?? false,
        privacy_version: data.privacy_version ?? '2026-06-20',
        privacy_url: data.privacy_url ?? '/privacy.html',
        cs_uid: data.cs_uid ?? undefined,
        cs_t: data.cs_t ?? '',
      }),
    }),
  updateProfile: (username: string) =>
    req('/api/auth/profile', { method: 'PUT', body: JSON.stringify({ username }) }),
  changePassword: (currentPassword: string, newPassword: string) =>
    req('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  uploadAvatar: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ ok: boolean; avatar_url: string; avatar_version: number }>('/api/auth/avatar', {
      method: 'POST',
      body: fd,
    })
  },
  deleteAvatar: () =>
    req<{ ok: boolean; avatar_url: null }>('/api/auth/avatar', { method: 'DELETE' }),
  fetchAvatarBlob: (avatarUrl: string) => {
    const path = avatarUrl.startsWith('/') ? avatarUrl : `/${avatarUrl}`
    return requestBlob(path)
  },
}
