<template>
  <div class="landing-page">
    <!-- Landing Nav -->
    <header class="landing-nav">
      <div class="container">
        <div class="landing-nav-inner">
          <router-link to="/" class="landing-logo">XC AGI</router-link>
          <nav class="landing-nav-links">
            <router-link :to="{ name: 'ai-store' }" class="nav-ghost">AI 员工商店</router-link>
            <router-link :to="workbenchLink" class="nav-ghost">进入工作台</router-link>
            <router-link v-if="!isLoggedIn" to="/register" class="nav-primary">免费注册</router-link>
          </nav>
        </div>
      </div>
    </header>

    <!-- Hero -->
    <section class="hero">
      <div class="hero-gradient-bg"></div>
      <div class="container">
        <div class="hero-content">
          <p class="hero-eyebrow">AI 驱动 · 智能未来</p>
          <h1 class="hero-heading">
            <span class="gradient-text">不知疲倦、永不离线</span><br />
            可无限复制的智能员工团队
          </h1>
          <p class="hero-description">
            让 AI 承担重复性工作，您专注创造性价值。
            数据存储、流程规则、自动化处理——用 MOD 把各种组件组合在一起，审批、进销存、工单、报表，什么都能做。
          </p>
          <div class="hero-actions">
            <router-link to="/register" class="btn btn-white">开始使用</router-link>
            <router-link :to="workbenchLink" class="btn btn-ghost">进入工作台</router-link>
          </div>
        </div>
      </div>
    </section>

    <!-- Features -->
    <section class="section">
      <div class="container">
        <div class="features-grid">
          <div class="feature-item">
            <h3 class="feature-title">智能识别</h3>
            <p class="feature-desc">AI 快速识别 Excel 出货单、收货单等单据，自动提取关键信息，准确率高</p>
          </div>
          <div class="feature-item">
            <h3 class="feature-title">自动化处理</h3>
            <p class="feature-desc">自动填充数据、生成标签、同步信息，减少人工操作环节</p>
          </div>
          <div class="feature-item">
            <h3 class="feature-title">7×24 工作</h3>
            <p class="feature-desc">不知疲倦的 AI 员工，随时响应，无需休息，不离职不请假</p>
          </div>
          <div class="feature-item">
            <h3 class="feature-title">多场景适配</h3>
            <p class="feature-desc">支持制造业、贸易、物流等多种行业场景，灵活定制</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Use Case Video -->
    <section class="section section--border-top">
      <div class="container">
        <div class="section-header">
          <h2 class="section-title">智能单据处理</h2>
          <p class="section-description">
            告别繁琐的手工录入，AI 员工帮您自动识别 Excel 单据，智能提取关键数据，一键生成标签并打印
          </p>
        </div>

        <div class="video-wrapper">
          <video class="demo-video" autoplay muted loop playsinline>
            <source :src="heroVideoUrl" type="video/mp4" />
          </video>
        </div>

        <div class="use-case-stats">
          <div class="stat-card">
            <span class="stat-value gradient-text">95%+</span>
            <span class="stat-label">识别准确率</span>
          </div>
          <div class="stat-card">
            <span class="stat-value gradient-text">80%</span>
            <span class="stat-label">效率提升</span>
          </div>
          <div class="stat-card">
            <span class="stat-value gradient-text">24/7</span>
            <span class="stat-label">不间断服务</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Capabilities -->
    <section class="section section--border-top">
      <div class="container">
        <div class="section-header">
          <h2 class="section-title">XC AGI 能做什么</h2>
          <p class="section-description">按需选择，自由搭配</p>
        </div>

        <div class="capabilities-grid">
          <div class="capability-card">
            <h3 class="capability-title">Excel 单据识别</h3>
            <p class="capability-desc">AI 快速识别各种格式的 Excel 出货单、收货单，支持批量处理</p>
          </div>
          <div class="capability-card">
            <h3 class="capability-title">标签自动生成</h3>
            <p class="capability-desc">根据单据数据自动生成产品标签，支持多种打印机型号</p>
          </div>
          <div class="capability-card">
            <h3 class="capability-title">出货单管理</h3>
            <p class="capability-desc">自动记录出货信息，多客户数据隔离，支持查询统计</p>
          </div>
          <div class="capability-card">
            <h3 class="capability-title">微信集成</h3>
            <p class="capability-desc">对接微信消息，发送打印指令，实时接收处理结果通知</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Scenarios -->
    <section class="section section--border-top">
      <div class="container">
        <div class="section-header">
          <h2 class="section-title">行业场景</h2>
          <p class="section-description">
            帮助各行业实现数字化，降低运营成本
          </p>
        </div>

        <div class="scenarios-grid">
          <div class="scenario-card">
            <span class="scenario-number">01</span>
            <h3 class="scenario-title">制造业数字化</h3>
            <p class="scenario-desc">帮助制造企业实现生产、库存、供应链的信息化管理，降低运营成本</p>
          </div>
          <div class="scenario-card">
            <span class="scenario-number">02</span>
            <h3 class="scenario-title">贸易公司</h3>
            <p class="scenario-desc">快速处理订单单据，自动生成标签，提升发货效率和准确性</p>
          </div>
          <div class="scenario-card">
            <span class="scenario-number">03</span>
            <h3 class="scenario-title">物流仓储</h3>
            <p class="scenario-desc">智能识别入库单据，自动打印标签，实现仓储管理数字化</p>
          </div>
        </div>
      </div>
    </section>

    <!-- About -->
    <section class="section section--border-top">
      <div class="container">
        <div class="about-section">
          <h2 class="section-title">关于我们</h2>
          <p class="about-text">
            成都修茈科技有限公司专注于企业级软件开发与数字化解决方案。我们相信 AI 技术能够为中小企业带来前所未有的效率提升。
            我们的 AI 员工系统基于 DeepSeek AI 和 OCR 技术，能够自动识别和处理各种商业单据，让您的团队从繁琐的重复工作中解放出来。
          </p>
        </div>
      </div>
    </section>

    <!-- Market（顶栏「AI 员工」锚点） -->
    <section id="ai-market" class="section section--border-top">
      <div class="container">
        <div class="section-header">
          <h2 class="section-title">
            <router-link class="section-title-link" :to="{ name: 'ai-store' }">AI 员工市场</router-link>
          </h2>
          <p class="section-description">
            浏览和购买现成的 MOD 扩展，快速为你的业务系统添加能力。
            <router-link :to="{ name: 'ai-store' }" class="section-more-link">进入专属商店页（按行业 / 类型筛选）</router-link>
          </p>
        </div>

        <div v-if="loading" class="market-loading">加载中...</div>
        <div v-else-if="items.length" class="market-grid">
          <div v-for="item in items" :key="item.id" class="market-card">
            <h3 class="market-card-title">{{ item.name }}</h3>
            <p class="market-card-desc">{{ truncate(item.description, 60) }}</p>
            <div class="market-card-footer">
              <span class="market-card-price" :class="{ free: item.price <= 0 }">
                {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
              </span>
              <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn btn-sm">详情</router-link>
            </div>
          </div>
        </div>
        <div v-else class="market-empty">市场暂无商品</div>
      </div>
    </section>

    <!-- CTA -->
    <section class="section section--border-top">
      <div class="container">
        <div class="cta-inner">
          <h2 class="cta-heading">准备好迎接您的 AI 员工了吗？</h2>
          <p class="cta-description">
            立即体验，让 AI 为您工作
          </p>
          <router-link to="/register" class="btn btn-white btn--large">开始使用</router-link>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
      <div class="container">
        <div class="footer-grid">
          <div class="footer-brand">
            <span class="footer-logo">XC AGI</span>
            <p class="footer-desc">AI 单据智能处理系统</p>
          </div>
          <div class="footer-links">
            <div class="footer-col">
              <h4 class="footer-heading">产品</h4>
              <router-link to="/" class="footer-link">首页</router-link>
              <router-link :to="{ name: 'ai-store' }" class="footer-link">AI 员工商店</router-link>
              <router-link to="/plans" class="footer-link">套餐</router-link>
            </div>
            <div class="footer-col">
              <h4 class="footer-heading">支持</h4>
              <router-link :to="workbenchLink" class="footer-link">{{ isLoggedIn ? '工作台' : '登录' }}</router-link>
              <router-link v-if="!isLoggedIn" to="/register" class="footer-link">注册</router-link>
            </div>
          </div>
        </div>
        <div class="footer-bottom">
          <p class="footer-legal">© 2026 成都修茈科技有限公司 保留所有权利。</p>
          <p class="footer-contact">
            地址：（请填写公司地址）
            <span class="footer-contact-sep" aria-hidden="true">·</span>
            邮箱：<a class="footer-mail" href="mailto:970882904@qq.com">970882904@qq.com</a>
          </p>
          <p class="footer-beian">
            <a
              class="footer-beian-link"
              href="https://beian.miit.gov.cn/"
              target="_blank"
              rel="noopener noreferrer"
            >蜀ICP备2026014056号-1</a>
            <span class="footer-beian-sep" aria-hidden="true">·</span>
            <span class="footer-beian-police">川公网安备13f68c61238ea5b1f4c4887c942a0d55号</span>
          </p>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()

/** ``public/hero-video.mp4``，随 Vite ``base``（如 ``/market/``）解析 */
const heroVideoUrl = `${import.meta.env.BASE_URL}hero-video.mp4`

const loading = ref(false)
const items = ref([])
const isLoggedIn = ref(false)

/** 已登录直接去仓库工作台；未登录去登录页并带回跳，避免已登录点 /login 被守卫立即打回首页像「点不动」 */
const workbenchLink = computed(() =>
  isLoggedIn.value
    ? '/workbench/repository'
    : { path: '/login', query: { redirect: '/workbench/repository' } },
)

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
}

