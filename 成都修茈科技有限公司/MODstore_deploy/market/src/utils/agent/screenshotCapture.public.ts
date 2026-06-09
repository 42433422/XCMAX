/**
 * 截图模块公开 API 入口 (Docking Contract v1.1)
 *
 * 下游 (LLM 服务端 / 其它 feature / 测试) 唯一推荐 import 路径。
 *
 * @example
 *   import { captureViewport, invalidateCaptureCache, onCaptureMeta } from '@/utils/agent/screenshotCapture.public'
 *   import type { CaptureResult, CaptureOptions, VisionDetail } from '@/utils/agent/screenshotCapture.public'
 *
 * @module screenshotCapture.public
 * @see ./screenshotCapture.types 契约层 (类型 / 枚举 / 回调签名)
 * @see ./screenshotCapture        实现层 (内部后端 / 缓存)
 */

export type {
  // 核心判别联合
  CaptureResult,
  CaptureOptions,
  // 失败分类
  CaptureFailureReason,
  CaptureFailureSeverity,
  // 后端
  ScreenshotBackend,
  // vision detail (OpenAI 兼容 API)
  VisionDetail,
  // meta + 回调
  CaptureMeta,
  CaptureMetaListener,
} from './screenshotCapture.types'

// 公开函数：从实现模块 re-export，下游不必再 import 内部路径
export {
  captureViewport,
  invalidateCaptureCache,
  onCaptureMeta,
} from './screenshotCapture'
