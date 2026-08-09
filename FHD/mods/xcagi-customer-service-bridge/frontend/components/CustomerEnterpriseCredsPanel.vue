<template>
  <section class="cs-enterprise-creds">
    <div class="cs-enterprise-creds__head">
      <span class="cs-stage-badge">企业专属账号</span>
      <span v-if="enterpriseCreds.is_enterprise" class="cs-tag cs-tag--ok">已开通</span>
    </div>
    <p class="muted cs-enterprise-creds__hint">
      用于修茈市场 (xiu-ci.com) 与企业版 XCAGI 宿主登录；密码在生成或重置后回显并写入客服档案。
    </p>
    <p v-if="enterpriseCreds.loading" class="muted">加载账号信息…</p>
    <template v-else>
      <dl class="cs-enterprise-creds__dl">
        <dt>登录账号</dt>
        <dd>
          <code class="cs-enterprise-creds__code">{{ enterpriseCreds.username || '—' }}</code>
          <button
            v-if="enterpriseCreds.username"
            type="button"
            class="btn btn-xs"
            @click="$emit('copy', 'username')"
          >
            复制
          </button>
        </dd>
        <template v-if="enterpriseCreds.email">
          <dt>邮箱</dt>
          <dd><code class="cs-enterprise-creds__code">{{ enterpriseCreds.email }}</code></dd>
        </template>
        <dt>登录密码</dt>
        <dd>
          <code v-if="enterpriseCreds.password" class="cs-enterprise-creds__code">{{ enterpriseCreds.password }}</code>
          <span v-else class="muted">未记录明文（可点击下方生成临时密码）</span>
          <button
            v-if="enterpriseCreds.password"
            type="button"
            class="btn btn-xs"
            @click="$emit('copy', 'password')"
          >
            复制
          </button>
        </dd>
        <template v-if="enterpriseCreds.issued_at">
          <dt>签发时间</dt>
          <dd class="muted">{{ formatPassivePollTime(enterpriseCreds.issued_at) }}</dd>
        </template>
      </dl>
      <p v-if="enterpriseCreds.error" class="form-error">{{ enterpriseCreds.error }}</p>
      <div class="cs-enterprise-creds__actions">
        <button
          type="button"
          class="btn btn-xs btn-accent"
          :disabled="enterpriseCreds.issuing || !selectedUserId"
          @click="$emit('issue')"
        >
          {{
            enterpriseCreds.issuing
              ? '生成中…'
              : (enterpriseCreds.password_recorded ? '重新生成临时密码' : '生成临时密码')
          }}
        </button>
        <button
          type="button"
          class="btn btn-xs"
          :disabled="enterpriseCreds.loading"
          @click="$emit('load')"
        >
          刷新
        </button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { formatPassivePollTime } from '../composables/useCustomerServiceFormat'

export type EnterpriseCredsState = {
  loading: boolean
  issuing: boolean
  username: string
  email: string
  password: string
  password_recorded: boolean
  issued_at: string
  is_enterprise: boolean
  error: string
}

defineProps<{
  enterpriseCreds: EnterpriseCredsState
  selectedUserId: number | null
}>()

defineEmits<{
  (e: 'copy', kind: 'username' | 'password'): void
  (e: 'issue'): void
  (e: 'load'): void
}>()
</script>

<style scoped>
.cs-enterprise-creds {
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cs-enterprise-creds__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-enterprise-creds__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
}
.cs-enterprise-creds__dl {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}
.cs-enterprise-creds__dl dt {
  margin: 0;
  color: #8b949e;
}
.cs-enterprise-creds__dl dd {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-enterprise-creds__code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.25);
}
.cs-enterprise-creds__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.cs-stage-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: #eff6ff; color: #4a6cf7; font-weight: 500;
}
.cs-tag { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: #f3f4f6; color: #6b7280; }
.cs-tag--ok { background: #ecfdf5; color: #047857; }
.muted { color: #94a3b8; }
.form-error { color: #b91c1c; font-size: 12px; margin: 0; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: #4a6cf7; border-color: #4a6cf7; color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }
</style>