async function refreshLandingAuth() {
  const token = localStorage.getItem('modstore_token')
  if (!token) {
    isLoggedIn.value = false
    return
  }
  try {
    await api.me()
    isLoggedIn.value = true
  } catch {
    isLoggedIn.value = false
  }
}

onMounted(async () => {
  await refreshLandingAuth()
  try {
    const res = await api.catalog('', '', 4, 0)
    items.value = res?.items || []
  } catch {
    items.value = []
  }
})

const stopAfterEach = router.afterEach((to) => {
  if (to.name === 'home') refreshLandingAuth()
})
onUnmounted(() => {
  stopAfterEach()
})
</script>

<style scoped>
.landing-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* 顶栏 / 落地页锚点跳转时避免标题被 sticky 导航挡住 */
#ai-market {
  scroll-margin-top: 72px;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

/* Landing Nav */
.landing-nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 2000;
  background: rgba(10, 10, 10, 0.8);
  backdrop-filter: blur(12px);
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
  pointer-events: auto;
}

.landing-nav-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
}

.landing-logo {
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  text-decoration: none;
}

.landing-nav-links {
  display: flex;
  align-items: center;
  gap: 16px;
}

.landing-nav-links a {
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 6px;
  transition: all 0.2s;
}

.nav-ghost {
  color: rgba(255, 255, 255, 0.6);
}

