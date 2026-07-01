import 'package:flutter/material.dart';

import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../scan/scan_qr_screen.dart';

class ConnectScreen extends StatelessWidget {
  const ConnectScreen({
    super.key,
    this.fromProfile = false,
    this.onNext,
    this.onScan,
    this.onSkipCloud,
    this.onBack,
  });

  final bool fromProfile;
  final VoidCallback? onNext;
  final VoidCallback? onScan;
  final VoidCallback? onSkipCloud;
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(title: 'Agent 远程控制', onBack: () => _back(context)),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(vertical: 40),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Image.asset(
                      appLauncherIconAsset,
                      width: 72,
                      height: 72,
                      fit: BoxFit.contain,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      key: const ValueKey('connect_title'),
                      'XCAGI 手机控制端',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 18,
                        height: 1.44,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0,
                      ),
                    ),
                    const SizedBox(height: 16),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 40),
                      child: Text(
                        key: const ValueKey('connect_description'),
                        '绑定服务器后台、企业工作台或电脑执行端后，手机可远程调动员工和 Codex。',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 14,
                          height: 1.36,
                          fontWeight: FontWeight.w400,
                          letterSpacing: 0,
                        ),
                      ),
                    ),
                    const SizedBox(height: 40),
                    _LoginButton(
                      text: '扫描绑定',
                      kind: _LoginButtonKind.primary,
                      onTap: () => _scan(context),
                    ),
                    const SizedBox(height: 16),
                    _LoginButton(
                      text: '返回',
                      kind: _LoginButtonKind.secondary,
                      onTap: () => _back(context),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _scan(BuildContext context) {
    final callback = onScan;
    if (callback != null) {
      callback();
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const ScanQrScreen()),
    );
  }

  void _back(BuildContext context) {
    final callback = onBack ?? onSkipCloud ?? onNext;
    if (callback != null) {
      callback();
      return;
    }
    Navigator.of(context).maybePop();
  }
}

enum _LoginButtonKind { primary, secondary }

class _LoginButton extends StatelessWidget {
  const _LoginButton({
    required this.text,
    required this.kind,
    required this.onTap,
  });

  final String text;
  final _LoginButtonKind kind;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final primary = kind == _LoginButtonKind.primary;
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Material(
        color: primary ? colors.brand : colors.surface,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Container(
            key: ValueKey(
              primary ? 'connect_primary_button' : 'connect_secondary_button',
            ),
            height: 48,
            width: double.infinity,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: primary
                  ? null
                  : Border.all(color: colors.divider, width: 0.5),
            ),
            alignment: Alignment.center,
            child: Text(
              text,
              style: TextStyle(
                color:
                    primary ? colors.chatUserBubbleText : colors.textSecondary,
                fontSize: primary ? 16 : 15,
                height: primary ? 1.38 : 1.4,
                fontWeight: primary ? FontWeight.w500 : FontWeight.w400,
                letterSpacing: 0,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
