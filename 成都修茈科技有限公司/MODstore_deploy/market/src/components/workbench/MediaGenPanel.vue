<template>
  <div v-if="open" class="mg-mask" role="dialog" aria-modal="true" aria-labelledby="mg-title" @click.self="$emit('close')">
    <div class="mg-card">
      <header class="mg-head">
        <h2 id="mg-title" class="mg-title">AI 创作 · {{ panelTitle }}</h2>
        <button type="button" class="mg-x" aria-label="关闭" @click="$emit('close')">×</button>
      </header>

      <nav class="mg-tabs" role="tablist" aria-label="生成模式">
        <button v-for="t in tabs" :key="t.id" type="button" role="tab" class="mg-tab" :class="{ 'mg-tab--on': activeTab === t.id }" :aria-selected="activeTab === t.id" @click="setActiveTab(t.id)">
          <span aria-hidden="true">{{ t.icon }}</span> {{ t.label }}
        </button>
      </nav>

      <section v-if="activeTab === 'image'" class="mg-body">
        <label class="mg-field">
          <span>描述</span>
          <textarea v-model="imgPrompt" rows="3" class="mg-input mg-input--area" placeholder="例如：一只在赛博朋克城市夜景中漫步的橘猫，霓虹灯光反射，电影感构图" />
        </label>
        <div class="mg-row">
          <label class="mg-field mg-field--inline">
            <span>尺寸</span>
            <select v-model="imgSize" class="mg-input">
              <option value="1024x1024">1:1 (1024)</option>
              <option value="1024x1536">2:3 竖图</option>
              <option value="1536x1024">3:2 横图</option>
              <option value="768x1280">9:16 手机</option>
            </select>
          </label>
          <label class="mg-field mg-field--inline">
            <span>风格</span>
            <select v-model="imgStyle" class="mg-input">
              <option value="default">默认</option>
              <option value="photo">摄影</option>
              <option value="anime">二次元</option>
              <option value="3d">3D 渲染</option>
              <option value="ink">水墨</option>
            </select>
          </label>
          <label class="mg-field mg-field--inline">
            <span>数量</span>
            <select v-model.number="imgCount" class="mg-input">
              <option :value="1">1 张</option>
              <option :value="2">2 张</option>
              <option :value="4">4 张</option>
            </select>
          </label>
        </div>
        <div class="mg-foot">
          <button type="button" class="mg-btn mg-btn--primary" :disabled="busy || !imgPrompt.trim()" @click="onGenImage">
            {{ busy ? '生成中…' : '生成图片' }}
          </button>
          <button type="button" class="mg-btn mg-btn--ghost" @click="$emit('insert', currentImageInsertText)" :disabled="!previewImages.length">把结果插入对话</button>
        </div>
        <p v-if="error" class="mg-error" role="alert">{{ error }}</p>
        <div v-if="previewImages.length" class="mg-grid">
          <figure v-for="(u, i) in previewImages" :key="`img-${i}`" class="mg-grid__cell">
            <img :src="u" alt="生成图" class="mg-grid__img" />
            <figcaption class="mg-grid__cap">
              <a :href="u" target="_blank" rel="noopener noreferrer">在新标签查看</a>
            </figcaption>
          </figure>
        </div>
        <p v-else-if="!busy" class="mg-tip">可视化效果取决于后端供应商；当前演示模式会以「占位图 + 文本说明」形式返回，便于把生成入口先打通。</p>
      </section>

      <section v-else-if="activeTab === 'video'" class="mg-body">
        <label class="mg-field">
          <span>描述</span>
          <textarea v-model="videoPrompt" rows="3" class="mg-input mg-input--area" placeholder="例如：产品特写镜头缓慢旋转，柔光背景，15 秒广告片风格" />
        </label>
        <div class="mg-row">
          <label class="mg-field mg-field--inline">
            <span>画幅</span>
            <select v-model="videoAspect" class="mg-input">
              <option value="16:9">16:9 横屏</option>
              <option value="9:16">9:16 竖屏</option>
              <option value="1:1">1:1 方形</option>
            </select>
          </label>
          <label class="mg-field mg-field--inline">
            <span>时长</span>
            <select v-model.number="videoDurationSec" class="mg-input">
              <option :value="5">约 5 秒</option>
              <option :value="10">约 10 秒</option>
              <option :value="15">约 15 秒</option>
            </select>
          </label>
        </div>
        <div class="mg-foot">
          <button type="button" class="mg-btn mg-btn--primary" :disabled="busy || !videoPrompt.trim()" @click="onGenVideo">
            {{ busy ? '提交中…' : '生成视频' }}
          </button>
          <button type="button" class="mg-btn mg-btn--ghost" @click="$emit('insert', videoInsertText)" :disabled="!videoResultText">把说明插入对话</button>
        </div>
        <p v-if="error" class="mg-error" role="alert">{{ error }}</p>
        <pre v-if="videoResultText" class="mg-outline">{{ videoResultText }}</pre>
        <p v-else-if="!busy" class="mg-tip">视频生成依赖已配置的视频模型；演示模式会先返回任务说明，接入供应商后可在此预览成片。</p>
      </section>

      <section v-else-if="activeTab === 'ppt'" class="mg-body">
        <label class="mg-field">
          <span>主题</span>
          <input v-model="pptTopic" type="text" class="mg-input" maxlength="80" placeholder="例如：成都火锅品牌的全国扩张策略" />
        </label>
        <label class="mg-field">
          <span>受众 / 风格</span>
          <input v-model="pptAudience" type="text" class="mg-input" maxlength="80" placeholder="例如：投资人路演 + 极简商务风" />
        </label>
        <label class="mg-field mg-field--inline">
          <span>页数</span>
          <select v-model.number="pptPages" class="mg-input">
            <option :value="6">6 页（速汇报）</option>
            <option :value="10">10 页（标准）</option>
            <option :value="16">16 页（详尽）</option>
          </select>
        </label>
        <div class="mg-foot">
          <button type="button" class="mg-btn mg-btn--primary" :disabled="busy || !pptTopic.trim()" @click="onGenPpt">
            {{ busy ? '生成中…' : '生成 PPT 大纲' }}
          </button>
          <button type="button" class="mg-btn mg-btn--ghost" @click="$emit('insert', pptOutlineText)" :disabled="!pptOutlineText">把大纲插入对话</button>
          <a
            v-if="pptDownloadUrl"
            class="mg-btn mg-btn--download"
            :href="pptDownloadUrl"
            :download="pptFilename"
          >下载 PPT 文件</a>
        </div>
        <p v-if="error" class="mg-error" role="alert">{{ error }}</p>
        <pre v-if="pptOutlineText" class="mg-outline">{{ pptOutlineText }}</pre>
        <p v-else-if="!busy" class="mg-tip">演示版会调用同一个 LLM 生成 markdown 风格的大纲，包含每页标题、要点、讲解词；后续可换为真正的 PPT 引擎。</p>
      </section>

      <section v-else class="mg-body">
        <label class="mg-field">
          <span>文档类型</span>
          <select v-model="docKind" class="mg-input">
            <option value="weekly">周报</option>
            <option value="proposal">方案 / 提案</option>
            <option value="article">公众号文章</option>
            <option value="redbook">小红书种草</option>
            <option value="email">商务邮件</option>
          </select>
        </label>
        <label class="mg-field">
          <span>关键信息（自由填）</span>
          <textarea v-model="docInputs" rows="4" class="mg-input mg-input--area" placeholder="例如：本周完成 A/B 测试，转化率提升 12%；接下来要推渠道合作；目标受众…" />
        </label>
        <div class="mg-foot">
          <button type="button" class="mg-btn mg-btn--primary" :disabled="busy || !docInputs.trim()" @click="onGenDoc">
            {{ busy ? '生成中…' : '生成文稿' }}
          </button>
          <button type="button" class="mg-btn mg-btn--ghost" @click="$emit('insert', docText)" :disabled="!docText">插入对话</button>
        </div>
        <p v-if="error" class="mg-error" role="alert">{{ error }}</p>
        <pre v-if="docText" class="mg-outline">{{ docText }}</pre>
        <p v-else-if="!busy" class="mg-tip">把生成结果当成草稿，建议在对话里继续要求改稿；任何文案润色都比从零开写省时间。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

