String androidProductErrorMessage(String? raw, String fallback) {
  final message = (raw ?? '').trim();
  final lower = message.toLowerCase();
  if (lower.contains('401') || message.contains('未授权')) {
    return '登录已过期，请重新登录或重新扫码绑定';
  }
  if (lower.contains('403') || message.contains('拒绝')) {
    return '当前账号没有权限，请切换到管理员账号或重新绑定后台';
  }
  if (lower.contains('failed to connect') ||
      lower.contains('timeout') ||
      lower.contains('connect')) {
    return '连接不到电脑执行端，已尝试通过服务器中继，请稍后重试';
  }
  if (lower.contains('firebase') || lower.contains('fcm')) {
    return '消息提醒未开启，不影响登录和员工同步';
  }
  if (message.isEmpty || message.length > 80) return fallback;
  return message;
}
