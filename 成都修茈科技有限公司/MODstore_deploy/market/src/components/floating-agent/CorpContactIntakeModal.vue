<template>
  <Teleport to="body">
    <Transition name="corp-intake-modal">
      <div
        v-if="contactIntakeModalOpen"
        class="corp-intake-modal"
        role="presentation"
        @click.self="closeModal"
      >
        <div
          class="corp-intake-modal__sheet"
          role="dialog"
          aria-modal="true"
          aria-labelledby="corp-intake-modal-title"
          @click.stop
        >
          <header class="corp-intake-modal__head">
            <div>
              <h3 id="corp-intake-modal-title" class="corp-intake-modal__title">AI 一键填表</h3>
              <p class="corp-intake-modal__desc">
                填写公司与行业后点「发送」，将自动写好页面上的需求问卷。
              </p>
            </div>
            <button
              type="button"
              class="corp-intake-modal__close"
              aria-label="关闭"
              :disabled="filling"
              @click="closeModal"
            >
              ×
            </button>
          </header>

          <form class="corp-intake-modal__form" @submit.prevent="submitMobileFill">
            <div class="form-field form-field--company-match">
              <label for="corp-intake-modal-company">公司名称</label>
              <div class="intake-company-wrap">
                <input
                  id="corp-intake-modal-company"
                  ref="companyInputRef"
                  v-model="company"
                  class="intake-company-input"
                  type="text"
                  maxlength="80"
                  autocomplete="off"
                  aria-autocomplete="list"
                  placeholder="例如：成都某某贸易有限公司"
                  :disabled="filling"
                  :aria-expanded="showSuggestions ? 'true' : 'false'"
                  @input="onCompanyInput"
                />
                <div
                  v-if="matchUiUnlocked && resultMode === 'warn' && resultText.trim()"
                  class="intake-company-result intake-company-result--warn"
                  role="status"
                >
                  <span class="intake-company-result__text">{{ resultText }}</span>
                </div>
                <ul
                  v-if="matchUiUnlocked && showSuggestions && suggestions.length"
                  class="intake-company-suggest"
                  role="listbox"
                >
                  <li v-for="(item, idx) in suggestions" :key="idx">
                    <button type="button" role="option" @click="selectSuggestion(item, company)">
                      {{ item.name }}
                    </button>
                  </li>
                </ul>
              </div>
              <p
                v-if="matchUiUnlocked && statusHint"
                class="intake-company-status"
                :class="{
                  'intake-company-status--ok': hintVariant === 'ok',
                  'intake-company-status--new': hintVariant === 'new',
                }"
                aria-live="polite"
              >
                {{ hint }}
              </p>
            </div>
            <div class="form-field">
              <label for="corp-intake-modal-system">行业 / 业务类型</label>
              <input
                id="corp-intake-modal-system"
                v-model="system"
                type="text"
                maxlength="120"
                placeholder="例如：贸易跟单、制造业、金蝶 ERP"
                :disabled="filling"
                @focus="onIndustryFocus"
                @input="onIndustryInput"
              />
            </div>
            <p v-if="fillError" class="corp-intake-modal__error" role="alert">{{ fillError }}</p>
            <button type="submit" class="corp-intake-modal__send" :disabled="filling || !canSubmit">
              {{ filling ? '正在预填…' : '发送' }}
            </button>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { runContactAiAssistFill } from '../../corp-butler/contactIntakeBridge'
import {
  closeContactIntakeModal,
  contactIntakeFillCompleted,
  contactIntakeModalOpen,
} from '../../corp-butler/useContactIntakeModal'
import { useContactCompanyMatch } from '../../corp-butler/useContactCompanyMatch'
import { useAgentStore } from '../../stores/agent'

const agentStore = useAgentStore()
const { isOpen } = storeToRefs(agentStore)

const company = ref('')
const system = ref('')
const filling = ref(false)
const fillError = ref('')
const companyInputRef = ref<HTMLInputElement | null>(null)

const {
  hint,
  hintVariant,
  resultMode,
  resultText,
  suggestions,
  showSuggestions,
  matchUiUnlocked,
  resetUi,
  onCompanyInput: matchOnCompanyInput,
  onIndustryFocus: matchOnIndustryFocus,
  onIndustryInput: matchOnIndustryInput,
  selectSuggestion,
  getCompanyForSubmit,
} = useContactCompanyMatch()

const statusHint = computed(() => (hint.value || '').trim())
const canSubmit = computed(() => company.value.trim().length > 0 && system.value.trim().length > 0)

let _msgId = 0
function nextId() {
  return `corp-intake-modal-${Date.now()}-${++_msgId}`
}

function lockBodyScroll(lock: boolean) {
  if (typeof document === 'undefined') return
  document.documentElement.style.overflow = lock ? 'hidden' : ''
  document.body.style.overflow = lock ? 'hidden' : ''
}