export type MediaGenTabId = 'image' | 'video' | 'ppt' | 'doc'

export interface MediaGenVideoResult {
  status: 'pending' | 'done'
  message: string
  previewUrl?: string
}

export interface MediaGenRunner {
  /** 生图：返回 N 张 url（演示版可返回占位图 / data:url） */
  generateImages: (prompt: string, opts: { size: string; style: string; count: number }) => Promise<string[]>
  /** 生视频：演示版返回任务说明；接入后返回 previewUrl */
  generateVideo?: (prompt: string, opts: { aspect: string; durationSec: number }) => Promise<MediaGenVideoResult>
  /** 生 PPT 大纲：返回 markdown 文本 */
  generatePptOutline: (topic: string, audience: string, pages: number) => Promise<string>
  /** 把 markdown 大纲转成真正 .pptx 文件 */
  generatePptx?: (topic: string, markdown: string) => Promise<Blob>
  /** 生文档：返回 markdown 文本 */
  generateDocument: (kind: string, inputs: string) => Promise<string>
}

const props = defineProps<{
  open: boolean
  runner: MediaGenRunner
  initialTab?: MediaGenTabId
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'insert', text: string): void
}>()

const tabs: ReadonlyArray<{ id: MediaGenTabId; label: string; icon: string }> = [
  { id: 'image', label: '生图', icon: '🖼️' },
  { id: 'video', label: '生视频', icon: '🎬' },
  { id: 'ppt', label: '生 PPT', icon: '📊' },
  { id: 'doc', label: '生文档', icon: '📝' },
]

