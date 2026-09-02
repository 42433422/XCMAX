<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./developer-tokens/，样式在 ./developer-tokens/developer-tokens.css。
const _props = withDefaults(
  defineProps<{
    /** 账户中心嵌入：精简列表，桌面加密导出见开发者门户 */
    embedded?: boolean
  }>(),
  { embedded: false },
)
import { RouterLink } from 'vue-router'
// formatTime/formatExpiresShort/scopesSummary/statusOf/SCOPE_HINTS 经顶层 import 保留在 vm 与模板访问面上。
import {
  formatExpiresShort,
  formatTime,
  SCOPE_HINTS,
  scopesSummary,
  statusOf,
} from './developer-tokens/developerTokenTypes'
import { useDeveloperTokens } from './developer-tokens/useDeveloperTokens'

const {
  tokens,
  activeTokens,
  loading,
  errMsg,
  showDialog,
  submitBusy,
  draft,
  justCreated,
  copied,
  desktopPubB64,
  exportPassword,
  exportSelected,
  exportBusy,
  exportAuditOpen,
  exportAudit,
  exportAuditLoading,
  onExportCheck,
  selectAllActiveForExport,
  runExportBundle,
  toggleAudit,
  refresh,
  openCreate,
  addScope,
  closeCreate,
  submitCreate,
  copyJustCreated,
  dismissJustCreated,
  revoke,
  justCreatedHasScope,
} = useDeveloperTokens()
</script>