const getCompany = () => company.value

function onCompanyInput() {
  matchOnCompanyInput(company.value, getCompany)
}

function onIndustryFocus() {
  matchOnIndustryFocus(getCompany)
  syncSystemField()
}

function onIndustryInput() {
  matchOnIndustryInput()
  syncSystemField()
}

function syncSystemField() {
  const el = document.getElementById('intake-ai-system') as HTMLInputElement | null
  if (el) el.value = system.value
}

watch(system, () => syncSystemField())

function closeModal() {
  if (filling.value) return
  closeContactIntakeModal()
}

watch(contactIntakeModalOpen, (open) => {
  if (open) {
    fillError.value = ''
    resetUi()
    lockBodyScroll(true)
    void nextTick(() => companyInputRef.value?.focus())
  } else {
    lockBodyScroll(false)
  }
})

watch(isOpen, (open) => {
  if (!open) closeContactIntakeModal()
})

onBeforeUnmount(() => {
  lockBodyScroll(false)
})

async function submitMobileFill() {
  fillError.value = ''
  const c = getCompanyForSubmit(company.value)
  const s = system.value.trim()
  syncSystemField()
  if (!c || !s) {
    fillError.value = '请填写公司名称和行业 / 业务类型。'
    return
  }

  filling.value = true
  agentStore.addMessage({
    id: nextId(),
    role: 'user',
    content: `公司：${c}\n行业：${s}`,
    timestamp: Date.now(),
  })
  agentStore.addMessage({
    id: nextId(),
    role: 'assistant',
    content: '…',
    timestamp: Date.now(),
    isLoading: true,
  })
  agentStore.isLoading = true

  try {
    const result = await runContactAiAssistFill(c, s)
    if (result.ok) {
      contactIntakeFillCompleted.value = true
      closeContactIntakeModal()
      agentStore.updateLastMessage({
        isLoading: false,
        content:
          result.message ||
          '已预填下方问卷，请逐步核对；联系方式不会自动填写，请自行补全后提交。',
      })
    } else {
      fillError.value = result.message
      agentStore.updateLastMessage({ isLoading: false, content: result.message })
    }
  } catch {
    const err = '网络异常，请稍后重试。'
    fillError.value = err
    agentStore.updateLastMessage({ isLoading: false, content: err })
  } finally {
    filling.value = false
    agentStore.isLoading = false
  }
}
</script>

<style>
.corp-intake-modal {
  position: fixed;
  inset: 0;
  z-index: 26000;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 0;
  background: rgba(15, 23, 42, 0.52);
  backdrop-filter: blur(4px);
  pointer-events: auto;
}

.corp-intake-modal__sheet {
  width: 100%;
  max-width: 520px;
  max-height: min(88dvh, 640px);
  overflow: auto;
  padding: 18px 18px calc(18px + env(safe-area-inset-bottom, 0px));
  border-radius: 20px 20px 0 0;
  background: #fff;
  box-shadow: 0 -12px 40px rgba(15, 23, 42, 0.18);
  -webkit-overflow-scrolling: touch;
}

.corp-intake-modal__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.corp-intake-modal__title {
  margin: 0 0 6px;
  font-size: 1.12rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: rgba(15, 23, 42, 0.95);
}

.corp-intake-modal__desc {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.5;
  color: rgba(51, 65, 85, 0.88);
}

.corp-intake-modal__close {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: rgba(241, 245, 249, 1);
  color: rgba(51, 65, 85, 0.9);
  font-size: 1.35rem;
  line-height: 1;
  cursor: pointer;
}

.corp-intake-modal__close:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.corp-intake-modal__form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.corp-intake-modal__error {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.45;
  color: #dc2626;
  font-weight: 600;
}

.corp-intake-modal__send {
  width: 100%;
  margin-top: 4px;
  padding: 14px 16px;
  border: 0;
  border-radius: 14px;
  font-size: 1rem;
  font-weight: 800;
  color: #fff;
  cursor: pointer;
  background: linear-gradient(135deg, #0b63f6, #0aa8ff);
}

.corp-intake-modal__send:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.corp-intake-modal-enter-active,
.corp-intake-modal-leave-active {
  transition: opacity 0.22s ease;
}

.corp-intake-modal-enter-active .corp-intake-modal__sheet,
.corp-intake-modal-leave-active .corp-intake-modal__sheet {
  transition: transform 0.28s cubic-bezier(0.34, 1.2, 0.64, 1);
}

.corp-intake-modal-enter-from,
.corp-intake-modal-leave-to {
  opacity: 0;
}

.corp-intake-modal-enter-from .corp-intake-modal__sheet,
.corp-intake-modal-leave-to .corp-intake-modal__sheet {
  transform: translateY(100%);
}
</style>
