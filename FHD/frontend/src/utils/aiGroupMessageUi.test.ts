import { describe, expect, it } from 'vitest';
import { groupSendingLabel, resolveAiGroupMessageUi } from './aiGroupMessageUi';

describe('resolveAiGroupMessageUi', () => {
  it('marks discussion kinds', () => {
    expect(resolveAiGroupMessageUi('discussion')).toEqual({
      badge: '讨论',
      bubbleClass: 'is-discussion',
      needsReview: false,
    });
    expect(resolveAiGroupMessageUi('super_discussion').badge).toBe('讨论');
  });

  it('marks routing before owner assignment', () => {
    expect(resolveAiGroupMessageUi('routing_decision').badge).toBe('分工');
  });

  it('marks work order and reports', () => {
    expect(resolveAiGroupMessageUi('work_order').badge).toBe('派单');
    expect(resolveAiGroupMessageUi('work_report').badge).toBe('汇报');
    expect(resolveAiGroupMessageUi('relay_work_report').badge).toBe('汇报');
  });

  it('flags false acceptance as needs review', () => {
    const byStatus = resolveAiGroupMessageUi('work_acceptance', 'needs_review');
    expect(byStatus.badge).toBe('待复核');
    expect(byStatus.bubbleClass).toBe('is-acceptance-review');

    const byBody = resolveAiGroupMessageUi('work_acceptance', 'ok', '【小C验收】需要复核 0/2');
    expect(byBody.needsReview).toBe(true);
  });

  it('marks clean acceptance', () => {
    expect(resolveAiGroupMessageUi('work_acceptance', 'ok', '可以验收 2/2').badge).toBe('可验收');
  });
});

describe('groupSendingLabel', () => {
  it('differs between chat and dispatch', () => {
    expect(groupSendingLabel(false)).toContain('讨论');
    expect(groupSendingLabel(true)).toContain('执行');
  });
});
