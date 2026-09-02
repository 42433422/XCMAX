// 拆分自 HomeView.vue：联系表单 + 客服 intake 参数解析（逻辑逐字迁移，行为不变）。
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import type { ContactFormState } from './homeViewTypes'

export type ContactField = 'name' | 'email' | 'phone' | 'company' | 'message' | 'privacyAgreed'

export function useContactForm() {
  const route = useRoute()

  const contactForm = ref<ContactFormState>({ name: '', email: '', phone: '', company: '', message: '', privacyAgreed: false })
  const contactSubmitting = ref(false)
  const contactError = ref('')
  const contactSuccess = ref(false)
  const csIntakeActive = ref(false)
  const csIntakeUid = ref<number | null>(null)
  const csIntakeToken = ref('')

  function decodeBriefParam(raw: string): string {
    const s = (raw || '').trim().replace(/-/g, '+').replace(/_/g, '/')
    const pad = '='.repeat((4 - (s.length % 4)) % 4)
    try {
      return decodeURIComponent(escape(atob(s + pad)))
    } catch {
      return ''
    }
  }

  function applyCsIntakeFromRoute() {
    const q = route.query
    const uid = Number(q.cs_uid)
    const token = String(q.cs_t || '').trim()
    if (!Number.isFinite(uid) || uid <= 0 || !token) {
      csIntakeActive.value = false
      csIntakeUid.value = null
      csIntakeToken.value = ''
      return
    }
    csIntakeActive.value = true
    csIntakeUid.value = uid
    csIntakeToken.value = token
    const brief = decodeBriefParam(String(q.brief || ''))
    const csName = String(q.cs_name || '').trim()
    if (csName && !contactForm.value.name) contactForm.value.name = csName
    if (brief && !contactForm.value.message) contactForm.value.message = brief
    void nextTick(() => {
      document.getElementById('contact')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  async function submitContact() {
    if (contactSubmitting.value) return
    contactError.value = ''
    contactSuccess.value = false
    if (!contactForm.value.privacyAgreed) { contactError.value = '请先阅读并同意用户协议与隐私政策'; return }
    contactSubmitting.value = true
    try {
      await api.submitLandingContact({
        name: contactForm.value.name,
        email: contactForm.value.email,
        phone: contactForm.value.phone,
        company: contactForm.value.company,
        message: contactForm.value.message,
        source: csIntakeActive.value ? 'cs_intake' : 'home',
        privacy_agreed: true, privacy_version: '2026-06-20', privacy_url: '/privacy.html',
        cs_uid: csIntakeActive.value && csIntakeUid.value ? csIntakeUid.value : undefined,
        cs_t: csIntakeActive.value ? csIntakeToken.value : '',
      })
      contactSuccess.value = true
      contactForm.value = { name: '', email: '', phone: '', company: '', message: '', privacyAgreed: false }
    } catch (e) {
      contactError.value = (e as Error)?.message || '提交失败，请稍后重试'
    } finally {
      contactSubmitting.value = false
    }
  }

  watch(
    () => route.query,
    () => {
      applyCsIntakeFromRoute()
    },
  )

  /** 表单字段回写（模板拆出子组件后改为 emits 传回，行为不变） */
  function onContactFieldUpdate(field: ContactField, value: string | boolean) {
    (contactForm.value as unknown as Record<string, string | boolean>)[field] = value
  }

  return {
    contactForm,
    contactSubmitting,
    contactError,
    contactSuccess,
    csIntakeActive,
    csIntakeUid,
    csIntakeToken,
    submitContact,
    applyCsIntakeFromRoute,
    onContactFieldUpdate,
  }
}
