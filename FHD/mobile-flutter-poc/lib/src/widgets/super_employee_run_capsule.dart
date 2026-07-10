import 'package:flutter/material.dart';

import '../data/mobile_repository.dart';
import '../theme/app_theme.dart';

enum SuperEmployeeRunAvailability {
  checking,
  ready,
  offline,
  unpaired,
  unknown,
}

class SuperEmployeeRunCapsule extends StatelessWidget {
  const SuperEmployeeRunCapsule({
    super.key,
    required this.runs,
    required this.onTap,
    this.availability = SuperEmployeeRunAvailability.ready,
  });

  final List<RelayRunSummary> runs;
  final VoidCallback onTap;
  final SuperEmployeeRunAvailability availability;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final byTool = <String, RelayRunSummary>{};
    for (final run in runs) {
      byTool.putIfAbsent(relayRunToolLabel(run.kind), () => run);
    }
    return Material(
      color: colors.page,
      child: InkWell(
        key: const ValueKey('super_employee_run_capsule'),
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.fromLTRB(12, 6, 12, 4),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(color: colors.divider),
          ),
          child: availability == SuperEmployeeRunAvailability.ready
              ? Row(
                  children: [
                    for (final tool in const [
                      'Codex',
                      'Claude',
                      'Cursor',
                      'Trae'
                    ])
                      Expanded(
                        child: _RunCapsuleSlot(
                          tool: tool,
                          status: byTool[tool]?.status ?? 'idle',
                        ),
                      ),
                    Icon(
                      Icons.chevron_right,
                      size: 18,
                      color: colors.textSecondary,
                    ),
                  ],
                )
              : _RunAvailabilityNotice(availability: availability),
        ),
      ),
    );
  }
}

class _RunAvailabilityNotice extends StatelessWidget {
  const _RunAvailabilityNotice({required this.availability});

  final SuperEmployeeRunAvailability availability;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final (icon, title, subtitle, color) = switch (availability) {
      SuperEmployeeRunAvailability.checking => (
          Icons.sync_rounded,
          '正在检查执行电脑',
          '确认四位超级员工的实时状态',
          colors.brand,
        ),
      SuperEmployeeRunAvailability.offline => (
          Icons.cloud_off_outlined,
          '执行电脑离线',
          '请检查电脑服务和局域网连接',
          colors.danger,
        ),
      SuperEmployeeRunAvailability.unpaired => (
          Icons.link_off_rounded,
          '尚未配对执行电脑',
          '连接电脑后可运行四位超级员工',
          colors.warning,
        ),
      SuperEmployeeRunAvailability.unknown => (
          Icons.help_outline_rounded,
          '执行状态未知',
          '下拉刷新，或轻点查看详情',
          colors.textSecondary,
        ),
      SuperEmployeeRunAvailability.ready => (
          Icons.check_circle_outline,
          '执行电脑已就绪',
          '四位超级员工可以接收任务',
          colors.success,
        ),
    };
    return Semantics(
      label: '$title，$subtitle',
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.10),
              borderRadius: BorderRadius.circular(11),
            ),
            alignment: Alignment.center,
            child: Icon(icon, size: 19, color: color),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: colors.textSecondary, fontSize: 10.5),
                ),
              ],
            ),
          ),
          Icon(Icons.chevron_right, size: 18, color: colors.textSecondary),
        ],
      ),
    );
  }
}

class _RunCapsuleSlot extends StatelessWidget {
  const _RunCapsuleSlot({required this.tool, required this.status});

  final String tool;
  final String status;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final active = const {
      'queued',
      'running',
      'assigned',
      'processing',
      'in_progress',
    }.contains(status);
    final failed = const {'failed', 'blocked'}.contains(status);
    final color = failed
        ? colors.danger
        : active
            ? colors.brand
            : colors.textSecondary;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 4),
            Flexible(
              child: Text(
                tool,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 2),
        Text(
          relayRunStatusLabel(status),
          style: TextStyle(fontSize: 10, color: color),
        ),
      ],
    );
  }
}

String relayRunToolLabel(String kind) {
  if (kind.startsWith('claude')) return 'Claude';
  if (kind.startsWith('cursor')) return 'Cursor';
  if (kind.startsWith('trae')) return 'Trae';
  return 'Codex';
}

String relayRunStatusLabel(String status) {
  switch (status) {
    case 'queued':
      return '排队';
    case 'running':
    case 'assigned':
    case 'processing':
    case 'in_progress':
      return '运行';
    case 'completed':
    case 'done':
      return '完成';
    case 'failed':
      return '失败';
    case 'blocked':
      return '受阻';
    case 'cancelled':
      return '停止';
    case 'archived':
      return '归档';
    default:
      return '待命';
  }
}
