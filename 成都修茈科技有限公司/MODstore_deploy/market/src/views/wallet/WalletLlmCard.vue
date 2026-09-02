<script setup lang="ts">
import { computed } from 'vue'
import LlmPricingAdminPanel from '../../components/llm/LlmPricingAdminPanel.vue'
import { LLM_OAI_COMPAT_BASE_URL_PROVIDERS } from '../../llmModels'
import { llmProviderIconImgSrc } from '../../llmIconUrls'
import type { WalletLlmApi } from '../../composables/useWalletLlm'

/**
 * WalletView 大模型 API 卡片（自 WalletView.vue 原样迁移）。
 * props.llm 为父级持有的大模型域 API 对象（属性均为稳定 ref / 纯函数），
 * 解构后与父级共享同一 ref 实例，状态常驻父级。
 */
const props = defineProps<{
  llm: WalletLlmApi
  isAdmin: boolean
}>()

const isAdmin = computed(() => props.isAdmin)

const {
  LLM_CATEGORY_ORDER,
  catalog,
  llmStatusList,
  llmCatalogLoading,
  llmErr,
  llmNote,
  selectedProvider,
  selectedModel,
  iconLoadFailed,
  byokKey,
  byokBaseUrl,
  byokSaving,
  byokBulkPaste,
  byokImportBusy,
  llmProviderFilter,
  currentProviderBlock,
  categoryLabel,
  modelOptionLabel,
  selectedModelPricingDetail,
  providerTilePriceHint,
  onPricingAdminSaved,
  modelsForCategory,
  byokConfiguredCount,
  byokImportDisabled,
  catalogSyncMeta,
  catalogProvidersSorted,
  providerTileMediaTags,
  formatCatalogFetchedAt,
  llmTileShowsImg,
  providerTileState,
  llmTileIconFailKey,
  providerTileTitle,
  llmByokCatalogDanger,
  llmInitials,
  refreshCatalog,
  selectProvider,
  schedulePersistPreferences,
  saveByok,
  importByokBulk,
  clearByok,
} = props.llm
</script>

