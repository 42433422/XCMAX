import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

/// 工具调用时间线：展示 dev-loop 的步骤（CLI 执行 → 创建分支 → 验证 → 推送）。
class TimelineScreen extends StatefulWidget {
  const TimelineScreen({
    super.key,
    required this.repository,
    required this.taskId,
    required this.toolLabel,
    this.initialCalls,
  });

  final MobileRepository repository;
  final String taskId;
  final String toolLabel;
  final List<Map<String, Object?>>? initialCalls;

  @override
  State<TimelineScreen> createState() => _TimelineScreenState();
}

class _TimelineScreenState extends State<TimelineScreen> {
  bool _loading = true;
  String? _error;
  List<Map<String, Object?>> _calls = const [];

  @override
  void initState() {
    super.initState();
    _loadCalls();
  }

  Future<void> _loadCalls() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final initial = widget.initialCalls;
    if (initial != null && initial.isNotEmpty) {
      if (!mounted) return;
      setState(() {
        _calls = initial;
        _loading = false;
      });
      return;
    }
    final taskId = widget.taskId;
    if (taskId.isEmpty) {
      if (!mounted) return;
      setState(() {
        _calls = const [];
        _loading = false;
      });
      return;
    }
    try {
      final result = await widget.repository.loadToolCalls(taskId);
      if (!mounted) return;
      setState(() {
        _calls = result;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: Column(
        children: [
          WeTopBar(
            title: '执行时间线 · ${widget.toolLabel}',
            showBack: true,
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh, size: 22),
                tooltip: '刷新',
                onPressed: _loading ? null : _loadCalls,
              ),
            ],
          ),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _ErrorView(message: _error!, onRetry: _loadCalls);
    }
    if (_calls.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.history, size: 48, color: AppTheme.colors(context).textTertiary),
            const SizedBox(height: 12),
            Text(
              '暂无工具调用记录',
              style: TextStyle(color: AppTheme.colors(context).textSecondary),
            ),
          ],
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      children: [
        Text(
          '本次 dev-loop 共 ${_calls.length} 步',
          style: TextStyle(
            color: AppTheme.colors(context).textSecondary,
            fontSize: 13,
          ),
        ),
        const SizedBox(height: 12),
        ..._buildTimeline(),
      ],
    );
  }

  List<Widget> _buildTimeline() {
    final colors = AppTheme.colors(context);
    final widgets = <Widget>[];
    for (var i = 0; i < _calls.length; i++) {
      final call = _calls[i];
      final isLast = i == _calls.length - 1;
      widgets.add(
        _TimelineEntry(
          call: call,
          isLast: isLast,
          accentColor: colors.brand,
        ),
      );
    }
    return widgets;
  }
}

class _TimelineEntry extends StatelessWidget {
  const _TimelineEntry({
    required this.call,
    required this.isLast,
    required this.accentColor,
  });

  final Map<String, Object?> call;
  final bool isLast;
  final Color accentColor;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final icon = _resolveIcon(call['icon'] as String?, call['action'] as String?);
    final label = (call['label'] as String?) ?? (call['action'] as String?) ?? '';
    final detail = (call['detail'] as String?) ?? '';
    final success = call['success'] as bool?;
    final iconColor = success == false
        ? colors.danger
        : success == true
            ? colors.success
            : accentColor;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 40,
            child: Column(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: iconColor.withValues(alpha: 0.12),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(icon, size: 18, color: iconColor),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: 2,
                      color: colors.divider.withValues(alpha: 0.6),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Container(
              margin: EdgeInsets.only(bottom: isLast ? 0 : 16),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: colors.surface,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          label,
                          style: TextStyle(
                            color: colors.textPrimary,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      if (success == true)
                        Icon(Icons.check_circle, size: 16, color: colors.success)
                      else if (success == false)
                        Icon(Icons.error, size: 16, color: colors.danger),
                    ],
                  ),
                  if (detail.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      detail,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 12,
                        height: 1.4,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  IconData _resolveIcon(String? icon, String? action) {
    if (icon == 'branch') return Icons.call_split;
    if (icon == 'check') return Icons.verified;
    if (icon == 'upload') return Icons.cloud_upload;
    if (icon == 'terminal') return Icons.terminal;
    if (action == 'create_branch') return Icons.call_split;
    if (action == 'verify') return Icons.verified;
    if (action == 'push') return Icons.cloud_upload;
    if (action == 'cli_run') return Icons.terminal;
    return Icons.history;
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: colors.danger),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.textSecondary),
            ),
            const SizedBox(height: 16),
            FilledButton.tonalIcon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
