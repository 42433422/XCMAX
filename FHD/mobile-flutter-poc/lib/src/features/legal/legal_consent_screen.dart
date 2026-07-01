import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';

class LegalConsentScreen extends StatefulWidget {
  const LegalConsentScreen({
    super.key,
    this.api,
    this.legalVersion = 'enterprise-v1',
    this.onAccepted,
    this.onAbout,
  });

  final MobileApiClient? api;
  final String legalVersion;
  final VoidCallback? onAccepted;
  final VoidCallback? onAbout;

  @override
  State<LegalConsentScreen> createState() => _LegalConsentScreenState();
}

class _LegalConsentScreenState extends State<LegalConsentScreen> {
  late final MobileApiClient _api;
  var _checked = false;

  @override
  void initState() {
    super.initState();
    _api = widget.api ??
        MobileRepositoryScope.maybeRead(context)?.client ??
        MobileApiClient();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final foreground = colors.chatUserBubbleText;
    return Scaffold(
      backgroundColor: colors.brand,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Column(
            children: [
              const Spacer(),
              Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(
                  color: foreground.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(24),
                ),
                alignment: Alignment.center,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Image.asset(
                    appLauncherIconAsset,
                    width: 64,
                    height: 64,
                    fit: BoxFit.contain,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              Text(
                'XCAGI',
                style: TextStyle(
                  color: foreground,
                  fontSize: 34,
                  height: 1.12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                '企业智能工作平台',
                style: TextStyle(
                  color: foreground.withValues(alpha: 0.7),
                  fontSize: 14,
                  height: 1.36,
                  letterSpacing: 0,
                ),
              ),
              const Spacer(),
              InkWell(
                onTap: () => setState(() => _checked = !_checked),
                borderRadius: BorderRadius.circular(8),
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Container(
                        width: 18,
                        height: 18,
                        decoration: BoxDecoration(
                          color: _checked
                              ? foreground
                              : foreground.withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        alignment: Alignment.center,
                        child: _checked
                            ? Icon(
                                Icons.check,
                                size: 14,
                                color: colors.brand,
                              )
                            : null,
                      ),
                      const SizedBox(width: 8),
                      Flexible(
                        child: Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              '我已阅读并同意',
                              style: TextStyle(
                                color: foreground.withValues(alpha: 0.6),
                                fontSize: 12,
                                height: 1.34,
                                letterSpacing: 0,
                              ),
                            ),
                            const _LegalLabel('《用户协议》'),
                            Text(
                              '和',
                              style: TextStyle(
                                color: foreground.withValues(alpha: 0.6),
                                fontSize: 12,
                                height: 1.34,
                                letterSpacing: 0,
                              ),
                            ),
                            const _LegalLabel('《隐私政策》'),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 18),
              SizedBox(
                width: double.infinity,
                height: 48,
                child: FilledButton(
                  onPressed: _checked ? _accept : null,
                  style: FilledButton.styleFrom(
                    backgroundColor: foreground,
                    disabledBackgroundColor: foreground.withValues(alpha: 0.2),
                    foregroundColor: colors.brand,
                    disabledForegroundColor: foreground.withValues(alpha: 0.5),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(24),
                    ),
                  ),
                  child: Text(_checked ? '进入 XCAGI' : '请先同意协议'),
                ),
              ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }

  void _accept() {
    unawaited(
      _api.saveLegalAcceptedVersion(widget.legalVersion).catchError((_) {}),
    );
    if (!mounted) return;
    widget.onAccepted?.call();
  }
}

class _LegalLabel extends StatelessWidget {
  const _LegalLabel(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    final foreground = AppTheme.colors(context).chatUserBubbleText;
    return Text(
      label,
      style: TextStyle(
        color: foreground,
        fontSize: 12,
        height: 1.34,
        decoration: TextDecoration.underline,
        decorationColor: foreground,
        letterSpacing: 0,
      ),
    );
  }
}
