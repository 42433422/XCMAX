import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';

void main() {
  test('home shell exposes the stable Flutter navigation contract', () {
    expect(flutterHomeShellBottomNavItemsForTest(), [
      {'route': 'chat', 'label': '消息'},
      {'route': 'work', 'label': 'AI员工'},
      {'route': 'discover', 'label': '探索'},
      {'route': 'profile', 'label': '我'},
    ]);
  });
}
