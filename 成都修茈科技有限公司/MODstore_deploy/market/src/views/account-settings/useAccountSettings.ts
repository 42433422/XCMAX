// 账户中心主逻辑：基本信息/密码表单、会员档位文案与头像上传管理。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '../../api'
import { normalizeMeResponse } from '../../domain/accountLevel'
import { useAuthStore } from '../../stores/auth'

export function useAccountSettings() {
  const authStore = useAuthStore()
  const {
    levelProfile,
    membership,
    membershipTier,
    membershipFetchFailed,
    username: storeUsername,
    isAdmin,
    user: authUser,
  } = storeToRefs(authStore)

  const username = ref('')
  const email = ref('')
  const saving = ref(false)
  const savingPw = ref(false)
  const msg = ref('')
  const err = ref('')
  const pw = ref({ current: '', new1: '', new2: '' })
  const avatarInputRef = ref<HTMLInputElement | null>(null)
  const avatarPreviewUrl = ref('')
  const avatarBusy = ref(false)
  let avatarObjectUrl = ''

  function revokeAvatarObjectUrl() {
    if (avatarObjectUrl) {
      URL.revokeObjectURL(avatarObjectUrl)
      avatarObjectUrl = ''
    }
  }

  async function loadAvatarPreview() {
    revokeAvatarObjectUrl()
    const path = authUser.value?.avatar_url
    if (!path) {
      avatarPreviewUrl.value = ''
      return
    }
    try {
      const blob = await api.fetchAvatarBlob(String(path))
      avatarObjectUrl = URL.createObjectURL(blob)
      avatarPreviewUrl.value = avatarObjectUrl
    } catch {
      avatarPreviewUrl.value = ''
    }
  }

  function openAvatarPicker() {
    avatarInputRef.value?.click()
  }

  async function onAvatarSelected(ev: Event) {
    const input = ev.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    if (!/^image\/(jpeg|png|webp|gif)$/i.test(file.type)) {
      err.value = '请选择 JPG、PNG、WebP 或 GIF 图片'
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      err.value = '头像不能超过 2MB'
      return
    }
    msg.value = ''
    err.value = ''
    avatarBusy.value = true
    try {
      await api.uploadAvatar(file)
      msg.value = '头像已更新'
      await authStore.refreshSession(true)
      await loadAvatarPreview()
    } catch (e: unknown) {
      err.value = e instanceof Error ? e.message : '头像上传失败'
    } finally {
      avatarBusy.value = false
    }
  }

  async function removeAvatar() {
    if (!authUser.value?.avatar_url && !avatarPreviewUrl.value) return
    msg.value = ''
    err.value = ''
    avatarBusy.value = true
    try {
      await api.deleteAvatar()
      revokeAvatarObjectUrl()
      avatarPreviewUrl.value = ''
      msg.value = '已移除头像'
      await authStore.refreshSession(true)
    } catch (e: unknown) {
      err.value = e instanceof Error ? e.message : '移除失败'
    } finally {
      avatarBusy.value = false
    }
  }

  const canChangePw = computed(
    () =>
      pw.value.current.length > 0 &&
      pw.value.new1.length >= 6 &&
      pw.value.new1 === pw.value.new2,
  )

  const level = computed(() => levelProfile.value)
  const progressPercent = computed(() => Math.round(((level.value?.progress ?? 0) as number) * 100))
  const expToNextLevel = computed(() => {
    const l = level.value
    if (!l || l.nextLevelMinExp === null) return 0
    return Math.max(0, (l.nextLevelMinExp as number) - l.experience)
  })

  const displayUsername = computed(() => (username.value || storeUsername.value || '用户').trim() || '用户')
  const avatarInitial = computed(() => {
    const s = displayUsername.value.trim()
    if (!s) return '?'
    return s.slice(0, 1).toUpperCase()
  })

  const membershipLabel = computed(() => {
    if (membershipFetchFailed.value) return '暂不可用'
    const m = membership.value
    if (m?.label) return String(m.label)
    if (m?.tier && m.tier !== 'free') return String(m.tier)
    return '普通用户'
  })

  const membershipHint = computed(() => {
    if (membershipFetchFailed.value) {
      return '无法连接支付服务以读取会员档位（网络或网关异常）。请稍后刷新页面；若已购买仍异常，请联系运维核对支付服务与数据库。'
    }
    const t = (membershipTier.value || 'free').toLowerCase()
    if (t === 'free' || !membership.value?.is_member) {
      return '未开通会员。升级可享受更高 AI 额度、BYOK、会员标识等权益。'
    }
    if (t === 'vip' || t === 'vip_plus') {
      return '你正在使用付费会员能力，可在「会员购买」中继续升级。'
    }
    if (t.startsWith('svip')) {
      return '你正在使用 SVIP 系列权益。可在套餐页按档升级。'
    }
    return '感谢支持，更多权益可在「会员购买」中查看。'
  })

  watch(
    () => authUser.value?.avatar_url,
    () => {
      void loadAvatarPreview()
    },
  )

  onMounted(async () => {
    try {
      const me = normalizeMeResponse(await api.me())
      if (!me) {
        err.value = '加载失败'
        return
      }
      username.value = me.username || ''
      email.value = me.email || ''
      await authStore.refreshSession(true)
      await authStore.refreshMembership()
      await loadAvatarPreview()
    } catch (e: unknown) {
      err.value = e instanceof Error ? e.message : '加载失败'
    }
  })

  onBeforeUnmount(() => {
    revokeAvatarObjectUrl()
  })

  async function saveProfile() {
    msg.value = ''
    err.value = ''
    saving.value = true
    try {
      await api.updateProfile(username.value.trim())
      msg.value = '已保存'
      await authStore.refreshSession(true)
    } catch (e: unknown) {
      err.value = e instanceof Error ? e.message : '保存失败'
    } finally {
      saving.value = false
    }
  }

  async function changePw() {
    msg.value = ''
    err.value = ''
    savingPw.value = true
    try {
      await api.changePassword(pw.value.current, pw.value.new1)
      msg.value = '密码已更新'
      pw.value = { current: '', new1: '', new2: '' }
    } catch (e: unknown) {
      err.value = e instanceof Error ? e.message : '修改失败'
    } finally {
      savingPw.value = false
    }
  }

  return {
    authUser,
    isAdmin,
    username,
    email,
    saving,
    savingPw,
    msg,
    err,
    pw,
    avatarInputRef,
    avatarPreviewUrl,
    avatarBusy,
    openAvatarPicker,
    onAvatarSelected,
    removeAvatar,
    canChangePw,
    level,
    progressPercent,
    expToNextLevel,
    displayUsername,
    avatarInitial,
    membershipLabel,
    membershipHint,
    membershipTier,
    saveProfile,
    changePw,
  }
}
