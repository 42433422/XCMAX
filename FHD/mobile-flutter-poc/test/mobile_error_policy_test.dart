import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_error_policy.dart';

void main() {
  test(
    'Flutter product error policy mirrors AppViewModel productErrorMessage',
    () {
      expect(
        mobileProductErrorMessage('401 Unauthorized', 'fallback'),
        '登录已过期，请重新登录或重新扫码绑定',
      );
      expect(
        mobileProductErrorMessage('请求被拒绝', 'fallback'),
        '当前账号没有权限，请切换账号或重新绑定',
      );
      expect(
        mobileProductErrorMessage('failed to connect to desktop', 'fallback'),
        '连接不到电脑工具，已尝试通过云端中继，请稍后重试',
      );
      expect(
        mobileProductErrorMessage('FCM registration missing', 'fallback'),
        '消息提醒未开启，不影响登录和员工同步',
      );
      expect(mobileProductErrorMessage('', 'fallback'), 'fallback');
      expect(mobileProductErrorMessage('服务繁忙', 'fallback'), '服务繁忙');
      expect(mobileProductErrorMessage('x' * 81, 'fallback'), 'fallback');
    },
  );
}
