/**
 * 截图模块公开契约 (Docking Contract v1.1)
 *
 * 这是下游（LLM 服务端 / agent 调用方 / 其它 feature）唯一应该 import 的
 * 类型来源。**不要从 ``screenshotCapture.ts`` 内部导出的类型入手**——那些
 * 符号属于模块内部实现，会被重构。本文件保证：
 *
 *   1. 类型稳定（不依赖模块内部状态 / 不随实现切换而漂移）
 *   2. 跨语言可读（每个字段都有 JSDoc 解释，Python 服务端能照着写 dataclass）
 *   3. 失败路径有兜底（reason 枚举 + severity + textFallback 三件套）
 *
 * 真实截图实现见 ``./screenshotCapture``，公开 API 见 ``./screenshotCapture.public``。
 *
 * @module screenshotCapture.types
 * @see ./screenshotCapture.public  公开 API 入口（推荐从这 import 函数）
 * @see ./screenshotCapture        内部实现（含私有后端、缓存、解析逻辑）
 */

/**
 * 失败原因枚举——保持稳定，下游 telemetry 按这个分桶。
 * 增删都视为 breaking change，**主版本号 +1**。
 */
export type CaptureFailureReason =
  /** 跨域图片未带 crossorigin → canvas 被 taint */
  | 'cors'
  /** Content-Security-Policy 拒绝 html2canvas 注入 */
  | 'csp'
  /** 浏览器无 document.body / 非 DOM 环境（SSR / happy-dom 限制） */
  | 'unsupported'
  /** html2canvas 自身渲染失败（DOM 太复杂 / 未知错误） */
  | 'render'
  /** 内存不足 / 分配失败（大节点树常见） */
  | 'memory'
  /** html2canvas 渲染超时 */
  | 'timeout'
  /** 调用方主动取消（外部 AbortSignal 触发） */
  | 'aborted'
  /** 未知 backend 值 */
  | 'no_backend'

/**
 * 严重等级——辅助 telemetry 报警/降级策略。
 * - critical: 截图不可用且无 textFallback，LLM 链路拿不到任何页面信息
 * - degraded: 截图失败但有 textFallback，LLM 降级到纯文本可用
 * - transient: 临时性失败（CORS / memory / timeout），可考虑自动重试
 * - user:     用户主动操作（aborted），非系统问题
 */
export type CaptureFailureSeverity = 'critical' | 'degraded' | 'transient' | 'user'

/**
 * 截图后端选择。
 * - html2canvas:  像素输出 (data:image/jpeg;base64,...)
 * - dom-snapshot: 文本输出 (data:application/json;base64,...)，
 *                  永远不 CORS / CSP / 失败，适合作为兜底
 */
export type ScreenshotBackend = 'html2canvas' | 'dom-snapshot'

/**
 * OpenAI 兼容 vision API 的 detail 参数——控制 LLM 看到的图片分辨率。
 * - low:    85 token per image（默认，省钱）
 * - high:   170 token（精细但贵）
 * - auto:   765 token（让模型自行决定）
 *
 * 暴露给调用方是因为 token 成本/准确率取舍是业务问题，不是技术问题。
 */
export type VisionDetail = 'low' | 'high' | 'auto'

/**
 * CaptureResult 判别联合：
 *
 *   ok: true,  kind: 'image'         → 高质量图片
 *   ok: true,  kind: 'text-snapshot' → 零依赖文本快照
 *   ok: false, reason: ...           → 失败（可能附带 textFallback）
 *
 * 设计要点：
 * - 失败**必须**返回 { ok: false, reason } 而非抛错——下游 LLM 链路需要区分
 *   "无截图" 和 "截图失败"，否则会拿空上下文硬跑。
 * - severity 字段是 fail 路径的 severity（success 路径下为 undefined）。
 * - noteTruncated 字段标记 textFallback 是否被截断，下游 LLM 可据此判断
 *   "这是完整 DOM 还是被切了"。
 */
