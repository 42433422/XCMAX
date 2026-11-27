<script setup lang="ts">
import { MODEL_PAYMENT_SECTIONS } from '@/constants/modelServiceNavigation'
import type { ModelPaymentCtx } from './assemble'

const props = defineProps<{ tm: ModelPaymentCtx }>()

const { membershipPlans, openMarketPlan } = props.tm
</script>

<template>
  <details class="mp-fold">
    <summary class="mp-fold-title">{{ MODEL_PAYMENT_SECTIONS.membership.label }}</summary>
    <article v-for="plan in membershipPlans" :key="plan.id" class="mp-plan-row">
      <div>
        <h3>{{ plan.title }} <small v-if="plan.badge">{{ plan.badge }}</small></h3>
        <p>{{ plan.description }}</p>
        <ul>
          <li v-for="feature in plan.features" :key="feature">{{ feature }}</li>
        </ul>
      </div>
      <div class="mp-plan-action">
        <strong>¥{{ plan.price }}</strong>
        <button class="mp-hero-btn" type="button" :aria-label="`在市场查看 ${plan.title}`" @click="openMarketPlan(plan)">去市场</button>
      </div>
    </article>
  </details>
</template>

<style scoped src="./model-payment.css"></style>
