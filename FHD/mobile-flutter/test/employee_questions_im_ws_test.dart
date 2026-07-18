import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/employee_pending_question.dart';
import 'package:xcagi_flutter_poc/src/im/im_websocket_client.dart';

void main() {
  test('EmployeePendingQuestion maps Flutter pending question payload', () {
    final question = EmployeePendingQuestion.fromJson({
      'id': 7,
      'employee_id': 'llm-ops-engineer',
      'task': '整理发版清单',
      'question': '是否现在推送 v10 热修？',
      'status': 'pending',
      'answer': '',
      'asked_at': '2026-07-07',
      'answered_at': '',
      'expires_at': '',
    });

    expect(question.id, 7);
    expect(question.employeeId, 'llm-ops-engineer');
    expect(question.isPending, isTrue);
    expect(question.statusLabel, '待回答');
  });

  test('ImWebSocketClient parses im.message events', () {
    final event = ImWebSocketClient.parseMessageEvent({
      'type': 'im.message',
      'conversation_id': 12,
      'message': {'id': 99, 'sender_user_id': 3, 'body': '你好'},
    });

    expect(event, isNotNull);
    expect(event!.conversationId, 12);
    expect(event.messageId, 99);
    expect(event.body, '你好');
  });
}
