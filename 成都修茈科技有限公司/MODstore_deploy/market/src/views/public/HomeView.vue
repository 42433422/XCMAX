<template>
  <div class="landing-page">
    <!-- Landing Nav -->
    <header class="landing-nav">
      <div class="container">
        <div class="landing-nav-inner">
          <router-link to="/about" class="landing-logo" @click="closeMobileNav">XC AGI</router-link>
          <nav class="landing-nav-links" aria-label="主导航">
            <router-link :to="{ name: 'ai-store' }" class="nav-ghost">AI 市场</router-link>
            <router-link to="/download" class="nav-ghost">软件下载</router-link>
            <router-link :to="workbenchLink" class="nav-ghost">进入工作台</router-link>
            <router-link
              v-if="!isLoggedIn"
              to="/register"
              class="nav-primary"
            >免费注册</router-link>
            <span
              v-else
              class="nav-user"
              :title="userLabel"
            >{{ userLabel }}</span>
          </nav>
          <button
            type="button"
            class="landing-nav-toggle"
            :class="{ 'landing-nav-toggle--open': mobileNavOpen }"
            :aria-label="mobileNavOpen ? '关闭菜单' : '打开菜单'"
            :aria-expanded="mobileNavOpen"
            aria-controls="landing-mobile-nav"
            @click="toggleMobileNav"
          >
            <span aria-hidden="true"></span>
            <span aria-hidden="true"></span>
            <span aria-hidden="true"></span>
          </button>
        </div>
      </div>
      <div
        v-if="mobileNavOpen"
        class="landing-nav-overlay"
        aria-hidden="true"
        @click="closeMobileNav"
      ></div>
      <nav
        id="landing-mobile-nav"
        class="landing-nav-drawer"
        :class="{ 'landing-nav-drawer--open': mobileNavOpen }"
        aria-label="移动端菜单"
      >
        <router-link :to="{ name: 'ai-store' }" class="landing-nav-drawer-link" @click="closeMobileNav">AI 市场</router-link>
        <router-link to="/download" class="landing-nav-drawer-link" @click="closeMobileNav">软件下载</router-link>
        <router-link :to="workbenchLink" class="landing-nav-drawer-link" @click="closeMobileNav">
          {{ isLoggedIn ? '进入工作台' : '登录 / 工作台' }}
        </router-link>
        <router-link :to="{ name: 'plans' }" class="landing-nav-drawer-link" @click="closeMobileNav">会员方案</router-link>
        <a href="/services.html" class="landing-nav-drawer-link" @click="closeMobileNav">官网产品中心</a>
        <router-link
          v-if="!isLoggedIn"
          to="/register"
          class="landing-nav-drawer-link landing-nav-drawer-link--primary"
          @click="closeMobileNav"
        >免费注册</router-link>
        <span v-else class="landing-nav-drawer-user" :title="userLabel">{{ userLabel }}</span>
      </nav>
    </header>

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
            <router-link to="/download" class="btn btn-ghost btn-ghost--download">下载 Android 客户端</router-link>
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
    <section id="contact" class="section section--border-top">
      <div class="container grid grid-2">
        <div class="contact-intro">
          <h2 class="section-title">商务合作与咨询</h2>
          <p v-if="csIntakeActive" class="cs-intake-banner">
            修茈科技邀请您填写项目需求，提交后您的专属顾问将尽快跟进。
          </p>
          <p class="section-description contact-intro__text">
            留下您的需求与联系方式，我们会通过邮箱尽快回复。信息将保存至平台数据库，仅用于商务联络。
          </p>
        </div>
        <form id="contact-form" class="contact-form" @submit.prevent="submitContact">
          <div class="form-group">
            <label for="contact-name">称呼</label>
            <input id="contact-name" v-model.trim="contactForm.name" type="text" required maxlength="128" autocomplete="name" />
          </div>
          <div class="form-group">
            <label for="contact-email">邮箱</label>
            <input id="contact-email" v-model.trim="contactForm.email" type="email" required maxlength="256" autocomplete="email" />
          </div>
          <div class="form-group">
            <label for="contact-phone">电话（选填）</label>
            <input id="contact-phone" v-model.trim="contactForm.phone" type="tel" maxlength="64" autocomplete="tel" />
          </div>
          <div class="form-group">
            <label for="contact-company">公司 / 组织（选填）</label>
            <input id="contact-company" v-model.trim="contactForm.company" type="text" maxlength="256" autocomplete="organization" />
          </div>
          <div class="form-group">
            <label for="contact-message">需求说明（选填）</label>
            <textarea id="contact-message" v-model.trim="contactForm.message" maxlength="8000" rows="4" />
          </div>
          <div v-if="contactError" class="error-message">{{ contactError }}</div>
          <div v-if="contactSuccess" class="success-message">已提交，我们会尽快与您联系。</div>
          <div class="form-actions contact-form__actions">
            <button type="submit" class="btn btn-primary" :disabled="contactSubmitting">
              {{ contactSubmitting ? '提交中…' : '提交' }}
            </button>
          </div>
          <p id="form-tip" class="footer-meta">
            提交后写入服务器数据库；若提示失败请检查网络或稍后重试。
          </p>
        </form>
      </div>
    </section>

    <!-- Market（顶栏「AI 员工」锚点） -->
    <section id="ai-market" class="section section--border-top">
      <div class="container">
        <div class="section-header">
          <h2 class="section-title">
            <router-link class="section-title-link" :to="{ name: 'ai-store' }">XC AGI · AI 市场</router-link>
          </h2>
          <p class="section-description">
            浏览和购买 AI 员工、提示词、Skill、TTS 声音模型与 MOD 素材，快速为你的业务系统添加能力。
            <router-link :to="{ name: 'ai-store' }" class="section-more-link">进入 AI 市场（按行业 / 类目 / 授权筛选）</router-link>
          </p>
          <button v-if="isLoggedIn" @click="showUploadModal = true" class="btn btn-primary">上架素材</button>
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
        <div v-else class="market-empty">AI 市场暂无商品</div>
      </div>
    </section>

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
              <router-link :to="{ name: 'ai-store' }" class="footer-link">AI 市场</router-link>
              <router-link to="/plans" class="footer-link">套餐</router-link>
              <router-link to="/download" class="footer-link">软件下载</router-link>
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
            >蜀ICP备2026014056号-3A</a>
            <span class="footer-beian-sep" aria-hidden="true">·</span>
            <span class="footer-beian-police">川公网安备13f68c61238ea5b1f4c4887c942a0d55号</span>
          </p>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'