export type CaptureResult =
  | {
      ok: true
      kind: 'image'
      /** data URL，可直接喂 OpenAI image_url */
      dataUrl: string
      /** base64 解码后字节数（精确匹配 JPEG 实际大小） */
      bytes: number
      /** 第二次调用是否命中模块级 LRU 缓存 */
      fromCache?: boolean
      /** 后端实际使用的值（与请求 backend 一致或因 fallback 不同） */
      backend: ScreenshotBackend
      /** 渲染耗时（含 html2canvas，不含缓存命中） */
      elapsedMs?: number
      reason?: undefined
      textFallback?: undefined
      severity?: undefined
      noteTruncated?: undefined
    }
  | {
      ok: true
      kind: 'text-snapshot'
      dataUrl: string
      bytes: number
      fromCache?: boolean
      backend: ScreenshotBackend
      elapsedMs?: number
      reason?: undefined
      textFallback?: undefined
      severity?: undefined
      noteTruncated?: undefined
    }
  | {
      ok: false
      kind?: undefined
      dataUrl?: undefined
      reason: CaptureFailureReason
      /** 详细错误信息（html2canvas 内部抛出原文） */
      message?: string
      /** 严重等级（telemetry 报警 / 自动降级策略用） */
      severity: CaptureFailureSeverity
      /** 自动附带的可见 DOM 文本——下游可降级到纯文本 LLM 链路 */
      textFallback?: string
      /** textFallback 是否被截断（长度超过 noteMaxLen） */
      noteTruncated?: boolean
      /** textFallback 原始长度（截断前），用于 LLM 评估"是否丢失上下文" */
      noteOriginalLength?: number
      fromCache?: boolean
      backend: ScreenshotBackend
      elapsedMs?: number
    }

/**
 * CaptureOptions：调用方可调的旋钮。
 * 大多数字段都有合理默认值，只在需要偏离时显式传。
 */
export interface CaptureOptions {
  /** 跳过截图的元素 CSS 选择器列表。仅 html2canvas 生效。
   * 默认 ``['.butler-float-root']`` 排除浮窗管家自身。 */
  ignoreSelectors?: string[]

  /** 缩放比，默认 0.5（适合 LLM vision detail=low）。仅 html2canvas 生效。 */
  scale?: number

  /** JPEG 质量 0-1，默认 0.7。仅 html2canvas 生效。 */
  quality?: number

  /** 取消信号——用户切走/重新发消息时调用 .abort()，渲染立即中断 */
  signal?: AbortSignal

  /** 后端选择，默认 'html2canvas' */
  backend?: ScreenshotBackend

  /** 路由签名：用于缓存 key。默认取 ``window.location.pathname``。
   * 推荐显式传 ``route.fullPath`` 以避免 SPA 内子路由命中陈旧截图 */
  routeSig?: string

  /** 启用模块级 LRU 缓存，默认 true */
  enableCache?: boolean

  /** 缓存 TTL 毫秒，默认 30000。
   * 30s 经验值：用户连发消息场景下避免重复渲染；超过 30s 视作"用户可能去
   * 别的页面了"自动失效 */
  cacheTtlMs?: number

  /** 失败时自动调用 ``serializeVisibleDom()`` 附 ``textFallback``，默认 true。
   * 设为 false 可节省 DOM 序列化开销（前提是上游已有备用上下文） */
  autoTextFallback?: boolean

  /** textFallback / text-snapshot 进 LLM 前的最大字符数，默认 1500。
   * 超过会被截断并加 ``[已截断 共 N 字符]`` 边界标界 */
  noteMaxLen?: number

  /** html2canvas 渲染的最大重试次数（仅限 transient 失败：cors/memory/timeout）。
   * 默认 0——保守起见不重试。生产可设 1~2。 */
  retry?: number

  /** 强制忽略缓存重跑（即使命中也跑一遍）。
   * 用法：用户点击"重新截图"按钮、或在测试里绕过缓存。 */
  forceRetake?: boolean

  /** 渲染过程中报错时是否主动释放 canvas 内存。
   * 默认 true——大页面（6000px）单张 canvas 31MB，不释放会撑爆移动端。
   * 调用方手动管 canvas 的场景可关掉。 */
  releaseCanvasOnDone?: boolean
}

/**
 * CaptureResult 元数据——所有成功 / 失败结果都带。
 * 不进 LLM 链路（不进 prompt），用于 telemetry / 调试。
 */
export interface CaptureMeta {
  /** 调用起止耗时（毫秒，含缓存查询） */
  elapsedMs: number
  /** 后端实际使用 */
  backend: ScreenshotBackend
  /** 是否命中缓存 */
  fromCache: boolean
  /** 失败时：textFallback 是否被截断 */
  noteTruncated?: boolean
  /** 失败时：textFallback 原始长度 */
  noteOriginalLength?: number
}

/**
 * 公开回调：模块内部 telemetry 上报钩子。
 * 下游（sentry / 业务埋点）可注册 ``onCaptureMeta`` 监听每次结果。
 *
 * 设计意图：模块不该隐式上报，但**必须**给下游一个观测点。
 * 默认 noop，调用方按需注册。
 */
export type CaptureMetaListener = (result: CaptureResult, meta: CaptureMeta) => void
