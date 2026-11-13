import '../api/mobile_api.dart';

/// 把任意异常转换成用户能看懂的中文提示。
String mobileErrorText(
  Object? error, {
  String fallback = '操作失败，请稍后重试',
}) {
  if (error == null) return fallback;
  if (error is MobileApiException) {
    return mobileProductErrorMessage(
      'HTTP ${error.statusCode} ${error.message}',
      fallback,
    );
  }
  return mobileProductErrorMessage(error.toString(), fallback);
}

/// 移动端错误文案策略：按 HTTP 状态码区分登录失效、权限、版本差异、冲突和限流。
String mobileProductErrorMessage(String? raw, String fallback) {
  final message = (raw ?? '').trim();
  final lower = message.toLowerCase();
  final status = _httpStatusFromMessage(message);

  switch (status) {
    case 400:
      return '配对码无效或已过期，请在电脑端刷新二维码后重试';
    case 401:
      return '登录已过期，请重新登录或重新扫码绑定';
    case 403:
      return '当前账号没有权限，请切换账号或重新绑定';
    case 404:
      // 404 既可能是资源不存在，也可能是旧客户端调用了新版本才有的接口。
      return '接口或数据不存在，可能是客户端与服务端版本不一致，请更新后重试';
    case 409:
      return '数据已被他人更新，请刷新后重试';
    case 422:
      return '提交的内容有误，请检查后重试';
    case 429:
      return '请求过于频繁，请稍后重试';
    case 500:
    case 502:
    case 503:
    case 504:
      return '服务器暂时不可用，请稍后重试';
  }

  if (message.contains('未授权')) {
    return '登录已过期，请重新登录或重新扫码绑定';
  }
  if (message.contains('配对码无效') || message.contains('缺少配对码')) {
    return '配对码无效或已过期，请在电脑端刷新二维码后重试';
  }
  if (message.contains('拒绝') ||
      message.contains('权限不足') ||
      message.contains('无权')) {
    return '当前账号没有权限，请切换账号或重新绑定';
  }
  if (lower.contains('handshake') ||
      lower.contains('certificate') ||
      lower.contains('tls') ||
      lower.contains('ssl')) {
    return '无法安全连接服务器，请检查网络后重试';
  }
  if (lower.contains('sockettexception') ||
      lower.contains('failed host lookup') ||
      lower.contains('network is unreachable') ||
      lower.contains('connection refused') ||
      lower.contains('connection reset') ||
      lower.contains('broken pipe')) {
    return '网络连接失败，请检查网络后重试';
  }
  if (lower.contains('timeout') || lower.contains('timed out')) {
    return '网络超时，请稍后重试';
  }
  if (lower.contains('connection terminated') ||
      lower.contains('connection closed') ||
      lower.contains('httpexception') ||
      lower.contains('software caused connection abort')) {
    return '服务器连接中断，请稍后重试';
  }
  if (lower.contains('formatexception') ||
      lower.contains('unexpected character')) {
    return '服务器返回内容异常，请稍后重试';
  }
  if (lower.contains('failed to connect') || lower.contains('connect')) {
    return '连接不到电脑工具，已尝试通过云端中继，请稍后重试';
  }
  if (lower.contains('firebase') || lower.contains('fcm')) {
    return '消息提醒未开启，不影响登录和员工同步';
  }
  if (message.isEmpty || message.length > 80) return fallback;
  // 未识别的英文或技术报错不直接展示给用户。
  if (!_containsChinese(message)) return fallback;
  return message;
}

bool _containsChinese(String text) => RegExp(r'[\u4e00-\u9fa5]').hasMatch(text);

int? _httpStatusFromMessage(String message) {
  final match = RegExp(
    r'\b(400|401|403|404|409|422|429|500|502|503|504)\b',
  ).firstMatch(message);
  if (match == null) return null;
  return int.tryParse(match.group(1) ?? '');
}
