import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class OcrScreen extends StatelessWidget {
  const OcrScreen({super.key});

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
              title: '拍照识别',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 24),
                children: [
                  const WeSectionCaption('入口'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '拍照识别',
                        subtitle: '调用企业端 OCR 引擎处理图片文字',
                        icon: Icons.camera_alt,
                        iconColor: colors.brand,
                        iconBg: colors.brandContainer,
                        onTap: () =>
                            _showMessage(context, '移动端拍照上传正在接入，请先使用电脑端 OCR'),
                      ),
                      WeCell(
                        title: '从相册选择',
                        subtitle: '识别票据、表格截图与文档图片',
                        icon: Icons.photo_library,
                        iconColor: colors.success,
                        iconBg:
                            Theme.of(context).colorScheme.secondaryContainer,
                        onTap: () =>
                            _showMessage(context, '移动端相册识别正在接入，请先使用电脑端 OCR'),
                      ),
                      WeCell(
                        title: '批量识别',
                        subtitle: '完整批量处理请使用电脑端',
                        icon: Icons.insert_drive_file,
                        iconColor: colors.warning,
                        iconBg: colors.warning.withValues(alpha: 0.12),
                        showArrow: false,
                        showDivider: false,
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const WeSectionCaption('状态'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '企业 OCR',
                        subtitle: '等待移动端上传链路接入',
                        icon: Icons.cloud_done,
                        iconColor: colors.success,
                        iconBg:
                            Theme.of(context).colorScheme.secondaryContainer,
                        showArrow: false,
                        showDivider: false,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  static void _showMessage(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }
}
