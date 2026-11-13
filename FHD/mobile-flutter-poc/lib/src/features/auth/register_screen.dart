import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../webview/desktop_tool_webview_screen.dart';

bool handleMobileRegisterUrlOverride(String nextUrl, VoidCallback onComplete) {
  if (!isMobileRegisterCompleteUrl(nextUrl)) return false;
  onComplete();
  return true;
}

class RegisterScreen extends StatelessWidget {
  const RegisterScreen({super.key, this.onLogin});

  final VoidCallback? onLogin;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 60, 24, 28),
          children: [
            Text(
              '账号注册',
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 24,
                height: 1.25,
                fontWeight: FontWeight.w700,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 18),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: colors.surfaceHigh,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.language, color: colors.textPrimary),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '网页登录表单',
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 15,
                        height: 1.4,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            SizedBox(
              height: 48,
              child: FilledButton(
                onPressed: () => _openWebForm(context),
                child: const Text('去网页填写注册表单'),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 48,
              child: OutlinedButton(
                onPressed: onLogin ?? () => Navigator.of(context).maybePop(),
                child: const Text('返回登录'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openWebForm(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DesktopToolWebViewScreen(
          title: '注册',
          path: '/login/register?redirect=%2Fapp%2Fmobile-register-complete',
          onUrlOverride: (nextUrl) {
            return handleMobileRegisterUrlOverride(nextUrl, () {
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(const SnackBar(content: Text('注册完成，请使用新账号登录')));
              onLogin?.call();
              if (onLogin == null) {
                Navigator.of(context).popUntil((route) => route.isFirst);
              }
            });
          },
        ),
      ),
    );
  }
}
