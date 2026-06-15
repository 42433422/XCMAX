/** 智能对话消息渲染辅助（ChatMessageList / FloatingChatAssistant 共用）。 */

import type { ChatMessage } from '@/composables/useChatMessages'
import {
  extractToolInvocationChips,
  hasVisibleChatBubbleBody,
  isStreamingPlaceholderBody,
} from '@/utils/chatBubbleDisplay'

export function hasAiMessageSidecar(msg: ChatMessage): boolean {
  if (msg.role !== 'ai') return false
  if (msg.toolProgressLabel || msg.downloadUrl || msg.shipmentDownloadUrl) return true
  if (msg.contextSummary || msg.thinkingSteps) return true
  if (msg.todoSteps && msg.todoSteps.length) return true
  if (msg.workflowAction || (msg.nodeResults && msg.nodeResults.length)) return true
  return extractToolInvocationChips(msg.content).length > 0
}

export function isAiStreamingTail(
  messages: ChatMessage[],
  idx: number,
  isStreamingReply: boolean,
): boolean {
  return isStreamingReply && idx === messages.length - 1
}

/** 流式等待首 token：仅展示打字动画，不渲染空白气泡。 */
export function isAiTypingOnly(
  msg: ChatMessage,
  idx: number,
  messages: ChatMessage[],
  isStreamingReply: boolean,
): boolean {
  if (msg.role !== 'ai') return false
  if (!isAiStreamingTail(messages, idx, isStreamingReply)) return false
  return !hasVisibleChatBubbleBody(msg.content) && !hasAiMessageSidecar(msg)
}

export function shouldRenderChatMessageRow(
  msg: ChatMessage,
  idx: number,
  messages: ChatMessage[],
  isStreamingReply: boolean,
): boolean {
  if (msg.role !== 'ai') return true
  if (isAiTypingOnly(msg, idx, messages, isStreamingReply)) return true
  if (hasVisibleChatBubbleBody(msg.content)) return true
  if (hasAiMessageSidecar(msg)) return true
  if (isStreamingPlaceholderBody(msg.content)) return false
  return false
}
