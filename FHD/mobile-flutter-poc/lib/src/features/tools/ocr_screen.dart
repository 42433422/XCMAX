import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../platform/android_camera_permission.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class OcrScreen extends StatefulWidget {
  const OcrScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<OcrScreen> createState() => _OcrScreenState();
}

class _OcrScreenState extends State<OcrScreen> {
  final _picker = ImagePicker();
  var _busy = false;
  String _result = '';
  String _error = '';

  MobileRepository? get _repository =>
      widget.repository ?? MobileRepositoryScope.maybeRead(context);

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
                  const WeSectionCaption('图片文字识别'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: '拍照识别',
                        subtitle: '拍下票据、表格或文档，交给企业 OCR',
                        icon: Icons.camera_alt,
                        iconColor: colors.brand,
                        iconBg: colors.brandContainer,
                        onTap: _busy ? null : () => _pick(ImageSource.camera),
                      ),
                      WeCell(
                        title: '从相册选择',
                        subtitle: '支持截图、照片和扫描图片',
                        icon: Icons.photo_library,
                        iconColor: colors.success,
                        iconBg: colors.success.withValues(alpha: 0.12),
                        showDivider: false,
                        onTap: _busy ? null : () => _pick(ImageSource.gallery),
                      ),
                    ],
                  ),
                  if (_busy)
                    const Padding(
                      padding: EdgeInsets.all(28),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  if (_error.isNotEmpty)
                    _OcrResultCard(
                      title: '识别失败',
                      body: _error,
                      color: colors.danger,
                    ),
                  if (_result.isNotEmpty) ...[
                    _OcrResultCard(
                      title: '识别结果',
                      body: _result,
                      color: colors.success,
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                      child: FilledButton.icon(
                        onPressed: () => Navigator.of(context).pop(_result),
                        icon: const Icon(Icons.chat_bubble_outline),
                        label: const Text('带回小C继续处理'),
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  const WeSectionCaption('状态'),
                  WeCellGroup(
                    children: [
                      WeCell(
                        title: 'OCR 服务',
                        subtitle: _busy ? '正在调用企业端识别引擎' : '移动端上传链路已接通',
                        icon: Icons.cloud_done,
                        iconColor: colors.success,
                        iconBg: colors.success.withValues(alpha: 0.12),
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

  Future<void> _pick(ImageSource source) async {
    final repository = _repository;
    if (repository == null) {
      setState(() => _error = '当前没有可用的服务器连接');
      return;
    }
    if (source == ImageSource.camera &&
        !await const AndroidCameraPermission().ensureGranted()) {
      setState(() => _error = '需要相机权限才能拍照识别');
      return;
    }
    final image = await _picker.pickImage(
      source: source,
      imageQuality: 92,
      maxWidth: 2600,
    );
    if (image == null || !mounted) return;
    setState(() {
      _busy = true;
      _result = '';
      _error = '';
    });
    try {
      final bytes = await image.readAsBytes();
      final text = await repository.recognizeAssistantImage(
        filename: image.name,
        bytes: bytes,
        contentType: image.mimeType ?? 'image/jpeg',
      );
      if (mounted) {
        setState(() => _result = text.isEmpty ? '图片中没有识别到文字。' : text);
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _OcrResultCard extends StatelessWidget {
  const _OcrResultCard({
    required this.title,
    required this.body,
    required this.color,
  });

  final String title;
  final String body;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: TextStyle(color: color, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          SelectableText(body, style: const TextStyle(height: 1.5)),
        ],
      ),
    );
  }
}
