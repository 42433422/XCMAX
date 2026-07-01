import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/policy/android_error_policy.dart';

void main() {
  test('Android product error policy mirrors AppViewModel productErrorMessage',
      () {
    expect(
      androidProductErrorMessage('401 Unauthorized', 'fallback'),
      '登录已过期，请重新登录或重新扫码绑定',
    );
    expect(
      androidProductErrorMessage('请求被拒绝', 'fallback'),
      '当前账号没有权限，请切换到管理员账号或重新绑定后台',
    );
    expect(
      androidProductErrorMessage('failed to connect to desktop', 'fallback'),
      '连接不到电脑执行端，已尝试通过服务器中继，请稍后重试',
    );
    expect(
      androidProductErrorMessage('FCM registration missing', 'fallback'),
      '消息提醒未开启，不影响登录和员工同步',
    );
    expect(androidProductErrorMessage('', 'fallback'), 'fallback');
    expect(androidProductErrorMessage('服务繁忙', 'fallback'), '服务繁忙');
    expect(
      androidProductErrorMessage('x' * 81, 'fallback'),
      'fallback',
    );
  });
}
