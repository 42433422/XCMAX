<template>
  <div class="plans-page">
    <div class="page-header">
      <h1 class="page-title">AI 员工套餐</h1>
      <p class="page-desc">选择适合你的 AI 员工套餐，让智能员工为你工作</p>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else class="plans-grid">
      <div v-for="plan in plans" :key="plan.id" class="plan-card">
        <div class="plan-header">
          <h2 class="plan-name">{{ plan.name }}</h2>
          <div class="plan-price">
            <span class="price-symbol">¥</span>
            <span class="price-value">{{ plan.price.toFixed(2) }}</span>
          </div>
          <p class="plan-desc">{{ plan.description }}</p>
        </div>

        <ul class="plan-features">
          <li v-for="(feature, i) in plan.features" :key="i">{{ feature }}</li>
        </ul>

        <button class="btn btn-primary" :disabled="checkingOut" @click="handleBuy(plan)">
          <span v-if="checkingOut">处理中...</span>
          <span v-else>立即购买</span>
        </button>
      </div>
    </div>

    <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const plans = ref([])
const loading = ref(true)
const checkingOut = ref(false)
const errorMsg = ref('')

onMounted(async () => {
  try {
    const res = await api.paymentPlans()
    plans.value = res.plans || []
    
    // 如果API没有返回套餐数据，使用默认套餐
    if (plans.value.length === 0) {
      plans.value = [
        {
          id: 1,
          name: '体验版',
          price: 10,
          description: '适合个人用户体验AI员工',
          features: [
            '基础AI员工能力',
            '每月100次AI任务执行',
            '基本工作流程',
            '邮件支持'
          ]
        },
        {
          id: 2,
          name: '普通版',
          price: 99,
          description: '适合小型企业日常运营',
          features: [
            '高级AI员工能力',
            '每月1000次AI任务执行',
            '复杂工作流程',
            '优先邮件支持',
            '数据导出功能'
          ]
        },
        {
          id: 3,
          name: '高级版',
          price: 199,
          description: '适合中型企业智能转型',
          features: [
            '专业AI员工能力',
            '无限AI任务执行',
            '高级工作流程',
            '24小时在线支持',
            '高级数据导出',
            'API接口访问'
          ]
        }
      ]
    }
  } catch (e) {
    errorMsg.value = '加载套餐失败: ' + e.message
    // 出错时使用默认套餐
    plans.value = [
      {
        id: 1,
        name: '体验版',
        price: 10,
        description: '适合个人用户体验AI员工',
        features: [
          '基础AI员工能力',
          '每月100次AI任务执行',
          '基本工作流程',
          '邮件支持'
        ]
      },
      {
        id: 2,
        name: '普通版',
        price: 99,
        description: '适合小型企业日常运营',
        features: [
          '高级AI员工能力',
          '每月1000次AI任务执行',
          '复杂工作流程',
          '优先邮件支持',
          '数据导出功能'
        ]
      },
      {
        id: 3,
        name: '高级版',
        price: 199,
        description: '适合中型企业智能转型',
        features: [
          '专业AI员工能力',
          '无限AI任务执行',
          '高级工作流程',
          '24小时在线支持',
          '高级数据导出',
          'API接口访问'
        ]
      }
    ]
  } finally {
    loading.value = false
  }
})

async function handleBuy(plan) {
  if (!localStorage.getItem('modstore_token')) {
    router.push({ name: 'login', query: { redirect: '/plans' } })
    return
  }

  checkingOut.value = true
  errorMsg.value = ''

  try {
    const res = await api.paymentCheckout({
      plan_id: plan.id,
    })

    if (!res.ok) {
      errorMsg.value = res.message || '下单失败'
      return
    }

    if (res.type === 'page' || res.type === 'wap') {
      window.location.href = res.redirect_url
    } else if (res.type === 'precreate') {
      router.push({ name: 'checkout', params: { orderId: res.order_id } })
    } else {
      errorMsg.value = '未知的支付类型'
    }
  } catch (e) {
    errorMsg.value = '下单失败: ' + e.message
  } finally {
    checkingOut.value = false
  }
}
</script>

<style scoped>
.plans-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  padding: 80px 24px;
}

.page-header {
  text-align: center;
  margin-bottom: 48px;
}

.page-title {
  font-size: clamp(28px, 4vw, 36px);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.page-desc {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

.loading {
  text-align: center;
  padding: 48px;
  color: rgba(255, 255, 255, 0.5);
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
  max-width: 1000px;
  margin: 0 auto;
}

.plan-card {
  display: flex;
  flex-direction: column;
  padding: 32px 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.02);
  transition: all 0.2s ease-out;
}

.plan-card:hover {
  border-color: rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.04);
}

.plan-header {
  margin-bottom: 24px;
}

.plan-name {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 12px;
}

.plan-price {
  margin-bottom: 8px;
}

.price-symbol {
  font-size: 16px;
  vertical-align: top;
}

.price-value {
  font-size: 32px;
  font-weight: 700;
}

.plan-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

.plan-features {
  list-style: none;
  margin: 0 0 24px;
  padding: 0;
  flex: 1;
}

.plan-features li {
  padding: 8px 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.06);
}

.plan-features li:last-child {
  border-bottom: none;
}

.btn {
  width: 100%;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease-out;
  border: none;
}

.btn-primary {
  background: #ffffff;
  color: #0a0a0a;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-msg {
  max-width: 500px;
  margin: 24px auto 0;
  padding: 12px 16px;
  background: rgba(255, 80, 80, 0.1);
  border: 0.5px solid rgba(255, 80, 80, 0.2);
  border-radius: 8px;
  color: #ff6b6b;
  text-align: center;
  font-size: 13px;
}

@media (max-width: 768px) {
  .plans-page {
    padding: 64px 16px;
  }

  .plans-grid {
    grid-template-columns: 1fr;
  }
}
</style>