const activeTab = ref<MediaGenTabId>('image')

const panelTitle = computed(() => {
  if (activeTab.value === 'image') return '生图'
  if (activeTab.value === 'video') return '生视频'
  if (activeTab.value === 'ppt') return '生 PPT'
  return '生文档'
})

function setActiveTab(id: MediaGenTabId) {
  activeTab.value = id
}

watch(
  () => [props.open, props.initialTab] as const,
  ([open, tab]) => {
    if (open && tab) activeTab.value = tab
  },
)
const busy = ref(false)
const error = ref('')

const imgPrompt = ref('')
const imgSize = ref('1024x1024')
const imgStyle = ref('default')
const imgCount = ref(1)
const previewImages = ref<string[]>([])

const videoPrompt = ref('')
const videoAspect = ref('16:9')
const videoDurationSec = ref(10)
const videoResultText = ref('')

const pptTopic = ref('')
const pptAudience = ref('')
const pptPages = ref(10)
const pptOutlineText = ref('')
const pptDownloadUrl = ref('')
const pptFilename = ref('ai-presentation.pptx')

const docKind = ref('weekly')
const docInputs = ref('')
const docText = ref('')

const currentImageInsertText = computed(() => {
  if (!previewImages.value.length) return ''
  const md = previewImages.value
    .map((u, i) => `![生成图${i + 1}](${u})`)
    .join('\n')
  return `（AI 生图）${imgPrompt.value.trim()}\n\n${md}`
})

const videoInsertText = computed(() => {
  if (!videoResultText.value) return ''
  return `（AI 生视频）${videoPrompt.value.trim()}\n\n${videoResultText.value}`
})

async function onGenImage() {
  if (!imgPrompt.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const urls = await props.runner.generateImages(imgPrompt.value.trim(), {
      size: imgSize.value,
      style: imgStyle.value,
      count: imgCount.value,
    })
    previewImages.value = Array.isArray(urls) ? urls : []
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    busy.value = false
  }
}

async function onGenVideo() {
  if (!videoPrompt.value.trim() || busy.value) return
  if (!props.runner.generateVideo) {
    error.value = '当前环境未配置视频生成能力'
    return
  }
  busy.value = true
  error.value = ''
  videoResultText.value = ''
  try {
    const res = await props.runner.generateVideo(videoPrompt.value.trim(), {
      aspect: videoAspect.value,
      durationSec: videoDurationSec.value,
    })
    const lines = [res.message]
    if (res.previewUrl) lines.push(`预览：${res.previewUrl}`)
    videoResultText.value = lines.filter(Boolean).join('\n\n')
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    busy.value = false
  }
}

