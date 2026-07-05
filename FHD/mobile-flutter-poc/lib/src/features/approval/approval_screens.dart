import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class ApprovalListScreen extends StatefulWidget {
  const ApprovalListScreen({
    super.key,
    this.repository,
    this.initialItems,
  });

  final MobileRepository? repository;
  final List<ApprovalRequest>? initialItems;

  @override
  State<ApprovalListScreen> createState() => _ApprovalListScreenState();
}

class _ApprovalListScreenState extends State<ApprovalListScreen> {
  late final MobileRepository _repository;
  late Future<List<ApprovalRequest>> _future;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

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
              title: '审批',
              actions: [
                IconButton(
                  onPressed: _refresh,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<List<ApprovalRequest>>(
                future: _future,
                builder: (context, snapshot) {
                  final items = snapshot.data ?? const <ApprovalRequest>[];
                  if (snapshot.connectionState == ConnectionState.done &&
                      items.isEmpty) {
                    return RefreshIndicator(
                      color: colors.brand,
                      onRefresh: _refresh,
                      child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: [
                          const SizedBox(height: 180),
                          Center(
                            child: Text(
                              '暂无待办审批',
                              style: TextStyle(
                                color: colors.textSecondary,
                                fontSize: 16,
                                height: 1.38,
                                letterSpacing: 0,
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  }
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.only(bottom: 96),
                      children: [
                        const WeSectionCaption('待处理'),
                        WeCellGroup(
                          children: [
                            for (var i = 0; i < items.length; i++)
                              WeCell(
                                title:
                                    items[i].title.ifEmpty('#${items[i].id}'),
                                subtitle: items[i]
                                    .subtitle
                                    .ifEmpty(items[i].applicantName),
                                showArrow: items[i].id > 0,
                                showDivider: i < items.length - 1,
                                trailing: items[i].status.trim().isNotEmpty
                                    ? _StatusChip(items[i].status)
                                    : null,
                                onTap: items[i].id > 0
                                    ? () => _openDetail(items[i])
                                    : null,
                              ),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<List<ApprovalRequest>> _load() async {
    if (widget.initialItems != null) return widget.initialItems!;
    return _repository.loadApprovals();
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }

  void _openDetail(ApprovalRequest item) {
    if (item.id <= 0) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            ApprovalDetailScreen(repository: _repository, id: item.id),
      ),
    );
  }
}

class ApprovalDetailScreen extends StatefulWidget {
  const ApprovalDetailScreen({
    super.key,
    required this.id,
    this.repository,
    this.initialDetail,
  });

  final int id;
  final MobileRepository? repository;
  final ApprovalDetail? initialDetail;

  @override
  State<ApprovalDetailScreen> createState() => _ApprovalDetailScreenState();
}

class _ApprovalDetailScreenState extends State<ApprovalDetailScreen> {
  late final MobileRepository _repository;
  late Future<ApprovalDetail> _future;
  final _opinionController = TextEditingController();
  var _working = false;
  var _status = '';

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  void dispose() {
    _opinionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ApprovalDetail>(
      future: _future,
      builder: (context, snapshot) {
        final detail = snapshot.data ?? widget.initialDetail;
        final colors = AppTheme.colors(context);
        return Scaffold(
          backgroundColor: colors.page,
          body: SafeArea(
            bottom: false,
            child: Column(
              children: [
                WeTopBar(
                  title: detail?.title ?? '审批详情',
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                ),
                Expanded(
                  child: detail == null
                      ? Center(
                          child: CircularProgressIndicator(color: colors.brand),
                        )
                      : ListView(
                          padding: const EdgeInsets.only(bottom: 96),
                          children: [
                            if (_status.trim().isNotEmpty)
                              _StatusBanner(_status),
                            const WeSectionCaption('审批信息'),
                            WeCellGroup(
                              children: [
                                WeCell(
                                  title: '单号',
                                  value:
                                      detail.requestNo.ifEmpty('#${detail.id}'),
                                  trailing: _StatusChip(detail.status),
                                ),
                                WeCell(
                                  title: '发起人',
                                  value: detail.applicantName,
                                  showDivider:
                                      detail.flowName.trim().isNotEmpty,
                                ),
                                if (detail.flowName.trim().isNotEmpty)
                                  WeCell(
                                    title: '流程',
                                    value: detail.flowName,
                                    showDivider: detail.currentNodeName
                                        .trim()
                                        .isNotEmpty,
                                  ),
                                if (detail.currentNodeName.trim().isNotEmpty)
                                  WeCell(
                                    title: '当前节点',
                                    value: detail.currentNodeName,
                                    showDivider:
                                        detail.submittedAt.trim().isNotEmpty,
                                  ),
                                if (detail.submittedAt.trim().isNotEmpty)
                                  WeCell(
                                    title: '提交时间',
                                    value: detail.submittedAt,
                                    showDivider:
                                        detail.description.trim().isNotEmpty,
                                  ),
                                if (detail.description.trim().isNotEmpty)
                                  WeCell(
                                    title: '说明',
                                    subtitle: detail.description,
                                    showDivider: false,
                                  ),
                              ],
                            ),
                            const WeSectionCaption('审批意见'),
                            WeCellGroup(
                              children: [
                                Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 16,
                                    vertical: 8,
                                  ),
                                  child: TextField(
                                    controller: _opinionController,
                                    minLines: 2,
                                    maxLines: 4,
                                    decoration: const InputDecoration(
                                      border: InputBorder.none,
                                      hintText: '输入审批意见（可选）',
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                              child: Text(
                                '复杂编辑请在电脑端处理',
                                style: TextStyle(
                                  color: colors.textSecondary,
                                  fontSize: 12,
                                  height: 1.33,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                            const SizedBox(height: 16),
                            WeBlockButton(
                              text: '通过',
                              onPressed: () => _confirm(true),
                              enabled: detail.canAct && !_working,
                            ),
                            const SizedBox(height: 8),
                            WeBlockOutlinedButton(
                              text: '驳回',
                              onPressed: () => _confirm(false),
                              enabled: detail.canAct && !_working,
                            ),
                          ],
                        ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Future<ApprovalDetail> _load() async {
    if (widget.initialDetail != null) return widget.initialDetail!;
    return _repository.loadApprovalDetail(widget.id);
  }

  Future<void> _confirm(bool approve) async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => WeDialog(
        onDismiss: () => Navigator.of(dialogContext).pop(false),
        title: approve ? '确认通过' : '确认驳回',
        message: approve ? '确定通过该审批？' : '确定驳回该审批？',
        confirmText: '确定',
        confirmDanger: !approve,
        onConfirm: () => Navigator.of(dialogContext).pop(true),
      ),
    );
    if (accepted != true) return;
    setState(() => _working = true);
    try {
      final opinion = _opinionController.text.trim();
      if (approve) {
        await _repository.approveApproval(widget.id, opinion);
      } else {
        await _repository.rejectApproval(widget.id, opinion);
      }
      if (!mounted) return;
      setState(() => _status = approve ? '审批已通过' : '审批已驳回');
      Navigator.of(context).maybePop();
    } catch (error) {
      if (mounted) setState(() => _status = error.toString());
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: colors.brandContainer,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text.ifEmpty('待处理'),
        style: TextStyle(
          color: colors.brand,
          fontSize: 11,
          height: 1.27,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _StatusBanner extends StatelessWidget {
  const _StatusBanner(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.brandContainer,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: colors.brand,
          fontSize: 13,
          height: 1.38,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}
