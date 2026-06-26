/** AI 群聊消息气泡 UI：按 kind/status 区分讨论、分工、派工、汇报与验收（含误验收待复核）。 */

export type AiGroupMessageKindUi = {
  badge: string;
  bubbleClass: string;
  needsReview: boolean;
};

export function resolveAiGroupMessageUi(
  kind?: string,
  status?: string,
  body?: string,
): AiGroupMessageKindUi {
  const k = String(kind || 'chat').trim().toLowerCase();
  const bodyText = String(body || '');

  if (k === 'discussion' || k === 'super_discussion') {
    return { badge: '讨论', bubbleClass: 'is-discussion', needsReview: false };
  }
  if (k === 'routing_decision') {
    return { badge: '分工', bubbleClass: 'is-routing', needsReview: false };
  }
  if (k === 'work_order') {
    return { badge: '派单', bubbleClass: 'is-work', needsReview: false };
  }
  if (k === 'work_report' || k === 'relay_work_report') {
    return { badge: '汇报', bubbleClass: 'is-work', needsReview: false };
  }
  if (k === 'work_acceptance') {
    const needsReview =
      String(status || '').trim().toLowerCase() === 'needs_review' || bodyText.includes('需要复核');
    return {
      badge: needsReview ? '待复核' : '可验收',
      bubbleClass: needsReview ? 'is-acceptance-review' : 'is-acceptance',
      needsReview,
    };
  }
  return { badge: '', bubbleClass: '', needsReview: false };
}

export function groupSendingLabel(dispatchMode: boolean): string {
  return dispatchMode ? '员工正在执行并汇报…' : 'AI 成员正在讨论并回复…';
}
