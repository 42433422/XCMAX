<template>
  <div class="landing-page">
    <!-- Landing Nav -->
    <HomeLandingNav
      :is-logged-in="isLoggedIn"
      :user-label="userLabel"
      :workbench-link="workbenchLink"
      :mobile-nav-open="mobileNavOpen"
      @toggle-nav="toggleMobileNav"
      @close-nav="closeMobileNav"
    />

    <!-- Hero -->
    <section class="hero">
      <div class="hero-gradient-bg"></div>
      <div class="container">
        <div class="hero-content">
          <p class="hero-eyebrow">修茈科技 · XCAGI · AI 单据与流程自动化</p>
          <h1 class="hero-heading">
            <span class="gradient-text">不知疲倦、永不离线</span><br />
            可无限复制的智能员工团队
          </h1>
          <p class="hero-description">
            用 Mod 组合 AI 员工，处理 Excel 单据识别、标签打印、出货收货与报表流程；与官网产品中心能力一致，可在此注册进入完整工作台。
          </p>
          <div class="hero-actions">
            <router-link to="/register" class="btn btn-white">免费注册</router-link>
            <a href="/download" class="btn btn-ghost btn-ghost--download" target="_blank" rel="noopener">下载客户端</a>
            <router-link :to="{ name: 'plans' }" class="btn btn-ghost">查看会员方案</router-link>
            <a href="/services.html" class="btn btn-ghost btn-ghost--external">官网产品中心</a>
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

    <!-- 联系表单（对接 POST /api/public/contact） -->
    <HomeContactSection
      :cs-intake-active="csIntakeActive"
      :contact-form="contactForm"
      :contact-error="contactError"
      :contact-success="contactSuccess"
      :contact-submitting="contactSubmitting"
      @update-field="onContactFieldUpdate"
      @submit="submitContact"
    />

    <!-- Market（顶栏「AI 员工」锚点） -->
    <HomeMarketSection
      :is-logged-in="isLoggedIn"
      :loading="loading"
      :items="items"
      @open-upload="showUploadModal = true"
    />

    <!-- 上架素材模态框 -->
    <div v-if="showUploadModal" class="modal-overlay" @click="showUploadModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>上架 AI 员工素材</h3>
          <button @click="showUploadModal = false" class="modal-close">&times;</button>
        </div>
        <div class="modal-body">
          <form @submit.prevent="uploadEmployee">
            <div class="form-group">
              <label for="employee-name">员工名称</label>
              <input type="text" id="employee-name" v-model="uploadForm.name" required>
            </div>
            <div class="form-group">
              <label for="employee-description">描述</label>
              <textarea id="employee-description" v-model="uploadForm.description" required></textarea>
            </div>
            <div class="form-group">
              <label for="employee-industry">行业</label>
              <input type="text" id="employee-industry" v-model="uploadForm.industry">
            </div>
            <div class="form-group">
              <label for="employee-price">价格 (¥)</label>
              <input type="number" id="employee-price" v-model.number="uploadForm.price" min="0" step="0.01">
            </div>
            <div class="form-group">
              <label for="employee-license">授权范围</label>
              <select id="employee-license" v-model="uploadForm.license_scope">
                <option value="personal">个人使用</option>
                <option value="commercial">商业授权（可收费）</option>
                <option value="free_personal">免费个人用</option>
              </select>
            </div>
            <div class="form-group">
              <label for="employee-origin">来源类型</label>
              <select id="employee-origin" v-model="uploadForm.origin_type">
                <option value="original">原创</option>
                <option value="derivative">二创/改编</option>
                <option value="collaboration">联动授权</option>
                <option value="fan_linkage">粉丝联动</option>
                <option value="suspected_plagiarism">疑似抄袭</option>
              </select>
            </div>
            <div class="form-group">
              <label for="employee-risk">IP 风险级别</label>
              <select id="employee-risk" v-model="uploadForm.ip_risk_level">
                <option value="low">低</option>
                <option value="medium">中（只能免费/个人用）</option>
                <option value="high">高（只能免费/个人用）</option>
              </select>
            </div>
            <div class="form-group">
              <label for="employee-file">员工包文件 (.xcemp 或 .zip)</label>
              <input type="file" id="employee-file" @change="handleFileChange" required>
            </div>
            <div v-if="uploadError" class="error-message">{{ uploadError }}</div>
            <div v-if="uploadSuccess" class="success-message">上架成功！</div>
            <div class="form-actions">
              <button type="button" @click="showUploadModal = false" class="btn btn-secondary">取消</button>
              <button type="submit" class="btn btn-primary" :disabled="uploading">
                {{ uploading ? '上传中...' : '上架' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

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
    <HomeFooter :is-logged-in="isLoggedIn" :workbench-link="workbenchLink" />
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./home-view/，模板子组件在 ./home-view/，样式在 ./home-view/home-view.css。
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import * as homeViewTypes from './home-view/homeViewTypes'
import type { MarketItem } from './home-view/homeViewTypes'
import HomeLandingNav from './home-view/HomeLandingNav.vue'
import HomeContactSection from './home-view/HomeContactSection.vue'
import HomeMarketSection from './home-view/HomeMarketSection.vue'
import HomeFooter from './home-view/HomeFooter.vue'
import { useLandingNav } from './home-view/useLandingNav'
import { useLandingAuth } from './home-view/useLandingAuth'
import { useContactForm } from './home-view/useContactForm'
import { useUploadModal } from './home-view/useUploadModal'

const { mobileNavOpen, toggleMobileNav, closeMobileNav } = useLandingNav()

/** ``public/hero-video.mp4``，随 Vite ``base``（如 ``/market/``）解析 */
const heroVideoUrl = `${import.meta.env.BASE_URL}hero-video.mp4`

const loading = ref(false)
const items = ref<MarketItem[]>([])

// 顶层 const 保持 wrapper.vm 对拆分前绑定的可访问面一致。
const truncate = homeViewTypes.truncate

async function loadMarketItems() {
  try {
    const res = await api.catalog('', '', 4, 0)
    items.value = (res?.items ?? []) as MarketItem[]
  } catch {
    items.value = []
  }
}

const { isLoggedIn, userLabel, workbenchLink, refreshLandingAuth } = useLandingAuth()

const {
  showUploadModal, uploadForm, uploadError, uploadSuccess, uploading,
  handleFileChange, uploadEmployee,
} = useUploadModal({ items })

const {
  contactForm, contactSubmitting, contactError, contactSuccess, csIntakeActive,
  submitContact, applyCsIntakeFromRoute, onContactFieldUpdate,
} = useContactForm()

onMounted(async () => {
  applyCsIntakeFromRoute()
  await refreshLandingAuth()
  await loadMarketItems()
})
</script>

<style scoped src="./home-view/home-view.css"></style>
