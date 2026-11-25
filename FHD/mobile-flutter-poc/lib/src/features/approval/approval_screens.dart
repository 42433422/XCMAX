import 'dart:async';
import 'package:flutter/material.dart';

import '../../api/mobile_session_store.dart' show MobileSessionData;
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../../policy/mobile_error_policy.dart';
import '../webview/desktop_tool_webview_screen.dart';

class ApprovalListScreen extends StatefulWidget {
  const ApprovalListScreen({super.key, this.repository, this.initialItems});

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
        child: Column(
          children: [
            WeTopBar(
              title: '审批',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                PopupMenuButton<String>(
                    tooltip: '审批管理',
                    onSelected: (path) => Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) => DesktopToolWebViewScreen(
                                title: '审批管理',
                                path: path,
                                api: _repository.client))),
                    itemBuilder: (_) => const [
                          PopupMenuItem(
                              value: '/approval-hub/flow-management',
                              child: Text('流程管理')),
                          PopupMenuItem(
                              value: '/approval-hub/rules',
                              child: Text('规则配置')),
                        ]),
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
                  if (snapshot.hasError) {
                    return Center(
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                      Semantics(
                        liveRegion: true,
                        child: Text(mobileErrorText(snapshot.error)),
                      ),
                      TextButton(onPressed: _refresh, child: const Text('重试')),
                    ]));
                  }
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(
                      child: CircularProgressIndicator(
                        semanticsLabel: '正在加载待办审批',
                      ),
                    );
                  }
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
                                title: items[i].title.ifEmpty(
                                      '#${items[i].id}',
                                    ),
                                subtitle: items[i].subtitle.ifEmpty(
                                      items[i].applicantName,
                                    ),
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
    await future.catchError((Object _) => <ApprovalRequest>[]);
  }

  Future<void> _openDetail(ApprovalRequest item) async {
    if (item.id <= 0) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            ApprovalDetailScreen(repository: _repository, id: item.id),
      ),
    );
    if (mounted) await _refresh();
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
  var _needsReconciliation = false;
  var _status = '';
  late final int _generation;
  StreamSubscription<MobileSessionData>? _sessionSubscription;
  bool _revoked = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _generation = _repository.client.authGeneration;
    _sessionSubscription = _repository.client.sessionChanges.listen((_) {
      if (_generation != _repository.client.authGeneration && !_revoked) {
        _revoked = true;
        _needsReconciliation = true;
        if (mounted) setState(() => _status = '账号已切换，请重新打开审批');
      }
    });
    _future = _load();
  }

  @override
  void dispose() {
    unawaited(_sessionSubscription?.cancel());
    _opinionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ApprovalDetail>(
      future: _future,
      builder: (context, snapshot) {
        final revoked = _revoked || _repository.client.authGeneration != _generation;
        // Never display an earlier tenant's approval title after revocation.
        final detail = revoked || snapshot.hasError ? null : snapshot.data ?? widget.initialDetail;
        final colors = AppTheme.colors(context);
        return Scaffold(
          backgroundColor: colors.page,
          body: SafeArea(
            child: Column(
              children: [
                WeTopBar(
                  title: detail?.title ?? '审批详情',
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                ),
                Expanded(
                  child: revoked
                       ? const Center(child: Text('账号已切换，请重新打开审批'))
                       : snapshot.hasError
                      ? Center(
                          child:
                              Column(mainAxisSize: MainAxisSize.min, children: [
                          Semantics(
                            liveRegion: true,
                            child: Text(mobileErrorText(snapshot.error)),
                          ),
                          TextButton(
                              onPressed: () =>
                                  setState(() => _future = _load()),
                              child: const Text('重试')),
                        ]))
                      : detail == null
                          ? Center(
                              child: CircularProgressIndicator(
                                color: colors.brand,
                                semanticsLabel: '正在加载审批详情',
                              ),
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
                                      value: detail.requestNo.ifEmpty(
                                        '#${detail.id}',
                                      ),
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
                                    if (detail.currentNodeName
                                        .trim()
                                        .isNotEmpty)
                                      WeCell(
                                        title: '当前节点',
                                        value: detail.currentNodeName,
                                        showDivider: detail.submittedAt
                                            .trim()
                                            .isNotEmpty,
                                      ),
                                    if (detail.submittedAt.trim().isNotEmpty)
                                      WeCell(
                                        title: '提交时间',
                                        value: detail.submittedAt,
                                        showDivider: detail.description
                                            .trim()
                                            .isNotEmpty,
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
                                          labelText: '审批意见（可选）',
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 16),
                                WeBlockButton(
                                  text: '通过',
                                  onPressed: () => _confirm(true),
                                  enabled: detail.canAct && !_working && !_needsReconciliation &&
                                       !revoked &&
                                      !snapshot.hasError && snapshot.connectionState == ConnectionState.done,
                                ),
                                const SizedBox(height: 8),
                                WeBlockOutlinedButton(
                                  text: '驳回',
                                  onPressed: () => _confirm(false),
                                  enabled: detail.canAct && !_working && !_needsReconciliation &&
                                       !revoked &&
                                      !snapshot.hasError && snapshot.connectionState == ConnectionState.done,
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

  bool _isTerminalApproval(ApprovalDetail detail) =>
      detail.id == widget.id &&
      const {'approved', 'rejected', 'cancelled', 'canceled'}
          .contains(detail.status.trim().toLowerCase());

  Future<ApprovalDetail> _load() async {
    if (_revoked || _repository.client.authGeneration != _generation) {
      throw StateError('账号已切换，请重新打开审批');
    }
    final detail = await _repository.loadApprovalDetail(widget.id);
    final unresolved = await _repository.hasUnknownApprovalOutcome(widget.id);
    if (_revoked || _repository.client.authGeneration != _generation) {
      throw StateError('账号已切换，请重新打开审批');
    }
    if (unresolved && !_isTerminalApproval(detail)) {
      _needsReconciliation = true;
      _status = '原审批回执仍待核对，禁止重复提交。';
    } else if (unresolved) {
      // Only a terminal server snapshot can release a previously uncertain
      // local decision, including after force-stop or process restart.
      await _repository.clearUnknownApprovalOutcome(widget.id);
      _needsReconciliation = false;
    }
    return detail;
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
    if (accepted != true || !mounted || _working || _needsReconciliation) return;
    setState(() => _working = true);
    try {
      // The displayed initial detail is not a write authorization.
      final before = await _load();
      if (!before.canAct || before.id != widget.id) {
        throw StateError('原审批已变更或无权操作，请刷新');
      }
      if (_needsReconciliation) {
        throw StateError('原审批回执待核对，请勿重复提交');
      }
      // Persist BEFORE sending the POST. If the app crashes or times out,
      // its next instance can only query server state, not repeat the write.
      if (!await _repository.markUnknownApprovalOutcome(widget.id)) {
        throw StateError('原审批已被领取或本机核验账本不可用，已阻止审批提交');
      }
      if (!mounted || _revoked || _repository.client.authGeneration != _generation) {
        return;
      }
      final opinion = _opinionController.text.trim();
      _needsReconciliation = true;
      if (approve) {
        await _repository.approveApproval(widget.id, opinion);
      } else {
        await _repository.rejectApproval(widget.id, opinion);
      }
      if (!mounted || _repository.client.authGeneration != _generation) return;
      await _repository.clearUnknownApprovalOutcome(widget.id);
      _needsReconciliation = false;
      setState(() => _status = approve ? '审批已通过' : '审批已驳回');
      Navigator.of(context).maybePop();
    } catch (error) {
      if (!mounted) return;
      if (_needsReconciliation) {
        setState(() => _status = '审批提交结果待核对，请勿重复操作。');
        try {
          final latest = await _load();
          if (!mounted) return;
          setState(() {
            _future = Future.value(latest);
            if (_isTerminalApproval(latest)) {
              _needsReconciliation = false;
              _status = '审批状态已由服务端更新，请查看最新结果';
            }
          });
        } catch (_) {
          // A failed receipt read must not enable the original write again.
        }
      } else {
        setState(() {
          _status = mobileErrorText(error);
          _future = _load();
        });
      }
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
          color: Theme.of(context).colorScheme.onPrimaryContainer,
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
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: colors.brandContainer,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: Theme.of(context).colorScheme.onPrimaryContainer,
            fontSize: 13,
            height: 1.38,
            letterSpacing: 0,
          ),
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}
