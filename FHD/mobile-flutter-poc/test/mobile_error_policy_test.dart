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
      expect(
        mobileProductErrorMessage('MobileApiException(403): 权限不足', 'fallback'),
        '当前账号没有权限，请切换账号或重新绑定',
      );
      expect(
        mobileProductErrorMessage('MobileApiException(404): 接口不存在', 'fallback'),
        '接口或数据不存在，可能是客户端与服务端版本不一致，请更新后重试',
      );
      expect(
        mobileProductErrorMessage('MobileApiException(409): 任务状态冲突', 'fallback'),
        '数据已被他人更新，请刷新后重试',
      );
      expect(
        mobileProductErrorMessage(
          'MobileApiException(429, RATE_LIMITED, retry_after=5s): 请求过于频繁',
          'fallback',
        ),
        '请求过于频繁，请稍后重试',
      );
      expect(mobileProductErrorMessage('', 'fallback'), 'fallback');
      expect(mobileProductErrorMessage('服务繁忙', 'fallback'), '服务繁忙');
      expect(mobileProductErrorMessage('x' * 81, 'fallback'), 'fallback');
    },
  );

  test('network and server failures are shown in user-facing Chinese', () {
    expect(
      mobileProductErrorMessage(
        'HandshakeException: Connection terminated during handshake',
        'fallback',
      ),
      '无法安全连接服务器，请检查网络后重试',
    );
    expect(
      mobileProductErrorMessage('SocketException: Network is unreachable', 'fallback'),
      '网络连接失败，请检查网络后重试',
    );
    expect(
      mobileProductErrorMessage('TimeoutException after 0:00:10', 'fallback'),
      '网络超时，请稍后重试',
    );
    expect(
      mobileProductErrorMessage(
        'MobileApiException(500): Internal Server Error',
        'fallback',
      ),
      '服务器暂时不可用，请稍后重试',
    );
    expect(
      mobileProductErrorMessage('Internal Server Error', 'fallback'),
      'fallback',
    );
    expect(mobileErrorText(Exception('boom'), fallback: '登录失败'), '登录失败');
  });
}
