/**
 * Agents' context gauges, shared by the label over each character
 * (ToolOverlay) and the bar along the foot of each agent card (AgentCard).
 * The fill is the context LEFT, like a health bar; the colour warns by the
 * share used, in the steps of the user's Claude Code status line.
 */


import {
  CONTEXT_GAUGE_COLOR_OK,
  CONTEXT_GAUGE_COLOR_RED,
  CONTEXT_GAUGE_COLOR_YELLOW,
  CONTEXT_RED_THRESHOLD,
  CONTEXT_YELLOW_THRESHOLD,
} from '../constants.js';

/** The gauge colour for a share of the context used (0-1). */
export function contextColor(usedRatio: number): string {
  if (usedRatio > CONTEXT_RED_THRESHOLD) return CONTEXT_GAUGE_COLOR_RED;
  if (usedRatio >= CONTEXT_YELLOW_THRESHOLD) return CONTEXT_GAUGE_COLOR_YELLOW;
  return CONTEXT_GAUGE_COLOR_OK;
}

/** Share of the context left (0-1), what the gauge fills: a health bar. */
export function contextLeft(usedRatio: number): number {
  return Math.max(0, 1 - usedRatio);
}

/**
 * The share of the context used (0-1) that an agentContextUsage reports, or
 * null when it says nothing usable. 0 tokens is a real reading — the session
 * was just cleared — and shows as a full gauge: the server never sends the
 * meaningless all-zero usage records.
 */
export function contextUsedShare(contextTokens: number, maxTokens: number): number | null {
  if (!Number.isFinite(contextTokens) || contextTokens < 0 || !(maxTokens > 0)) return null;
  return Math.min(1, contextTokens / maxTokens);
}