<template>
  <div class="card llm-card">
    <header class="llm-card-head">
      <div class="llm-card-head__row">
        <span class="llm-card-head__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M12 3v2M5.6 5.6l1.4 1.4M3 12h2M5.6 18.4l1.4-1.4M12 21v-2M18.4 18.4l-1.4-1.4M21 12h-2M18.4 5.6l-1.4 1.4"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
            />
            <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.5" />
          </svg>
        </span>
        <div class="llm-card-head__text">
          <h3 class="llm-section-title">大模型 API</h3>
          <p class="llm-intro">
            模型目录由各厂商接口拉取并缓存约 10 分钟，可随时刷新；下方按「语言 / 视觉 / 生图 / 视频」分组。磁贴标注<strong>生图</strong>/<strong>生视频</strong>表示该厂商目录中含对应模型（OpenAI 兼容厂商亦支持标准生图接口）。默认模型写入账户；BYOK 经服务端加密保存。
          </p>
        </div>
      </div>
    </header>
    <div v-if="llmErr" class="flash flash-err">{{ llmErr }}</div>
    <div v-if="llmNote" class="flash flash-ok">{{ llmNote }}</div>
    <div class="llm-toolbar">
      <div class="llm-toolbar__main">
        <button
          type="button"
          class="btn llm-refresh-btn"
          :disabled="llmCatalogLoading"
          @click="refreshCatalog(true)"
        >
          <span class="llm-refresh-btn__icon" :class="{ 'llm-refresh-btn__icon--spin': llmCatalogLoading }" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M4.5 12a7.5 7.5 0 0 1 12.74-5.33M19.5 12a7.5 7.5 0 0 1-12.74 5.33M19.5 3v4.5H15M4.5 21v-4.5H9"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </span>
          <span>{{ llmCatalogLoading ? '加载中…' : '刷新模型列表' }}</span>
        </button>
        <div v-if="catalogSyncMeta" class="llm-sync-meta">
          <span class="llm-pill" :title="`ISO ${catalogSyncMeta.fetchedAt}`">
            <svg class="llm-pill__icon" viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5" />
              <path d="M12 7v5l3 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            最近拉取 {{ formatCatalogFetchedAt(catalogSyncMeta.fetchedAt) }}
          </span>
          <span class="llm-pill llm-pill--accent">缓存 TTL {{ catalogSyncMeta.ttlSec }}s</span>
        </div>
      </div>
      <p
        v-if="catalog && catalog.fernet_configured === false"
        class="llm-toolbar-hint"
        role="note"
      >
        <span class="llm-toolbar-hint__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.4" />
            <path d="M12 10v5M12 8h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </span>
        <span class="llm-toolbar-hint__text">
          保存 BYOK 需在服务端配置 Fernet 主密钥
          <code class="llm-code llm-code--hint">MODSTORE_LLM_MASTER_KEY</code>
        </span>
      </p>
    </div>
    <div v-if="catalog && !llmCatalogLoading" class="llm-media-filter" role="tablist" aria-label="厂商筛选">
      <button
        type="button"
        class="llm-media-filter__btn"
        :class="{ 'llm-media-filter__btn--on': llmProviderFilter === 'all' }"
        role="tab"
        :aria-selected="llmProviderFilter === 'all'"
        @click="llmProviderFilter = 'all'"
      >
        全部厂商
      </button>
      <button
        type="button"
        class="llm-media-filter__btn"
        :class="{ 'llm-media-filter__btn--on': llmProviderFilter === 'image' }"
        role="tab"
        :aria-selected="llmProviderFilter === 'image'"
        @click="llmProviderFilter = 'image'"
      >
        支持生图
      </button>
      <button
        type="button"
        class="llm-media-filter__btn"
        :class="{ 'llm-media-filter__btn--on': llmProviderFilter === 'video' }"
        role="tab"
        :aria-selected="llmProviderFilter === 'video'"
        @click="llmProviderFilter = 'video'"
      >
        支持生视频
      </button>
    </div>
    <div v-if="llmCatalogLoading && !catalog" class="loading">加载模型目录…</div>
    <template v-else-if="catalog">
      <div class="llm-grid" role="list">
        <button
          v-for="block in catalogProvidersSorted"
          :key="block.provider"
          type="button"
          class="llm-tile"
          :class="{
            'llm-tile--active': selectedProvider === block.provider,
            /* 仅密钥可用且目录拉取正常时「点亮」；认证失败、额度错误等与 inactive 同视为未点亮 */
            'llm-tile--keyed': providerTileState(block) === 'ok',
            'llm-tile--keywarn': providerTileState(block) === 'warn',
            'llm-tile--keydanger': providerTileState(block) === 'danger',
          }"
          role="listitem"
          :aria-pressed="selectedProvider === block.provider"
          :aria-label="`选择 ${block.label}，共 ${block.models.length} 个模型`"
          :title="providerTileTitle(block)"
          @click="selectProvider(block.provider)"
        >
          <span
            class="llm-tile__icon"
            :class="'llm-tile__icon--' + providerTileState(block)"
            aria-hidden="true"
          >
            <img
              v-if="llmTileShowsImg(block)"
              class="llm-tile__img"
              :src="llmProviderIconImgSrc(block.provider) || undefined"
              alt=""
              width="36"
              height="36"
              loading="lazy"
              crossorigin="anonymous"
              @error="iconLoadFailed[llmTileIconFailKey(block)] = true"
            />
            <span v-else class="llm-tile__fallback" :class="'llm-tile__fallback--' + providerTileState(block)">{{
              llmInitials(block.label)
            }}</span>
          </span>
          <span class="llm-tile__name">{{ block.label }}</span>
          <span class="llm-tile__count">{{ block.models.length }} 个模型</span>
          <span v-if="providerTileMediaTags(block).length" class="llm-tile__media-tags">
            <span
              v-for="tag in providerTileMediaTags(block)"
              :key="tag.kind"
              class="llm-tile__media-tag"
              :class="'llm-tile__media-tag--' + tag.kind"
            >{{ tag.label }}</span>
          </span>
          <span v-if="providerTilePriceHint(block)" class="llm-tile__price">{{ providerTilePriceHint(block) }}</span>
        </button>
      </div>
      <div v-if="currentProviderBlock" class="llm-model-panel">
        <div class="llm-model-panel__head">
          <span class="llm-model-panel__label">当前模型</span>
          <span v-if="selectedModel" class="llm-model-panel__hint">在列表中按分类快速定位</span>
        </div>
        <div class="llm-select-wrap">
          <select v-model="selectedModel" class="llm-select" @change="schedulePersistPreferences">
            <template v-for="cat in LLM_CATEGORY_ORDER" :key="cat">
              <optgroup v-if="modelsForCategory(cat).length" :label="categoryLabel(cat)">
                <option v-for="row in modelsForCategory(cat)" :key="row.id" :value="row.id">
                  {{ modelOptionLabel(row) }}
                </option>
              </optgroup>
            </template>
          </select>
        </div>
        <p v-if="selectedModelPricingDetail" class="llm-pricing-detail" role="note">
          {{ selectedModelPricingDetail }}
        </p>
        <p v-else-if="catalog?.billing_settings" class="llm-pricing-detail llm-pricing-detail--muted" role="note">
          平台代付按 token 扣钱包余额；BYOK 不扣费。服务费倍率 ×{{ Number(catalog.billing_settings.service_fee_multiplier || 1).toFixed(2) }}。
        </p>
        <p v-if="catalog?.gate_hints" class="llm-gate-hint">
          闸门：平台目录校验 {{ catalog.gate_hints.platform_catalog_gate ? '开' : '关' }} · BYOK 目录校验
          {{ catalog.gate_hints.byok_catalog_gate ? '开' : '关' }} · 平台须登记定价
          {{ catalog.gate_hints.platform_require_priced ? '开' : '关' }}。未登记定价时预授权可能上浮。
        </p>
      </div>
      <div v-else-if="catalogProvidersSorted.length" class="llm-empty-models">请选择供应商。</div>
      <div
        v-if="currentProviderBlock && !currentProviderBlock.models.length"
        class="llm-empty-models"
      >
        暂无可用模型：请配置 BYOK 的 API Key 后点击「刷新模型列表」。
      </div>

      <LlmPricingAdminPanel
        v-if="isAdmin && selectedProvider"
        :provider="selectedProvider"
        :provider-label="currentProviderBlock?.label || selectedProvider"
        @saved="onPricingAdminSaved"
      />

      <details class="llm-details">
        <summary class="llm-details__summary">
          <span class="llm-details__chevron" aria-hidden="true" />
          <span class="llm-details__summary-text">我的 API 密钥（BYOK）</span>
          <span
            v-if="byokConfiguredCount > 0"
            class="llm-byok-summary-badge"
          >{{ byokConfiguredCount }} 个已保存</span>
          <span
            v-else
            class="llm-byok-summary-badge llm-byok-summary-badge--muted"
          >未配置 BYOK</span>
        </summary>
        <p class="llm-byok-intro">
          密钥经服务端主密钥加密入库；接口仅返回掩码。可粘贴整段 .env 一键匹配厂商保存，无需逐行打开各厂商表单。
        </p>

        <div class="llm-byok-import">
          <label class="llm-byok-import__label" for="byok-bulk">一键导入</label>
          <textarea
            id="byok-bulk"
            v-model="byokBulkPaste"
            class="input llm-byok-bulk"
            rows="8"
            autocomplete="off"
            spellcheck="false"
            placeholder="粘贴 .env 片段或直接贴密钥，例如：&#10;OPENAI_API_KEY=sk-...&#10;OPENAI_BASE_URL=https://api.openai.com&#10;DEEPSEEK_API_KEY=sk-...&#10;moonshot=sk-...&#10;sk-...（无标签也可，将自动识别厂商）"
          />
          <p class="llm-byok-import__hint">
            支持环境变量名（与部署文档一致）、<code class="llm-code llm-code--hint">厂商id=密钥</code>，或直接粘贴裸密钥——会依次试拉各厂商 <code class="llm-code llm-code--hint">/models</code> 自动匹配归属。
          </p>
          <div class="llm-byok-import__actions">
            <button
              type="button"
              class="btn btn-primary-solid"
              :disabled="byokImportDisabled"
              @click="importByokBulk"
            >
              {{ byokImportBusy ? '保存中…' : '解析并保存' }}
            </button>
            <button type="button" class="btn btn-ghost" :disabled="byokImportBusy" @click="byokBulkPaste = ''">
              清空输入
            </button>
          </div>
        </div>

        <div class="llm-byok-list-head">各厂商状态</div>
        <ul class="llm-byok-list" role="list">
          <li v-for="st in llmStatusList" :key="st.provider" class="llm-byok-row" role="listitem">
            <div class="llm-byok-row__line">
              <div class="llm-byok-row__main">
                <span class="llm-byok-row__name">{{ st.label || st.provider }}</span>
                <span class="llm-byok-tags">
                  <span v-if="st.has_user_override" class="tag tag-user">BYOK</span>
                  <span v-if="st.has_platform_key" class="tag">平台密钥</span>
                  <span v-if="st.masked_key" class="llm-mask">{{ st.masked_key }}</span>
                  <span
                    v-else-if="!st.has_user_override && !st.has_platform_key"
                    class="llm-byok-row__dash"
                  >—</span>
                </span>
              </div>
              <button
                v-if="st.has_user_override"
                type="button"
                class="btn btn-ghost llm-byok-row__clear"
                :disabled="byokSaving === st.provider || byokImportBusy"
                @click="clearByok(st.provider)"
              >
                清除
              </button>
            </div>
            <p
              v-if="st.has_user_override && llmByokCatalogDanger(st.provider)"
              class="llm-byok-row__hint"
              role="note"
            >
              该厂商模型目录报红：请核对密钥与 Base URL，或先「清除」再重新保存。
            </p>
          </li>
        </ul>

        <details class="llm-details llm-details--nested">
          <summary class="llm-details__summary llm-details__summary--nested">
            <span class="llm-details__chevron" aria-hidden="true" />
            <span class="llm-details__summary-text">高级：逐厂商填写</span>
          </summary>
          <p class="llm-byok-intro llm-byok-intro--nested">适合只改单个 Key 或 Base URL 时使用。</p>
          <div v-for="st in llmStatusList" :key="'adv-' + st.provider" class="llm-byok-block">
            <div class="llm-byok-head">
              <strong>{{ st.label || st.provider }}</strong>
              <span class="llm-byok-tags">
                <span v-if="st.has_user_override" class="tag tag-user">BYOK</span>
                <span v-if="st.has_platform_key" class="tag">平台密钥</span>
                <span v-if="st.masked_key" class="llm-mask">{{ st.masked_key }}</span>
              </span>
            </div>
            <div v-if="LLM_OAI_COMPAT_BASE_URL_PROVIDERS.includes(st.provider)" class="llm-byok-fields">
              <input
                v-model="byokBaseUrl[st.provider]"
                class="input"
                type="text"
                autocomplete="off"
                placeholder="可选：自定义 Base URL（OpenAI 兼容）"
              />
            </div>
            <input
              v-model="byokKey[st.provider]"
              class="input"
              type="password"
              autocomplete="new-password"
              :placeholder="'粘贴 ' + st.provider + ' 的 API Key'"
            />
            <div class="llm-byok-actions">
              <button type="button" class="btn btn-primary-solid" :disabled="byokSaving === st.provider || byokImportBusy" @click="saveByok(st.provider)">
                {{ byokSaving === st.provider ? '保存中…' : '保存密钥' }}
              </button>
              <button type="button" class="btn btn-ghost" :disabled="byokSaving === st.provider || byokImportBusy" @click="clearByok(st.provider)">
                清除 BYOK
              </button>
            </div>
            <p
              v-if="st.has_user_override && llmByokCatalogDanger(st.provider)"
              class="llm-byok-block__hint"
              role="note"
            >
              模型目录报红时，可先「清除 BYOK」再粘贴正确密钥并保存。
            </p>
          </div>
        </details>
      </details>
    </template>
  </div>
</template>
