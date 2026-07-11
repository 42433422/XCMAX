import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import 'branch_detail_screen.dart';

class ExecutionReviewScreen extends StatefulWidget {
  const ExecutionReviewScreen({
    super.key,
    required this.repository,
    this.threadId = '',
    this.title = '执行回顾',
  });

  final MobileRepository repository;
  final String threadId;
  final String title;

  @override
  State<ExecutionReviewScreen> createState() => _ExecutionReviewScreenState();
}

class _ExecutionReviewScreenState extends State<ExecutionReviewScreen> {
  List<RelayRunSummary> _runs = const [];
  bool _loading = true;
  String _error = '';
  final Set<String> _working = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted) setState(() => _loading = true);
    try {
      final runs = await widget.repository.loadRelayRuns(
        threadId: widget.threadId,
        limit: 200,
      );
      if (!mounted) return;
      setState(() {
        _runs = runs;
        _error = '';
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _reviewErrorMessage(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _cancel(RelayRunSummary run) async {
    setState(() => _working.add(run.taskId));
    try {
      final acknowledged = await widget.repository.cancelRelayTask(run.taskId);
      if (!acknowledged && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('只能停止等待，电脑任务可能继续')),
        );
      }
      await _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('停止失败：${_reviewErrorMessage(error)}')),
        );
      }
    } finally {
      if (mounted) setState(() => _working.remove(run.taskId));
    }
  }

  Future<void> _retry(RelayRunSummary run) async {
    setState(() => _working.add(run.taskId));
    try {
      await widget.repository.retryRelayRun(run.taskId);
      await _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('重试失败：${_reviewErrorMessage(error)}')),
        );
      }
    } finally {
      if (mounted) setState(() => _working.remove(run.taskId));
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        child: Column(
          children: [
            WeTopBar(
              title: widget.title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: _loading ? null : _load,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                ),
              ],
            ),
            if (_loading) const LinearProgressIndicator(minHeight: 2),
            Expanded(child: _body(colors)),
          ],
        ),
      ),
    );
  }

  Widget _body(XcagiThemeColors colors) {
    if (_error.isNotEmpty && _runs.isEmpty) {
      return Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.cloud_off_outlined,
                size: 52,
                color: colors.textSecondary,
              ),
              const SizedBox(height: 16),
              const Text(
                '暂时无法加载执行记录',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              Text(
                _error,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 14,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: _loading ? null : _load,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('重新加载'),
              ),
            ],
          ),
        ),
      );
    }
    if (!_loading && _runs.isEmpty) {
      return const Center(child: Text('当前对话还没有执行记录'));
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 28),
        itemCount: _runs.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (_, index) => _RunCard(
          run: _runs[index],
          busy: _working.contains(_runs[index].taskId),
          onCancel: () => _cancel(_runs[index]),
          onRetry: () => _retry(_runs[index]),
          onBranch: _runs[index].branch.isEmpty
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => BranchDetailScreen(
                        branch: _runs[index].branch,
                        repository: widget.repository,
                      ),
                    ),
                  ),
        ),
      ),
    );
  }
}

class _RunCard extends StatelessWidget {
  const _RunCard({
    required this.run,
    required this.busy,
    required this.onCancel,
    required this.onRetry,
    this.onBranch,
  });