const router = useRouter()
const route = useRoute()

const mobileNavOpen = ref(false)

function toggleMobileNav() {
  mobileNavOpen.value = !mobileNavOpen.value
}

function closeMobileNav() {
  mobileNavOpen.value = false
}

watch(
  () => route.fullPath,
  () => {
    closeMobileNav()
  },
)

watch(mobileNavOpen, (open) => {
  if (typeof document === 'undefined') return
  document.body.classList.toggle('landing-nav-open', open)
})

onUnmounted(() => {
  if (typeof document !== 'undefined') {
    document.body.classList.remove('landing-nav-open')
  }
})

/** ``public/hero-video.mp4``，随 Vite ``base``（如 ``/market/``）解析 */
const heroVideoUrl = `${import.meta.env.BASE_URL}hero-video.mp4`

interface MarketItem {
  id: number | string
  name: string
  description?: string
  price: number
}

const loading = ref(false)
const items = ref<MarketItem[]>([])
const isLoggedIn = ref(false)
const username = ref('')
const userEmail = ref('')

const userLabel = computed(() => {
  const u = (username.value || '').trim()
  if (u) return u
  const e = (userEmail.value || '').trim()
  if (e) return e.split('@')[0] || e
  return '已登录'
})

// 上传相关状态
const showUploadModal = ref(false)
const uploadForm = ref({
  name: '',
  description: '',
  industry: '',
  price: 0,
  license_scope: 'personal',
  origin_type: 'original',
  ip_risk_level: 'low',
})
const uploadFile = ref<File | null>(null)
const uploadError = ref('')
const uploadSuccess = ref(false)
const uploading = ref(false)

const contactForm = ref({
  name: '',
  email: '',
  phone: '',
  company: '',
  message: '',
})
const contactSubmitting = ref(false)
const contactError = ref('')
const contactSuccess = ref(false)
const csIntakeActive = ref(false)
const csIntakeUid = ref<number | null>(null)
const csIntakeToken = ref('')

