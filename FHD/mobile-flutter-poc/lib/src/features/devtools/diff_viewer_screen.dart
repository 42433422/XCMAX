import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

/// 分支改动查看器：展示结构化 diff（文件级新增/删除/修改统计）。
class DiffViewerScreen extends StatefulWidget {
  const DiffViewerScreen({
    super.key,
    required this.branch,
    required this.repository,
  });

  final String branch;
  final MobileRepository repository;

  @override
  State<DiffViewerScreen> createState() => _DiffViewerScreenState();
}

class _DiffViewerScreenState extends State<DiffViewerScreen> {
  bool _loading = true;
  String? _error;
  Map<String, Object?>? _data;

  @override
  void initState() {
    super.initState();
    _loadDiff();
  }

  Future<void> _loadDiff() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.repository.runGitDiffStructured(
        branch: widget.branch,
      );
      if (!mounted) return;
      setState(() {
        _data = result;
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
            title: '改动预览 · ${widget.branch}',
            showBack: true,
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh, size: 22),
                tooltip: '刷新',
                onPressed: _loading ? null : _loadDiff,
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
      return _ErrorView(message: _error!, onRetry: _loadDiff);
    }
    final data = _data ?? const <String, Object?>{};
    final files = (data['files'] as List?) ?? const <Object?>[];
    final totalAdd = _toInt(data['total_additions']);
    final totalDel = _toInt(data['total_deletions']);
    final base = (data['base'] as String?) ?? '';
    final branch = (data['branch'] as String?) ?? widget.branch;
    if (files.isEmpty) {
      return const Center(
        child: Text('当前分支没有相对基线的改动', textAlign: TextAlign.center),
      );
    }
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      children: [
        _SummaryCard(
          base: base,
          branch: branch,
          additions: totalAdd,
          deletions: totalDel,
        ),
        const SizedBox(height: 12),
        ...files.map((raw) {
          if (raw is! Map) return const SizedBox.shrink();
          return _FileDiffRow(file: Map<String, Object?>.from(raw));
        }),
      ],
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({
    required this.base,
    required this.branch,
    required this.additions,
    required this.deletions,
  });

  final String base;
  final String branch;
  final int additions;
  final int deletions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '分支对比',
            style: textTheme.titleMedium?.copyWith(color: colors.textPrimary),
          ),
          const SizedBox(height: 8),
          Text(
            '$base → $branch',
            style: textTheme.bodySmall?.copyWith(color: colors.textSecondary),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _StatChip(label: '+$additions', color: colors.success),
              const SizedBox(width: 8),
              _StatChip(label: '-$deletions', color: colors.danger),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 13,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _FileDiffRow extends StatelessWidget {
  const _FileDiffRow({required this.file});

  final Map<String, Object?> file;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final path = (file['path'] as String?) ?? (file['file'] as String?) ?? '';
    final status = (file['status'] as String?) ?? 'M';
    final add = _toInt(file['additions']);
    final del = _toInt(file['deletions']);
    final statusColor = switch (status) {
      'A' => colors.success,
      'D' => colors.danger,
      'M' => colors.warning,
      _ => colors.textSecondary,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: statusColor.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              status,
              style: TextStyle(color: statusColor, fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              path,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 14,
                fontFamily: 'monospace',
              ),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '+$add/-$del',
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 12,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
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

int _toInt(Object? value) {
  if (value == null) return 0;
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value.toString()) ?? 0;
}