async function onGenPpt() {
  if (!pptTopic.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  if (pptDownloadUrl.value) URL.revokeObjectURL(pptDownloadUrl.value)
  pptDownloadUrl.value = ''
  try {
    pptOutlineText.value = await props.runner.generatePptOutline(pptTopic.value.trim(), pptAudience.value.trim(), pptPages.value)
    if (props.runner.generatePptx && pptOutlineText.value.trim()) {
      const blob = await props.runner.generatePptx(pptTopic.value.trim(), pptOutlineText.value)
      pptFilename.value = `${pptTopic.value.trim().slice(0, 32) || 'ai-presentation'}.pptx`
      pptDownloadUrl.value = URL.createObjectURL(blob)
    }
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    busy.value = false
  }
}

async function onGenDoc() {
  if (!docInputs.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    docText.value = await props.runner.generateDocument(docKind.value, docInputs.value.trim())
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => {
  if (pptDownloadUrl.value) URL.revokeObjectURL(pptDownloadUrl.value)
})
</script>

<style scoped>
.mg-mask {
  position: fixed;
  inset: 0;
  z-index: 75;
  background: rgba(2, 6, 23, 0.78);
  display: grid;
  place-items: center;
  padding: 1rem;
  backdrop-filter: blur(6px);
}

.mg-card {
  width: min(46rem, 100%);
  max-height: 92vh;
  overflow-y: auto;
  padding: 1.05rem 1.4rem 1.5rem;
  background: rgba(15, 23, 42, 0.97);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.95rem;
  color: #e2e8f0;
}

.mg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.65rem;
}

.mg-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
}

.mg-x {
  width: 2rem;
  height: 2rem;
  border-radius: 0.45rem;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  font-size: 1.1rem;
}

.mg-tabs {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.85rem;
}

.mg-tab {
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.5);
  color: rgba(226, 232, 240, 0.78);
  font-size: 0.82rem;
  cursor: pointer;
}

.mg-tab--on {
  background: rgba(99, 102, 241, 0.32);
  border-color: rgba(165, 180, 252, 0.55);
  color: #fff;
}

.mg-body {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.mg-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.82rem;
  color: rgba(226, 232, 240, 0.85);
}

.mg-field--inline {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

.mg-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}

.mg-input {
  padding: 0.45rem 0.65rem;
  background: rgba(2, 6, 23, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  border-radius: 0.45rem;
  font-family: inherit;
}

.mg-input--area {
  resize: vertical;
  min-height: 4.5rem;
}

.mg-input:focus {
  outline: none;
  border-color: rgba(129, 140, 248, 0.55);
}

.mg-foot {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.4rem;
}

.mg-btn {
  padding: 0.45rem 0.85rem;
  border-radius: 0.45rem;
  cursor: pointer;
  font-size: 0.82rem;
  border: 1px solid transparent;
}

.mg-btn--primary {
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.55), rgba(99, 102, 241, 0.75));
  color: #fff;
  border-color: rgba(165, 180, 252, 0.55);
}

.mg-btn--primary:disabled { opacity: 0.45; cursor: not-allowed; }

.mg-btn--ghost {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.86);
  border-color: rgba(255, 255, 255, 0.1);
}

.mg-btn--ghost:disabled { opacity: 0.45; cursor: not-allowed; }
.mg-btn--ghost:not(:disabled):hover { background: rgba(255, 255, 255, 0.1); }

.mg-btn--download {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
  background: rgba(45, 212, 191, 0.18);
  border-color: rgba(45, 212, 191, 0.35);
  color: #5eead4;
}

.mg-btn--download:hover {
  background: rgba(45, 212, 191, 0.3);
}

.mg-error {
  margin: 0.4rem 0 0;
  font-size: 0.8rem;
  color: rgba(252, 165, 165, 0.95);
}

.mg-tip {
  margin: 0.4rem 0 0;
  font-size: 0.78rem;
  color: rgba(203, 213, 225, 0.6);
}

.mg-grid {
  display: grid;
  gap: 0.6rem;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
  margin-top: 0.6rem;
}

.mg-grid__cell {
  margin: 0;
  padding: 0.4rem;
  background: rgba(2, 6, 23, 0.6);
  border-radius: 0.55rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.mg-grid__img {
  width: 100%;
  border-radius: 0.4rem;
  display: block;
}

.mg-grid__cap {
  margin: 0.3rem 0 0;
  font-size: 0.74rem;
  color: rgba(203, 213, 225, 0.65);
  text-align: right;
}

.mg-grid__cap a {
  color: #93c5fd;
  text-decoration: none;
}

.mg-outline {
  margin: 0.55rem 0 0;
  padding: 0.6rem 0.8rem;
  background: rgba(2, 6, 23, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.55rem;
  color: #e2e8f0;
  font-size: 0.84rem;
  white-space: pre-wrap;
  font-family: inherit;
  max-height: 22rem;
  overflow: auto;
}
</style>
