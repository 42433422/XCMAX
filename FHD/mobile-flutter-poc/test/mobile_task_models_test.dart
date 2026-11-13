import 'package:flutter_test/flutter_test.dart';

import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';

void main() {
  test('mobile task list parses unified task summary', () {
    final data = MobileTaskListData.fromJson(const {
      'items': [
        {
          'task_id': 'task-1',
          'title': '整理本周考勤',
          'status': 'running',
          'attention_state': 'approval_required',
          'approval_required': true,
          'execution_target': 'desktop:mac-1',
          'progress_percent': 42,
          'workspace_id': 'desktop:mac-1',
          'conversation_id': 'employee:attendance',
          'updated_at': '2026-11-13T10:00:00',
        },
      ],
      'count': 1,
    });

    expect(data.count, 1);
    expect(data.items.single.taskId, 'task-1');
    expect(data.items.single.approvalRequired, isTrue);
    expect(data.items.single.executionTarget, 'desktop:mac-1');
    expect(data.items.single.progressPercent, 42);
  });

  test('mobile task list tolerates missing fields', () {
    final data = MobileTaskListData.fromJson(const {
      'items': [
        {'task_id': 'task-2'},
      ],
    });

    expect(data.items.single.title, '');
    expect(data.items.single.progressPercent, 0);
    expect(data.count, 1);
  });
}
