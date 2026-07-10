import 'package:flutter/material.dart';

import '../../data/assistant_assets.dart';
import '../../data/mobile_repository.dart';
import '../../platform/assistant_native_bridge.dart';
import '../../theme/app_theme.dart';
import 'assistant_visuals.dart';

class AssistantFileScreen extends StatefulWidget {
  const AssistantFileScreen({
    super.key,
    required this.repository,
    this.nativeBridge = const AssistantNativeBridge(),
  });

  final MobileRepository repository;
  final AssistantNativeBridge nativeBridge;

  @override
  State<AssistantFileScreen> createState() => _AssistantFileScreenState();
}

class _AssistantFileScreenState extends State<AssistantFileScreen> {
  var _busy = false;
  String _status = '选择文件后，小C会调用项目里的全文读取员工';
  String _error = '';
  AssistantFileAnalysis? _analysis;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: AssistantBackdrop(
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              AssistantTopBar(
                title: '文件工作台',
                onBack: () => Navigator.of(context).maybePop(),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(18, 10, 18, 36),
                  children: [
                    Container(
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [Color(0xFFF0F0FF), Color(0xFFF8FBFF)],
                        ),
                        borderRadius: BorderRadius.circular(28),
                        border: Border.all(color: Colors.white, width: 1),
                        boxShadow: [
                          BoxShadow(
                            color: assistantIndigo.withValues(alpha: 0.10),
                            blurRadius: 30,
                            offset: const Offset(0, 14),
                          ),
                        ],
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Row(
                            children: [
                              AssistantIconTile(
                                icon: Icons.folder_copy_outlined,
                                color: assistantIndigo,
                                size: 48,
                                iconSize: 24,
                              ),
                              SizedBox(width: 13),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '理解任何工作文件',
                                      style: TextStyle(
                                        fontSize: 20,
                                        fontWeight: FontWeight.w800,
                                        letterSpacing: -0.5,
                                      ),
                                    ),
                                    SizedBox(height: 4),
                                    Text(
                                      '提取正文、表格、要点，再交给小C继续分析',
                                      style: TextStyle(
                                        color: Color(0xFF70758C),
                                        fontSize: 12,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 18),
                          const Wrap(
                            spacing: 7,
                            runSpacing: 7,
                            children: [
                              _FileTypePill('PDF'),
                              _FileTypePill('Word'),
                              _FileTypePill('Excel'),
                              _FileTypePill('PPT'),
                              _FileTypePill('图片 OCR'),
                            ],
                          ),
                          const SizedBox(height: 18),
                          Text(
                            _status,
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 12,
                              height: 1.4,
                            ),
                          ),
                          const SizedBox(height: 12),
                          SizedBox(
                            width: double.infinity,
                            height: 50,
                            child: FilledButton.icon(
                              style: FilledButton.styleFrom(
                                backgroundColor: assistantIndigo,
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(16),
                                ),
                              ),
                              onPressed: _busy ? null : _pickAndAnalyze,
                              icon: _busy
                                  ? const SizedBox.square(
                                      dimension: 18,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Colors.white,
                                      ),
                                    )
                                  : const Icon(Icons.add_rounded),
                              label: Text(
                                _busy ? '正在理解文件…' : '选择文件或图片',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (_error.isNotEmpty) ...[
                      const SizedBox(height: 18),
                      _ResultCard(
                        title: '读取失败',
                        body: _error,
                        color: colors.danger,
                      ),
                    ],
                    if (_analysis != null) ...[
                      const SizedBox(height: 22),
                      const AssistantSectionLabel('文件内容'),
                      const SizedBox(height: 10),
                      _ResultCard(
                        title: _analysis!.filename,
                        body: _analysis!.summary,
                        color: assistantMint,
                      ),
                      const SizedBox(height: 13),
                      SizedBox(
                        width: double.infinity,
                        height: 48,
                        child: FilledButton.icon(
                          style: FilledButton.styleFrom(
                            backgroundColor: colors.textPrimary,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                          onPressed: () => Navigator.of(context).pop(_analysis),
                          icon:
                              const Icon(Icons.arrow_upward_rounded, size: 19),
                          label: const Text(
                            '带回小C继续分析',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.lock_outline_rounded,
                            size: 15, color: colors.textSecondary),
                        const SizedBox(width: 7),
                        Expanded(
                          child: Text(
                            '文件只用于本次分析。办公文件由已有全文读取员工处理，图片使用企业 OCR。',
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 11,
                              height: 1.5,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _pickAndAnalyze() async {
    final picked = await widget.nativeBridge.pickFile();
    if (picked == null || !mounted) return;
    setState(() {
      _busy = true;
      _analysis = null;
      _error = '';
      _status = '正在读取 ${picked.name}';
    });
    try {
      final isImage = picked.mimeType.startsWith('image/') ||
          RegExp(r'\.(png|jpe?g|webp)$', caseSensitive: false)
              .hasMatch(picked.name);
      if (isImage) {
        final text = await widget.repository.recognizeAssistantImage(
          filename: picked.name,
          bytes: picked.bytes,
          contentType: picked.mimeType,
        );
        _analysis = AssistantFileAnalysis(
          filename: picked.name,
          employeeId: 'ocr',
          summary: text.isEmpty ? '图片中没有识别到文字。' : text,
        );
      } else {
        _analysis = await widget.repository.analyzeAssistantOfficeFile(
          filename: picked.name,
          bytes: picked.bytes,
          contentType: picked.mimeType,
        );
      }
      if (mounted) setState(() => _status = '读取完成，可以继续交给小C');
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error.toString();
          _status = '文件没有处理完成，可以重新选择';
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard(
      {required this.title, required this.body, required this.color});

  final String title;
  final String body;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: assistantSurfaceDecoration(context, radius: 22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AssistantIconTile(
                icon: Icons.description_outlined,
                color: color,
                size: 38,
                iconSize: 19,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  '已读取',
                  style: TextStyle(
                    color: color,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 15),
          SelectableText(
            body,
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 14.5,
              height: 1.68,
              letterSpacing: -0.05,
            ),
          ),
        ],
      ),
    );
  }
}

class _FileTypePill extends StatelessWidget {
  const _FileTypePill(this.label);

  final String label;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.74),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: Colors.white),
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: Color(0xFF62677C),
            fontSize: 10.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      );
}