function decodeBriefParam(raw: string): string {
  const s = (raw || '').trim().replace(/-/g, '+').replace(/_/g, '/')
  const pad = '='.repeat((4 - (s.length % 4)) % 4)
  try {
    return decodeURIComponent(escape(atob(s + pad)))
  } catch {
    return ''
  }
}

function applyCsIntakeFromRoute() {
  const q = route.query
  const uid = Number(q.cs_uid)
  const token = String(q.cs_t || '').trim()
  if (!Number.isFinite(uid) || uid <= 0 || !token) {
    csIntakeActive.value = false
    csIntakeUid.value = null
    csIntakeToken.value = ''
    return
  }
  csIntakeActive.value = true
  csIntakeUid.value = uid
  csIntakeToken.value = token
  const brief = decodeBriefParam(String(q.brief || ''))
  const csName = String(q.cs_name || '').trim()
  if (csName && !contactForm.value.name) contactForm.value.name = csName
  if (brief && !contactForm.value.message) contactForm.value.message = brief
  void nextTick(() => {
    document.getElementById('contact')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

/** 已登录直接去仓库工作台；未登录去登录页并带回跳，避免已登录点 /login 被守卫立即打回首页像「点不动」 */
const workbenchLink = computed(() =>
  isLoggedIn.value
    ? '/workbench'
    : { path: '/login', query: { redirect: '/workbench' } },
)

function truncate(str: string | undefined | null, len: number): string {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
}

async function refreshLandingAuth() {
  const raw = localStorage.getItem('modstore_token')
  const token = raw && raw !== 'undefined' && raw !== 'null' ? raw : ''
  if (!token) {
    isLoggedIn.value = false
    username.value = ''
    userEmail.value = ''
    if (raw) localStorage.removeItem('modstore_token')
    return
  }
  try {
    const me = await api.me()
    isLoggedIn.value = true
    username.value = typeof me.username === 'string' ? me.username : ''
    userEmail.value = typeof me.email === 'string' ? me.email : ''
  } catch {
    isLoggedIn.value = false
    username.value = ''
    userEmail.value = ''
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement | null
  uploadFile.value = input?.files?.[0] ?? null
}

async function submitContact() {
  if (contactSubmitting.value) return
  contactError.value = ''
  contactSuccess.value = false
  contactSubmitting.value = true
  try {
    await api.submitLandingContact({
      name: contactForm.value.name,
      email: contactForm.value.email,
      phone: contactForm.value.phone,
      company: contactForm.value.company,
      message: contactForm.value.message,
      source: csIntakeActive.value ? 'cs_intake' : 'home',
      cs_uid: csIntakeActive.value && csIntakeUid.value ? csIntakeUid.value : undefined,
      cs_t: csIntakeActive.value ? csIntakeToken.value : '',
    })
    contactSuccess.value = true
    contactForm.value = { name: '', email: '', phone: '', company: '', message: '' }
  } catch (e) {
    contactError.value = (e as Error)?.message || '提交失败，请稍后重试'
  } finally {
    contactSubmitting.value = false
  }
}

async function uploadEmployee() {
  if (!uploadFile.value) {
    uploadError.value = '请选择员工包文件'
    return
  }

  uploadError.value = ''
  uploadSuccess.value = false
  uploading.value = true

  try {
    const paid = Number(uploadForm.value.price || 0) > 0
    const risky = ['derivative', 'collaboration', 'fan_linkage', 'suspected_plagiarism'].includes(uploadForm.value.origin_type)
      || ['medium', 'high'].includes(uploadForm.value.ip_risk_level)
    if (paid && uploadForm.value.license_scope !== 'commercial') {
      throw new Error('收费商品必须选择商业授权')
    }
    if (risky && (paid || uploadForm.value.license_scope === 'commercial')) {
      throw new Error('疑似抄袭、二创、联动或中高风险素材只能免费或限制个人使用')
    }
    // 生成唯一的包ID和版本号
    const pkgId = `employee_${Date.now()}_${Math.floor(Math.random() * 1000)}`
    const version = '1.0.0'

    const metadata = {
      id: pkgId,
      version: version,
      name: uploadForm.value.name,
      description: uploadForm.value.description,
      artifact: 'employee_pack',
      material_category: 'ai_employee',
      license_scope: uploadForm.value.license_scope,
      origin_type: uploadForm.value.origin_type,
      ip_risk_level: uploadForm.value.ip_risk_level,
      industry: uploadForm.value.industry || '通用',
      commerce: {
        price: uploadForm.value.price
      }
    }

    await api.uploadPackage(metadata, uploadFile.value)
    uploadSuccess.value = true
    
    // 重置表单
    uploadForm.value = {
      name: '',
      description: '',
      industry: '',
      price: 0,
      license_scope: 'personal',
      origin_type: 'original',
      ip_risk_level: 'low',
    }
    uploadFile.value = null
    
    // 重新加载商品列表
    try {
      const res = await api.catalog('', '', 4, 0)
      items.value = res.items
    } catch {
      // 加载失败不影响上传成功的提示
    }
    
    // 3秒后关闭模态框
    setTimeout(() => {
      showUploadModal.value = false
    }, 3000)
  } catch (error) {
    uploadError.value = (error as Error)?.message || '上传失败，请重试'
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  applyCsIntakeFromRoute()
  await refreshLandingAuth()
  try {
    const res = await api.catalog('', '', 4, 0)
    items.value = (res?.items ?? []) as MarketItem[]
  } catch {
    items.value = []
  }
})

watch(
  () => route.query,
  () => {
    applyCsIntakeFromRoute()
  },
)

const stopAfterEach = router.afterEach((to) => {
  if (to.name === 'home') void refreshLandingAuth()
})
watch(
  () => router.currentRoute.value.name,
  (name) => {
    if (name === 'home') void refreshLandingAuth()
  },
)
onUnmounted(() => {
  stopAfterEach()
})
</script>

<style scoped>
.landing-page {
  min-height: 100vh;
  min-height: 100dvh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased;
  --nav-h: 56px;
  overflow-x: hidden;
}

/* 顶栏 / 落地页锚点跳转时避免标题被 sticky 导航挡住 */
#ai-market {
  scroll-margin-top: calc(var(--nav-h) + 16px);
}

.container {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: 0 var(--layout-pad-x);
  box-sizing: border-box;
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
  height: var(--nav-h);
  min-height: var(--nav-h);
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

.nav-user {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
  padding: 6px 12px;
  border-radius: 6px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.landing-nav-toggle {
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0.5px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.landing-nav-toggle span {
  display: block;
  width: 18px;
  height: 2px;
  margin: 3px 0;
  border-radius: 99px;
  background: rgba(255, 255, 255, 0.88);
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.landing-nav-toggle--open span:nth-child(1) {
  transform: translateY(8px) rotate(45deg);
}

.landing-nav-toggle--open span:nth-child(2) {
  opacity: 0;
}

.landing-nav-toggle--open span:nth-child(3) {
  transform: translateY(-8px) rotate(-45deg);
}

.landing-nav-overlay {
  position: fixed;
  inset: 0;
  z-index: 1999;
  background: rgba(0, 0, 0, 0.55);
  animation: landing-nav-overlay-in 0.2s ease;
}

@keyframes landing-nav-overlay-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.landing-nav-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 2001;
  width: min(18rem, calc(100vw - 3rem));
  padding: calc(var(--nav-h) + 1rem) 1rem calc(1rem + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  background: rgba(14, 14, 14, 0.98);
  border-left: 0.5px solid rgba(255, 255, 255, 0.1);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.45);
  transform: translateX(100%);
  visibility: hidden;
  pointer-events: none;
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1), visibility 0.28s;
}

.landing-nav-drawer--open {
  transform: translateX(0);
  visibility: visible;
  pointer-events: auto;
}

.landing-nav-drawer-link {
  display: block;
  padding: 0.85rem 1rem;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
  text-decoration: none;
  background: rgba(255, 255, 255, 0.04);
  border: 0.5px solid rgba(255, 255, 255, 0.08);
}

.landing-nav-drawer-link--primary {
  margin-top: 0.35rem;
  background: #ffffff;
  color: #0a0a0a;
  border-color: transparent;
  text-align: center;
}

.landing-nav-drawer-user {
  margin-top: auto;
  padding: 0.75rem 1rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  padding-top: var(--nav-h);
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
  flex-wrap: wrap;
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

  .btn-primary {
    background: #60a5fa;
    color: #0a0a0a;
  }

  .btn-primary:hover {
    background: #3b82f6;
  }

  .btn-secondary {
    background: rgba(255, 255, 255, 0.1);
    color: #ffffff;
  }

  .btn-secondary:hover {
    background: rgba(255, 255, 255, 0.15);
  }

  /* 模态框样式 */
  .modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 3000;
  }

  .modal-content {
    background: #111111;
    border-radius: 12px;
    border: 0.5px solid rgba(255, 255, 255, 0.1);
    width: 100%;
    max-width: 500px;
    max-height: 90vh;
    overflow-y: auto;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px;
    border-bottom: 0.5px solid rgba(255, 255, 255, 0.1);
  }

  .modal-header h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  .modal-close {
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.5);
    font-size: 24px;
    cursor: pointer;
    padding: 0;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .modal-close:hover {
    color: #ffffff;
  }

  .modal-body {
    padding: 20px;
  }

  .form-group {
    margin-bottom: 16px;
  }

  .form-group label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 6px;
    color: rgba(255, 255, 255, 0.8);
  }

  .form-group input,
  .form-group textarea {
    width: 100%;
    padding: 10px 12px;
    border-radius: 8px;
    border: 0.5px solid rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.04);
    color: #ffffff;
    font-size: 14px;
  }

  .form-group textarea {
    resize: vertical;
    min-height: 80px;
  }

  .form-group input:focus,
  .form-group textarea:focus {
    outline: none;
    border-color: #60a5fa;
  }

  .error-message {
    background: rgba(255, 80, 80, 0.1);
    color: #ff8a8a;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 13px;
  }

  .success-message {
    background: rgba(74, 222, 128, 0.1);
    color: #86efac;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 13px;
  }

  .form-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
    margin-top: 20px;
  }

  .form-actions button {
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    border: none;
  }

  .form-actions button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

/* Sections */
.section {
  padding-top: clamp(3.5rem, 10vw, 6rem);
  padding-bottom: clamp(3.5rem, 10vw, 6rem);
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
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
  gap: clamp(1rem, 3vw, 1.5rem);
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

#contact {
  scroll-margin-top: calc(var(--nav-h) + 16px);
}

.container.grid {
  display: grid;
  gap: clamp(1.5rem, 4vw, 2.5rem);
  align-items: start;
}

.container.grid-2 {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

@media (max-width: 768px) {
  .container.grid-2 {
    grid-template-columns: 1fr;
  }
}

.contact-intro__text {
  max-width: none;
}

.cs-intake-banner {
  margin: 0 0 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  background: rgba(74, 108, 247, 0.15);
  border: 1px solid rgba(74, 108, 247, 0.35);
  color: #c7d4ff;
  font-size: 0.9rem;
  line-height: 1.5;
}

.contact-form {
  padding: clamp(1rem, 3vw, 1.5rem);
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.contact-form .form-group {
  margin-bottom: 14px;
}

.contact-form .form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 6px;
  color: rgba(255, 255, 255, 0.8);
}

.contact-form .form-group input,
.contact-form .form-group textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: 8px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #ffffff;
  font-size: 14px;
}

.contact-form .form-group textarea {
  resize: vertical;
  min-height: 96px;
}

.contact-form .form-group input:focus,
.contact-form .form-group textarea:focus {
  outline: none;
  border-color: #60a5fa;
}

.contact-form__actions {
  margin-top: 8px;
  justify-content: flex-start;
}

.footer-meta {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.38);
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
  .landing-nav-links {
    display: none;
  }

  .landing-nav-toggle {
    display: flex;
  }

  .landing-nav-inner {
    padding-top: env(safe-area-inset-top);
  }

  .section {
    padding-top: 64px;
    padding-bottom: 64px;
  }

  .hero {
    min-height: auto;
    padding-top: calc(var(--nav-h) + env(safe-area-inset-top) + 2.5rem);
    padding-bottom: 4rem;
  }

  .hero-heading {
    font-size: clamp(1.75rem, 7vw, 2.25rem);
  }

  .hero-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .hero-actions .btn {
    width: 100%;
    justify-content: center;
    min-height: 44px;
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
