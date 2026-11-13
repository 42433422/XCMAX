import { reactive } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { get, post } from '@/api'
import { appAlert } from '@/utils/appDialog'

/** 该 composable 所需读取/写入的 pipeline 字段（其余字段由父组件持有）。 */
type PipelineCreds = {
  enterprise_login_username: string
  username: string
  enterprise_login_password: string
  enterprise_credentials_issued_at: string
  enterprise_auto_provisioned_at: string
}

/**
 * 企业专属账号凭据状态簇：加载/签发临时密码/复制。
 * 通过注入的 customerPipeline（reactive）读写客户档案字段，行为与原来地定义一致。
 */
export function useEnterpriseCredentials(
  customerPipeline: PipelineCreds,
  selectedUserId: Ref<number | null>,
  selectedEnterpriseUser: ComputedRef<{ username?: string; is_enterprise?: boolean } | null>,
) {
  const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

  const enterpriseCreds = reactive({
    loading: false,
    issuing: false,
    username: '',
    email: '',
    password: '',
    password_recorded: false,
    issued_at: '',
    is_enterprise: false,
    error: '',
  })

  function syncEnterpriseCredsFromPipeline() {
    enterpriseCreds.username = String(
      customerPipeline.enterprise_login_username
        || customerPipeline.username
        || selectedEnterpriseUser.value?.username
        || '',
    ).trim()
    enterpriseCreds.password = String(customerPipeline.enterprise_login_password || '').trim()
    enterpriseCreds.password_recorded = Boolean(enterpriseCreds.password)
    enterpriseCreds.issued_at = String(customerPipeline.enterprise_credentials_issued_at || '').trim()
    enterpriseCreds.is_enterprise = Boolean(
      customerPipeline.enterprise_auto_provisioned_at
        || selectedEnterpriseUser.value?.is_enterprise,
    )
  }

  function applyEnterpriseCredsPayload(data: Record<string, unknown> | null | undefined) {
    if (!data) return
    const username = String(data.username || '').trim()
    const password = String(data.password || '').trim()
    const issuedAt = String(data.issued_at || '').trim()
    if (username) {
      customerPipeline.enterprise_login_username = username
      customerPipeline.username = username
    }
    if (password) {
      customerPipeline.enterprise_login_password = password
    }
    if (issuedAt) {
      customerPipeline.enterprise_credentials_issued_at = issuedAt
    }
    if (data.is_enterprise) {
      customerPipeline.enterprise_auto_provisioned_at = String(
        customerPipeline.enterprise_auto_provisioned_at || issuedAt || new Date().toISOString(),
      )
    }
    enterpriseCreds.email = String(data.email || '').trim()
    enterpriseCreds.password_recorded = Boolean(data.password_recorded ?? password)
    enterpriseCreds.is_enterprise = Boolean(data.is_enterprise ?? enterpriseCreds.is_enterprise)
    enterpriseCreds.error = String(data.market_fetch_error || '').trim()
    syncEnterpriseCredsFromPipeline()
  }

  async function loadEnterpriseCredentials() {
    if (!selectedUserId.value) return
    enterpriseCreds.loading = true
    enterpriseCreds.error = ''
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/enterprise-credentials`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const body = res as { success?: boolean; error?: string; data?: Record<string, unknown> }
      if (body.success === false) {
        throw new Error(body.error || '加载企业账号失败')
      }
      applyEnterpriseCredsPayload(body.data)
    } catch (e) {
      enterpriseCreds.error = e instanceof Error ? e.message : String(e)
    } finally {
      enterpriseCreds.loading = false
    }
  }

  async function issueEnterpriseCredentials() {
    if (!selectedUserId.value) return
    if (
      enterpriseCreds.password_recorded
      && !window.confirm('将生成新密码并覆盖修茈市场 / 企业版登录密码，是否继续？')
    ) {
      return
    }
    enterpriseCreds.issuing = true
    enterpriseCreds.error = ''
    try {
      const res = await post(`${CS_BRIDGE}/user-cs/enterprise-credentials/issue`, {
        market_user_id: selectedUserId.value,
        username: selectedEnterpriseUser.value?.username || '',
      })
      const body = res as { success?: boolean; error?: string; data?: Record<string, unknown> }
      if (body.success === false) {
        throw new Error(body.error || '生成密码失败')
      }
      applyEnterpriseCredsPayload(body.data)
      await appAlert('已生成临时密码，请复制后发给客户（仅在此处与档案中保留明文）')
    } catch (e) {
      enterpriseCreds.error = e instanceof Error ? e.message : String(e)
      await appAlert(enterpriseCreds.error)
    } finally {
      enterpriseCreds.issuing = false
    }
  }

  async function copyEnterpriseCredential(kind: 'username' | 'password') {
    const text = kind === 'username' ? enterpriseCreds.username : enterpriseCreds.password
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      await appAlert(kind === 'username' ? '登录账号已复制' : '登录密码已复制')
    } catch {
      await appAlert('复制失败，请手动选择复制')
    }
  }

  return {
    enterpriseCreds,
    syncEnterpriseCredsFromPipeline,
    applyEnterpriseCredsPayload,
    loadEnterpriseCredentials,
    issueEnterpriseCredentials,
    copyEnterpriseCredential,
  }
}