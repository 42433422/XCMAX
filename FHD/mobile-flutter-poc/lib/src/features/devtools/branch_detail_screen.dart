import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

/// 分支详情：commit 列表 + 合并/丢弃操作。
class BranchDetailScreen extends StatefulWidget {
  const BranchDetailScreen({
    super.key,
    required this.branch,
    required this.repository,
  });

  final String branch;
  final MobileRepository repository;

  @override
  State<BranchDetailScreen> createState() => _BranchDetailScreenState();
}

class _BranchDetailScreenState extends State<BranchDetailScreen> {
  bool _loading = true;
  bool _acting = false;
  String? _error;
  List<Map<String, Object?>> _commits = const [];
  String _base = '';

  @override
  void initState() {
    super.initState();
    _loadCommits();
  }

  Future<void> _loadCommits() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.repository.runGitLog(branch: widget.branch);
      if (!mounted) return;
      final commits = (result['commits'] as List?) ?? const <Object?>[];
      setState(() {
        _commits = commits
            .whereType<Map>()
            .map((e) => Map<String, Object?>.from(e))
            .toList(growable: false);
        _base = (result['base'] as String?) ?? '';
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

  Future<void> _runGitOp(String op, {required String successMsg}) async {
    if (_acting) return;
    setState(() => _acting = true);
    try {
      final result = await widget.repository.runGitOperation(
        branch: widget.branch,
        op: op,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(successMsg.isEmpty ? result : successMsg)),
      );
      await _loadCommits();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('操作失败：$e')));
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _confirmMerge() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('合并分支'),
        content: Text('确认将 ${widget.branch} 合并到当前主分支吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('合并'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _runGitOp('git.merge', successMsg: '分支已合并');
    }
  }

  Future<void> _confirmDiscard() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('丢弃分支'),
        content: Text('确认丢弃 ${widget.branch} 的改动？此操作不可撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('丢弃'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _runGitOp('git.discard', successMsg: '分支已丢弃');
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
            title: '分支详情 · ${widget.branch}',
            showBack: true,
            actions: [
              IconButton(
                icon: const Icon(Icons.refresh, size: 22),
                tooltip: '刷新',
                onPressed: _loading || _acting ? null : _loadCommits,
              ),
            ],
          ),
          if (!_loading && _error == null)
            _ActionBar(
              onMerge: _acting ? null : _confirmMerge,
              onDiscard: _acting ? null : _confirmDiscard,
              acting: _acting,
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
      return _ErrorView(message: _error!, onRetry: _loadCommits);
    }
    if (_commits.isEmpty) {
      return const Center(child: Text('该分支暂无提交记录'));
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: _commits.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        final commit = _commits[index];
        return _CommitRow(commit: commit, isLatest: index == 0, base: _base);
      },
    );
  }
}

class _ActionBar extends StatelessWidget {
  const _ActionBar({
    required this.onMerge,
    required this.onDiscard,
    required this.acting,
  });

  final VoidCallback? onMerge;
  final VoidCallback? onDiscard;
  final bool acting;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: colors.surface,
      child: Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: onMerge,
              icon: acting
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.merge_type, size: 18),
              label: const Text('合并到主分支'),
            ),
          ),
          const SizedBox(width: 12),
          OutlinedButton.icon(
            onPressed: onDiscard,
            style: OutlinedButton.styleFrom(foregroundColor: colors.danger),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('丢弃'),
          ),
        ],
      ),
    );
  }
}

class _CommitRow extends StatelessWidget {
  const _CommitRow({
    required this.commit,
    required this.isLatest,
    required this.base,
  });

  final Map<String, Object?> commit;
  final bool isLatest;
  final String base;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final sha = (commit['sha'] as String?) ?? (commit['hash'] as String?) ?? '';
    final shortSha = sha.length > 7 ? sha.substring(0, 7) : sha;
    final message =
        (commit['message'] as String?) ?? (commit['subject'] as String?) ?? '';
    final author = (commit['author'] as String?) ?? '';
    final date =
        (commit['date'] as String?) ?? (commit['time'] as String?) ?? '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(10),
        border: isLatest
            ? Border.all(color: colors.brand.withValues(alpha: 0.4), width: 1)
            : null,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: colors.brand.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              shortSha,
              style: TextStyle(
                color: colors.brand,
                fontSize: 11,
                fontFamily: 'monospace',
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 14,
                    height: 1.4,
                  ),
                ),
                if (author.isNotEmpty || date.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    [author, date].where((s) => s.isNotEmpty).join(' · '),
                    style: TextStyle(color: colors.textTertiary, fontSize: 12),
                  ),
                ],
              ],
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