  final RelayRunSummary run;
  final bool busy;
  final VoidCallback onCancel;
  final VoidCallback onRetry;
  final VoidCallback? onBranch;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final accent = _statusColor(run.status, colors);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(_toolIcon(run.kind), size: 20, color: accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${_toolLabel(run.kind)} · 第 ${run.attemptNo} 次执行',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Container(
                key: ValueKey('run_source_${run.taskId}'),
                margin: const EdgeInsets.only(right: 6),
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: (run.source == 'lan' ? colors.success : colors.brand)
                      .withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  run.sourceLabel,
                  style: TextStyle(
                    color: run.source == 'lan' ? colors.success : colors.brand,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  _statusLabel(run.status),
                  style: TextStyle(color: accent, fontSize: 12),
                ),
              ),
            ],
          ),
          if (run.message.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(run.message, maxLines: 3, overflow: TextOverflow.ellipsis),
          ],
          if (run.resultText.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              run.resultText,
              maxLines: 5,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: colors.textSecondary, fontSize: 13),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            [
              if (run.branch.isNotEmpty) run.branch,
              if (run.elapsedSeconds > 0)
                '${run.elapsedSeconds.toStringAsFixed(1)} 秒',
              run.updatedAt,
            ].where((item) => item.isNotEmpty).join(' · '),
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          ),
          if (run.active ||
              onBranch != null ||
              const {'failed', 'blocked', 'cancelled'}
                  .contains(run.status)) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              children: [
                if (run.active)
                  OutlinedButton.icon(
                    onPressed: busy ? null : onCancel,
                    icon: const Icon(Icons.stop_circle_outlined, size: 18),
                    label: const Text('停止'),
                  ),
                if (const {'failed', 'blocked', 'cancelled'}
                    .contains(run.status))
                  FilledButton.tonalIcon(
                    onPressed: busy ? null : onRetry,
                    icon: const Icon(Icons.replay, size: 18),
                    label: const Text('重试'),
                  ),
                if (onBranch != null)
                  OutlinedButton.icon(
                    onPressed: onBranch,
                    icon: const Icon(Icons.account_tree, size: 18),
                    label: const Text('分支与审批'),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

String _toolLabel(String kind) {
  if (kind.startsWith('claude')) return 'Claude';
  if (kind.startsWith('cursor')) return 'Cursor';
  if (kind.startsWith('trae')) return 'Trae';
  return 'Codex';
}

IconData _toolIcon(String kind) {
  if (kind.startsWith('claude')) return Icons.psychology_outlined;
  if (kind.startsWith('cursor')) return Icons.mouse_outlined;
  if (kind.startsWith('trae')) return Icons.code;
  return Icons.terminal;
}

String _statusLabel(String status) {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'running':
    case 'assigned':
    case 'processing':
    case 'in_progress':
      return '运行中';
    case 'completed':
    case 'done':
      return '已完成';
    case 'cancelled':
      return '已停止';
    case 'blocked':
      return '受阻';
    case 'failed':
      return '失败';
    default:
      return status.isEmpty ? '待命' : status;
  }
}

Color _statusColor(String status, XcagiThemeColors colors) {
  if (const {'completed', 'done'}.contains(status)) return colors.success;
  if (const {'failed', 'blocked'}.contains(status)) return colors.danger;
  if (const {'queued', 'running', 'assigned', 'processing', 'in_progress'}
      .contains(status)) {
    return colors.brand;
  }
  return colors.textSecondary;
}

String _reviewErrorMessage(Object error) {
  final message = error.toString().trim();
  final normalized = message.toLowerCase();
  if (normalized.contains('404') && normalized.contains('/relay/tasks')) {
    return '当前服务端尚未升级“执行回顾”接口。请更新并重启电脑端/服务端后刷新；'
        '已有任务不会因此丢失。';
  }
  if (const [
    'timeoutexception',
    'timed out',
    'timeout',
    'future not completed',
  ].any(normalized.contains)) {
    return '连接电脑端超时。请确认手机与电脑在同一网络，电脑端服务保持运行，然后重试。';
  }
  if (const [
    'socketexception',
    'clientexception',
    'failed host lookup',
    'connection refused',
    'connection reset',
    'network is unreachable',
  ].any(normalized.contains)) {
    return '暂时无法连接电脑端。请检查局域网和电脑端服务，然后重试。';
  }
  if (const ['401', '403', 'unauthorized', 'forbidden']
      .any(normalized.contains)) {
    return '登录或配对状态已失效，请重新连接电脑端后再试。';
  }
  return '执行记录暂时加载失败，请稍后重试。';
}
