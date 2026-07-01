import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/demo_data.dart';
import 'package:xcagi_flutter_poc/src/data/duty_roster_ssot.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

void main() {
  test('admin duty roster fallback keeps Android employee count', () {
    final employeeItems = demoConversations
        .where((item) => item.type == ConversationType.aiTask)
        .toList(growable: false);

    expect(plannedAdminEmployeeCount, 55);
    expect(adminDutyRosterEmployees, hasLength(plannedAdminEmployeeCount));
    expect(employeeItems, hasLength(plannedAdminEmployeeCount));
  });
}
