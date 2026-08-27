<template>
  <section class="delivery-commerce" aria-label="商务交付信息">
    <header>
      <div>
        <h3>报价·合同·收款·指派</h3>
        <p v-if="ticket.custom_delivery?.commerce_ready">商务条件已齐备，可进入客户安装。</p>
        <p v-else>{{ (ticket.custom_delivery?.commerce_blockers || []).join('、') || '商务资料待完善' }}</p>
      </div>
      <span :class="['commerce-state', ticket.custom_delivery?.commerce_ready ? 'is-ready' : 'is-pending']">
        {{ ticket.custom_delivery?.commerce_ready ? '已就绪' : '未就绪' }}
      </span>
    </header>
    <div class="delivery-commerce__grid">
      <label>
        <span>交付负责人</span>
        <input v-model.trim="form.owner_name" placeholder="姓名 / 工号" />
        <button type="button" :disabled="busy" @click="save('assignment')">保存指派</button>
      </label>
      <label>
        <span>报价单</span>
        <input v-model.trim="form.quote_no" placeholder="报价单号" />
        <input v-model.number="form.quote_amount" type="number" min="0" step="0.01" placeholder="金额" />
        <select v-model="form.quote_status">
          <option value="draft">草稿</option><option value="sent">已发送</option><option value="accepted">已确认</option><option value="waived">免报价</option>
        </select>
        <button type="button" :disabled="busy" @click="save('quote')">保存报价</button>
      </label>
      <label>
        <span>合同</span>
        <input v-model.trim="form.contract_no" placeholder="合同编号" />
        <input v-model.trim="form.contract_reference" placeholder="文件地址 / 签署凭证" />
        <select v-model="form.contract_status">
          <option value="draft">草稿</option><option value="sent">已发送</option><option value="signed">已签署</option><option value="waived">免合同</option>
        </select>
        <button type="button" :disabled="busy" @click="save('contract')">保存合同</button>
      </label>
      <label>
        <span>收款</span>
        <input v-model.number="form.payment_amount" type="number" min="0" step="0.01" placeholder="到账金额" />
        <input v-model.trim="form.payment_reference" placeholder="支付流水 / 线下凭证" />
        <select v-model="form.payment_status">
          <option value="unpaid">未收款</option><option value="partial">部分收款</option><option value="paid">已结清</option><option value="waived">免收款</option>
        </select>
        <button type="button" :disabled="busy" @click="save('payment')">保存收款</button>
      </label>
    </div>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { xcmaxAdminApi, type CustomDeliveryTicket } from '@/api/xcmaxAdmin'
import { appAlert } from '@/utils/appDialog'

type Section = 'assignment' | 'quote' | 'contract' | 'payment'
const props = defineProps<{ ticket: CustomDeliveryTicket }>()
const emit = defineEmits<{ updated: [ticket: CustomDeliveryTicket] }>()
const busy = ref(false)
const form = reactive({
  owner_name: '', quote_no: '', quote_amount: 0, quote_status: 'draft',
  contract_no: '', contract_reference: '', contract_status: 'draft',
  payment_amount: 0, payment_reference: '', payment_status: 'unpaid',
})

function hydrate(ticket: CustomDeliveryTicket) {
  const crm = ticket.custom_delivery?.crm || {}
  const assignment = crm.assignment || {}
  const quote = crm.quote || {}
  const contract = crm.contract || {}
  const payment = crm.payment || {}
  Object.assign(form, {
    owner_name: String(assignment.owner_name || ''),
    quote_no: String(quote.quote_no || ''),
    quote_amount: Number(quote.amount || 0),
    quote_status: String(quote.status || 'draft'),
    contract_no: String(contract.contract_no || ''),
    contract_reference: String(contract.reference || ''),
    contract_status: String(contract.status || 'draft'),
    payment_amount: Number(payment.amount_paid || 0),
    payment_reference: String(payment.reference || ''),
    payment_status: String(payment.status || 'unpaid'),
  })
}

async function save(section: Section) {
  const payload: Record<string, unknown> = { section }
  if (section === 'assignment') Object.assign(payload, { owner_name: form.owner_name })
  if (section === 'quote') Object.assign(payload, { status: form.quote_status, number: form.quote_no, amount: form.quote_amount })
  if (section === 'contract') Object.assign(payload, { status: form.contract_status, number: form.contract_no, reference: form.contract_reference })
  if (section === 'payment') Object.assign(payload, { status: form.payment_status, amount: form.payment_amount, reference: form.payment_reference })
  busy.value = true
  try {
    const updated = await xcmaxAdminApi.updateCustomDeliveryCrm(props.ticket.id, payload)
    hydrate(updated)
    emit('updated', updated)
  } catch (error) {
    await appAlert(error instanceof Error ? error.message : String(error), { title: '商务交付信息保存失败' })
  } finally {
    busy.value = false
  }
}

watch(() => props.ticket, hydrate, { immediate: true })
</script>

<style scoped>
.delivery-commerce { margin: 0 18px 15px; padding: 14px; border: 1px solid #d6e4f1; border-radius: 13px; background: #f7fbff; }
.delivery-commerce > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 11px; }
.delivery-commerce h3 { margin: 0; color: #315879; font-size: 12px; }
.delivery-commerce header p { margin: 4px 0 0; color: #72869a; font-size: 10px; }
.commerce-state { border-radius: 999px; padding: 4px 9px; font-size: 9px; font-weight: 800; }
.commerce-state.is-ready { background: #e4f6ee; color: #247b5c; }
.commerce-state.is-pending { background: #fff2df; color: #a96125; }
.delivery-commerce__grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 9px; }
.delivery-commerce__grid label { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid #dfe9f2; border-radius: 10px; background: #fff; }
.delivery-commerce__grid label > span { color: #466884; font-size: 10px; font-weight: 800; }
.delivery-commerce__grid input,.delivery-commerce__grid select { min-width: 0; border: 1px solid #d1dfec; border-radius: 7px; background: #fff; color: #294b68; padding: 7px 8px; font-size: 10px; }
.delivery-commerce__grid button { border: 0; border-radius: 7px; background: #2f7ed7; color: #fff; padding: 7px 8px; font-size: 10px; font-weight: 700; cursor: pointer; }
.delivery-commerce__grid button:disabled { opacity: .5; cursor: wait; }
@media (max-width: 1100px) { .delivery-commerce__grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 760px) { .delivery-commerce__grid { grid-template-columns: 1fr; } }
</style>
