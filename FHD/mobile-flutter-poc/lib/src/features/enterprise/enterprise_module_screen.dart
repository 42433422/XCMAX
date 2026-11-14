import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class EnterpriseModuleScreen extends StatelessWidget {
  const EnterpriseModuleScreen({
    super.key,
    required this.title,
    required this.actionText,
    this.onAction,
  });

  factory EnterpriseModuleScreen.smartAnalysis({VoidCallback? onAction}) {
    return EnterpriseModuleScreen(
      title: '智慧分析',
      actionText: '回到消息',
      onAction: onAction,
    );
  }

  factory EnterpriseModuleScreen.aiOpen({VoidCallback? onAction}) {
    return EnterpriseModuleScreen(
      title: '开放智控',
      actionText: '返回',
      onAction: onAction,
    );
  }

  factory EnterpriseModuleScreen.brain({VoidCallback? onAction}) {
    return EnterpriseModuleScreen(
      title: '智脑集成',
      actionText: '打开能力库',
      onAction: onAction,
    );
  }

  factory EnterpriseModuleScreen.modStore({VoidCallback? onAction}) {
    return EnterpriseModuleScreen(
      title: '能力库',
      actionText: '查看企业模块',
      onAction: onAction,
    );
  }

  final String title;
  final String actionText;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 36,
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 24,
                        height: 1.25,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0,
                      ),
                    ),
                    const SizedBox(height: 22),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton(
                        onPressed:
                            onAction ?? () => Navigator.of(context).maybePop(),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(actionText),
                            const SizedBox(width: 8),
                            const Icon(Icons.arrow_forward, size: 18),
                          ],
                        ),
                      ),
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
}