.nav-ghost:hover {
  color: #ffffff;
}

.nav-primary {
  background: #ffffff;
  color: #0a0a0a;
}

.nav-primary:hover {
  opacity: 0.9;
}

/* Gradient Text */
.gradient-text {
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* Hero */
.hero {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  padding-top: 56px;
  overflow: hidden;
}

.hero-gradient-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: radial-gradient(ellipse at top right, rgba(96,165,250,0.15) 0%, transparent 60%),
              radial-gradient(ellipse at bottom left, rgba(167,139,250,0.1) 0%, transparent 60%);
  z-index: 0;
}

.hero-content {
  position: relative;
  z-index: 2;
  max-width: 720px;
}

.hero-eyebrow {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 24px;
  letter-spacing: 0.02em;
}

.hero-heading {
  font-size: clamp(40px, 5vw, 64px);
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.03em;
  margin: 0 0 24px;
}

.hero-description {
  font-size: 17px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 40px;
  max-width: 560px;
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s ease-out;
  line-height: 1;
  border: none;
}

.btn-white {
  background: #ffffff;
  color: #0a0a0a;
}

.btn-white:hover {
  opacity: 0.9;
}

.btn-ghost {
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  border: 0.5px solid rgba(255, 255, 255, 0.15);
}

.btn-ghost:hover {
  color: #ffffff;
  border-color: rgba(255, 255, 255, 0.3);
}

.btn--large {
  padding: 16px 24px;
  font-size: 14px;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 12px;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.7);
  border-radius: 6px;
}

.btn-sm:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

/* Sections */
.section {
  padding-top: 96px;
  padding-bottom: 96px;
}

.section--border-top {
  border-top: 0.5px solid rgba(255, 255, 255, 0.1);
}

.section-header {
  margin-bottom: 48px;
}

.section-title {
  font-size: clamp(24px, 3vw, 32px);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.section-title-link {
  color: inherit;
  text-decoration: none;
}

.section-title-link:hover {
  color: #93c5fd;
}

.section-description {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
  max-width: 640px;
}

.section-more-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 14px;
  color: #93c5fd;
  font-weight: 500;
  text-decoration: none;
}

.section-more-link:hover {
  text-decoration: underline;
}

/* Features */
.features-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
}

.feature-item {
  padding: 20px;
  border: 0.5px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
}

.feature-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px;
}