<template>
  <div class="dt dt--dark" :class="{ 'dt--embedded': embedded }">
    <header class="dt__head" :class="{ 'dt__head--embedded': embedded }">
      <div v-if="!embedded">
        <h2 class="dt__title">Personal Access Token</h2>
        <p class="dt__hint">
          Bearer Token 调用 API；创建后明文仅显示一次。
          <a href="/dev-docs/" target="_blank" rel="noreferrer">文档</a>
        </p>
      </div>
      <p v-else class="dt__hint dt__hint--inline">
        创建后明文仅显示一次。
        <a href="/dev-docs/" target="_blank" rel="noreferrer">API 文档</a>
      </p>
      <button class="dt__btn dt__btn--primary" type="button" @click="openCreate">创建 Token</button>
    </header>

    <p v-if="errMsg" class="dt__err">{{ errMsg }}</p>

    <div v-if="loading" class="dt__placeholder">加载中…</div>
    <div v-else-if="!tokens.length" class="dt__placeholder">
      {{ embedded ? '暂无 Token，点击「创建 Token」生成密钥。' : '还没有 Token，点击「创建新 Token」开始接入第三方应用。' }}
    </div>
    <ul v-else-if="embedded" class="dt__list">
      <li v-for="t in tokens" :key="t.id" class="dt__list-item" :class="{ 'dt__list-item--inactive': !t.is_active }">
        <div class="dt__list-body">
          <div class="dt__list-top">
            <span class="dt__list-name">{{ t.name || '—' }}</span>
            <span class="dt__status" :class="statusOf(t).cls">{{ statusOf(t).text }}</span>
          </div>
          <p class="dt__list-meta">
            <code>{{ t.prefix }}…</code>
            <span class="dt__list-sep">·</span>
            {{ scopesSummary(t.scopes) }}
            <span class="dt__list-sep">·</span>
            {{ formatExpiresShort(t.expires_at) }}
          </p>
        </div>
        <button v-if="t.is_active" class="dt__btn dt__btn--danger dt__btn--sm" type="button" @click="revoke(t)">吊销</button>
      </li>
    </ul>
    <table v-else class="dt__table">
      <thead>
        <tr>
          <th>名称</th>
          <th>前缀</th>
          <th>权限范围</th>
          <th>创建时间</th>
          <th>最近使用</th>
          <th>过期</th>
          <th>状态</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in tokens" :key="t.id" :class="{ 'dt__row--inactive': !t.is_active }">
          <td>{{ t.name || '—' }}</td>
          <td>
            <code>{{ t.prefix }}…</code>
          </td>
          <td>
            <span v-if="!t.scopes.length" class="dt__scope-empty">未配置</span>
            <span v-for="s in t.scopes" :key="s" class="dt__scope">{{ s }}</span>
          </td>
          <td>{{ formatTime(t.created_at) }}</td>
          <td>{{ formatTime(t.last_used_at) }}</td>
          <td>{{ t.expires_at ? formatTime(t.expires_at) : '永不' }}</td>
          <td>
            <span class="dt__status" :class="statusOf(t).cls">{{ statusOf(t).text }}</span>
          </td>
          <td>
            <button v-if="t.is_active" class="dt__btn dt__btn--danger" type="button" @click="revoke(t)">吊销</button>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-if="embedded && tokens.length" class="dt__portal-link">
      批量加密下发到桌面？
      <RouterLink :to="{ name: 'developer-portal' }">开发者门户 → API Token</RouterLink>
    </p>

    <section v-if="!embedded" class="dt-desk">
      <h3 class="dt-desk__title">传到桌面（加密包）</h3>
      <p class="dt-desk__hint">
        粘贴桌面公钥并确认密码后下发加密包。<a href="/dev-docs/developer/08-key-export-desktop.md" target="_blank" rel="noreferrer">说明</a>
      </p>
      <label class="dt-field">
        <span>桌面端公钥（base64 DER SPKI）</span>
        <textarea v-model="desktopPubB64" class="dt-desk__ta" rows="3" placeholder="MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE..." />
      </label>
      <label class="dt-field">
        <span>当前登录密码（二次确认）</span>
        <input v-model="exportPassword" type="password" autocomplete="current-password" />
      </label>
      <div v-if="activeTokens.length" class="dt-desk__pick">
        <div class="dt-desk__pick-head">
          <span>要下发的 Token（多选）</span>
          <button type="button" class="dt__btn" @click="selectAllActiveForExport">全选可用</button>
        </div>
        <label v-for="t in activeTokens" :key="'ex-' + t.id" class="dt-desk__cb">
          <input type="checkbox" :checked="exportSelected.includes(t.id)" @change="onExportCheck(t.id, $event)" />
          <span
            >{{ t.name }} <code>{{ t.prefix }}…</code></span
          >
        </label>
      </div>
      <p v-else class="dt__placeholder">没有可用 Token，请先创建。</p>
      <div class="dt-desk__actions">
        <button class="dt__btn dt__btn--primary" type="button" :disabled="exportBusy || !activeTokens.length" @click="runExportBundle">
          {{ exportBusy ? '生成中…' : '生成并下载 .msk1 加密包' }}
        </button>
        <button type="button" class="dt__btn" @click="toggleAudit">{{ exportAuditOpen ? '收起' : '查看' }}导出审计</button>
      </div>
      <div v-if="exportAuditOpen" class="dt-desk__audit">
        <p v-if="exportAuditLoading">加载审计…</p>
        <table v-else-if="exportAudit.length" class="dt__table dt__table--compact">
          <thead>
            <tr>
              <th>时间</th>
              <th>动作</th>
              <th>成功</th>
              <th>详情</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ev in exportAudit" :key="ev.id">
              <td>{{ formatTime(ev.created_at) }}</td>
              <td>{{ ev.action }}</td>
              <td>{{ ev.success ? '是' : '否' }}</td>
              <td>{{ ev.detail }}</td>
              <td>{{ ev.client_ip || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="dt__placeholder">暂无记录</p>
      </div>
    </section>

    <transition name="dt-fade">
      <div v-if="showDialog" class="dt-modal" @click.self="closeCreate">
        <div class="dt-modal__card">
          <header class="dt-modal__head">
            <h3>创建新 Token</h3>
            <button class="dt__btn" type="button" :disabled="submitBusy" @click="closeCreate">关闭</button>
          </header>
          <div class="dt-modal__body">
            <label class="dt-field">
              <span>名称</span>
              <input v-model="draft.name" type="text" placeholder="例如：本地脚本 / CI Pipeline" />
            </label>
            <label class="dt-field">
              <span>权限范围（逗号分隔）</span>
              <input v-model="draft.scopesCsv" type="text" placeholder="mod:sync,catalog:read" />
              <small class="dt-field__hint">
                本地 Mod 同步请至少包含 <code>mod:sync</code>；读取 Catalog 建议同时包含 <code>catalog:read</code>。
                <br />
                可选：
                <button v-for="s in SCOPE_HINTS" :key="s" type="button" class="dt-field__chip" @click="addScope(s)">
                  {{ s }}
                </button>
              </small>
            </label>
            <label class="dt-field">
              <span>有效期（天，留空 = 永不过期）</span>
              <input v-model="draft.expiresDays" type="number" min="1" max="365" placeholder="90" />
            </label>
          </div>
          <footer class="dt-modal__foot">
            <button class="dt__btn" type="button" :disabled="submitBusy" @click="closeCreate">取消</button>
            <button class="dt__btn dt__btn--primary" type="button" :disabled="submitBusy" @click="submitCreate">
              {{ submitBusy ? '提交中…' : '生成 Token' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>

    <transition name="dt-fade">
      <div v-if="justCreated" class="dt-modal">
        <div class="dt-modal__card dt-modal__card--ok">
          <header class="dt-modal__head">
            <h3>Token 已生成 — 仅显示一次</h3>
          </header>
          <div class="dt-modal__body">
            <p class="dt-just__warn">
              这是 <strong>{{ justCreated.meta.name }}</strong> 的明文 Token。请立即复制并妥善保管，关闭后将无法再次查看。
            </p>
            <pre class="dt-just__token">{{ justCreated.token }}</pre>
            <p class="dt-just__sample">使用示例：</p>
            <pre
              v-if="justCreatedHasScope('mod:sync')"
              class="dt-just__sample-code"
            ><code>curl -X POST https://xiu-ci.com/v1/mod-sync/push \
  -H "Authorization: Bearer {{ justCreated.token }}" \
  -H "Content-Type: application/json" \
  -d '{"mod_ids":["example-mod"]}'</code></pre>
            <pre v-else class="dt-just__sample-code"><code>curl https://&lt;your-domain&gt;/api/employees/ \
  -H "Authorization: Bearer {{ justCreated.token }}"</code></pre>
          </div>
          <footer class="dt-modal__foot">
            <button class="dt__btn" type="button" @click="copyJustCreated">
              {{ copied ? '已复制 ✓' : '复制到剪贴板' }}
            </button>
            <button class="dt__btn dt__btn--primary" type="button" @click="dismissJustCreated">我已保存</button>
          </footer>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped src="./developer-tokens/developer-tokens.css"></style>