.feature-desc {
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* Use Case Video */
.video-wrapper {
  margin-bottom: 48px;
  border-radius: 16px;
  overflow: hidden;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  background: #111111;
}

.demo-video {
  width: 100%;
  height: auto;
  display: block;
}

.use-case-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.stat-card {
  padding: 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
}

.stat-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
}

/* Capabilities */
.capabilities-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.capability-card {
  padding: 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.02);
  transition: all 0.2s;
}

.capability-card:hover {
  border-color: rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.04);
}

.capability-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 8px;
}

.capability-desc {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* Scenarios */
.scenarios-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

.scenario-card {
  padding: 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
}

.scenario-number {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.25);
  margin-bottom: 12px;
}

.scenario-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 8px;
}

.scenario-desc {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* About */
.about-section {
  max-width: 640px;
}

.about-text {
  font-size: 15px;
  line-height: 1.8;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

/* Market */
.market-loading {
  text-align: center;
  padding: 3rem;
  color: rgba(255,255,255,0.3);
}

.market-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.market-card {
  padding: 20px;
  border: 0.5px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  background: rgba(255,255,255,0.02);
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
}

.market-card:hover {
  border-color: rgba(255,255,255,0.15);
}

.market-card-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px;
}

.market-card-desc {
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255,255,255,0.4);
  margin: 0 0 16px;
  flex: 1;
}

.market-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.market-card-price {
  font-size: 13px;
  font-weight: 700;
  color: #ff6b6b;
}

.market-card-price.free {
  color: #4ade80;
}

.market-empty {
  text-align: center;
  padding: 2rem;
  color: rgba(255,255,255,0.3);
  font-size: 14px;
}

/* CTA */
.cta-inner {
  text-align: center;
  max-width: 560px;
  margin: 0 auto;
}

.cta-heading {
  font-size: clamp(24px, 3vw, 32px);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 12px;
}

.cta-description {
  font-size: 15px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 24px;
  line-height: 1.6;
}

/* Footer */
.footer {
  padding: 48px 0 24px;
  border-top: 0.5px solid rgba(255, 255, 255, 0.1);
}

.footer-grid {
  display: flex;
  justify-content: space-between;
  gap: 48px;
  margin-bottom: 48px;
}

.footer-logo {
  font-size: 14px;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
}

.footer-desc {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

.footer-links {
  display: flex;
  gap: 48px;
}

.footer-heading {
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.4);
  margin: 0 0 12px;
}

.footer-link {
  display: block;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  text-decoration: none;
  padding: 4px 0;
  transition: color 0.15s ease;
}

.footer-link:hover {
  color: #ffffff;
}

.footer-bottom {
  padding-top: 28px;
  margin-top: 4px;
  border-top: 0.5px solid rgba(255, 255, 255, 0.1);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}

.footer-bottom p {
  margin: 0;
  line-height: 1.55;
}

.footer-legal {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.38);
}

.footer-contact {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: center;
  column-gap: 0.15em;
  row-gap: 4px;
}

.footer-contact-sep,
.footer-beian-sep {
  margin: 0 0.35em;
  color: rgba(255, 255, 255, 0.28);
}

.footer-mail {
  color: rgba(255, 255, 255, 0.55);
  text-decoration: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  transition: color 0.15s ease, border-color 0.15s ease;
}

.footer-mail:hover {
  color: #ffffff;
  border-bottom-color: rgba(255, 255, 255, 0.45);
}

.footer-beian {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.36);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0 0.15em;
  row-gap: 6px;
}

.footer-beian-link {
  color: rgba(255, 255, 255, 0.42);
  text-decoration: none;
  transition: color 0.15s ease;
}

.footer-beian-link:hover {
  color: rgba(255, 255, 255, 0.75);
}

.footer-beian-police {
  color: rgba(255, 255, 255, 0.36);
}

/* Responsive */
@media (max-width: 768px) {
  .section {
    padding-top: 64px;
    padding-bottom: 64px;
  }

  .hero {
    min-height: auto;
    padding-top: 120px;
    padding-bottom: 64px;
  }

  .hero-video {
    display: none;
  }

  .features-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .use-case-grid {
    grid-template-columns: 1fr;
    gap: 32px;
  }

  .capabilities-grid {
    grid-template-columns: 1fr;
  }

  .scenarios-grid {
    grid-template-columns: 1fr;
  }

  .market-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .footer-grid {
    flex-direction: column;
  }

  .footer-links {
    gap: 32px;
  }
}

@media (max-width: 480px) {
  .features-grid {
    grid-template-columns: 1fr;
  }

  .market-grid {
    grid-template-columns: 1fr;
  }
}
</style>
