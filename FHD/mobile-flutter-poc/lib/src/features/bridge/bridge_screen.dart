import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class BridgeScreen extends StatefulWidget {
  const BridgeScreen({
    super.key,
    this.repository,
    this.initialItems,
    this.title = '服务桥接',
    this.sectionTitle = '待处理工单',
    this.emptyTitle = '暂无工单',
    this.emptySubtitle = '企业端有新工单后会同步到这里',
    this.replyTitle = '回复',
    this.replyPlaceholder = '输入处理意见或补充说明',
    this.submitText = '发送回复',
    this.requestType,
    this.respondedBy = 'android',
  });

  const BridgeScreen.customerService({
    super.key,
    this.repository,
    this.initialItems,
  })  : title = '客户客服',
        sectionTitle = '客户消息',
        emptyTitle = '暂无客户消息',
        emptySubtitle = '企业客户通过专属客服发来的消息会同步到这里',
        replyTitle = '回复客户',
        replyPlaceholder = '输入给客户的回复',
        submitText = '发送回复',
        requestType = MobileRepository.customerServiceRequestType,
        respondedBy = 'mobile-admin-customer-service';

  final MobileRepository? repository;
  final List<BusinessListItem>? initialItems;
  final String title;
  final String sectionTitle;
  final String emptyTitle;
  final String emptySubtitle;
  final String replyTitle;
  final String replyPlaceholder;
  final String submitText;
  final String? requestType;
  final String respondedBy;

  @override
  State<BridgeScreen> createState() => _BridgeScreenState();
}

class _BridgeScreenState extends State<BridgeScreen> {
  late final MobileRepository _repository;
  late Future<List<BusinessListItem>> _future;
  final _replyController = TextEditingController();
  var _selectedId = 0;
  var _working = false;

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
    _replyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final canPop = Navigator.of(context).canPop();
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: widget.title,
              showBack: canPop,
              onBack: canPop ? () => Navigator.of(context).maybePop() : null,
            ),
            Expanded(
              child: FutureBuilder<List<BusinessListItem>>(
                future: _future,
                builder: (context, snapshot) {
                  final items =
                      snapshot.data ?? widget.initialItems ?? const [];
                  final selectedItem = _selectedItem(items);
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      children: [
                        WeSectionCaption(widget.sectionTitle),
                        WeCellGroup(
                          children: [
                            if (items.isEmpty)
                              WeCell(
                                title: widget.emptyTitle,
                                subtitle: widget.emptySubtitle,
                                icon: Icons.forum,
                                iconColor: colors.textSecondary,
                                iconBg: colors.surfaceHigh,
                                showArrow: false,
                                showDivider: false,
                              )
                            else
                              for (var i = 0; i < items.length; i++)
                                WeCell(
                                  title: _itemTitle(items[i]),
                                  subtitle: _itemSubtitle(items[i]),
                                  icon: Icons.forum,
                                  iconColor: _selectedId == _itemId(items[i])
                                      ? colors.brand
                                      : colors.textSecondary,
                                  iconBg: _selectedId == _itemId(items[i])
                                      ? colors.brandContainer
                                      : colors.surfaceHigh,
                                  showDivider: i < items.length - 1,
                                  onTap: () => setState(
                                    () => _selectedId = _itemId(items[i]),
                                  ),
                                ),
                          ],
                        ),
                        if (_customerServiceMode && selectedItem != null) ...[
                          const SizedBox(height: 12),
                          const WeSectionCaption('当前客户'),
                          _CustomerServiceRequestDetail(item: selectedItem),
                        ],
                      ],
                    ),
                  );
                },
              ),
            ),
            _ReplyPanel(
              selectedId: _selectedId,
              controller: _replyController,
              working: _working,
              title: widget.replyTitle,
              placeholder: widget.replyPlaceholder,
              submitText: widget.submitText,
              onChanged: () => setState(() {}),
              onSubmit: _submit,
            ),
          ],
        ),
      ),
    );
  }

  Future<List<BusinessListItem>> _load() async {
    final items = widget.initialItems ??
        await _repository.loadBridgeRequests(requestType: widget.requestType);
    if (_customerServiceMode &&
        mounted &&
        _selectedId <= 0 &&
        items.isNotEmpty) {
      final firstId = _itemId(items.first);
      if (firstId > 0) {
        setState(() => _selectedId = firstId);
      }
    }
    return items;
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }

  Future<void> _submit() async {
    final text = _replyController.text.trim();
    if (_selectedId <= 0 || text.isEmpty) return;
    setState(() => _working = true);
    try {
      await _repository.respondBridgeRequest(
        id: _selectedId,
        response: text,
        respondedBy: widget.respondedBy,
      );
      if (!mounted) return;
      _replyController.clear();
      setState(() {
        _future = _load();
      });
    } catch (_) {
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  int _itemId(BusinessListItem item) {
    return int.tryParse(item.id.trim()) ?? 0;
  }

  bool get _customerServiceMode =>
      widget.requestType == MobileRepository.customerServiceRequestType;

  String _itemTitle(BusinessListItem item) {
    if (!_customerServiceMode) return item.title;
    return _payloadText(item, 'source_instance_name')
        .ifEmpty(_payloadText(item, 'username'))
        .ifEmpty(item.title)
        .ifEmpty('客户消息');
  }

  String _itemSubtitle(BusinessListItem item) {
    if (!_customerServiceMode) return item.subtitle.ifEmpty('等待处理');
    final description = _payloadText(item, 'description').ifEmpty(item.title);
    final status = _payloadText(item, 'status').ifEmpty('pending');
    if (description.isEmpty) return status;
    return '$description · $status';
  }

  String _payloadText(BusinessListItem item, String key) {
    return (item.payload[key]?.toString() ?? '').trim();
  }

  BusinessListItem? _selectedItem(List<BusinessListItem> items) {
    if (_selectedId > 0) {
      for (final item in items) {
        if (_itemId(item) == _selectedId) return item;
      }
    }
    if (_customerServiceMode && items.isNotEmpty) return items.first;
    return null;
  }
}

class _CustomerServiceRequestDetail extends StatelessWidget {
  const _CustomerServiceRequestDetail({required this.item});

  final BusinessListItem item;

  @override
  Widget build(BuildContext context) {
    final description = _text('description').ifEmpty(item.title);
    final response = _text('response');
    final source = _text('source_instance_name').ifEmpty('客户');
    final status = _text('status').ifEmpty('pending');
    return WeCellGroup(
      children: [
        WeCell(
          title: source,
          subtitle: '状态：$status',
          icon: Icons.forum,
          showArrow: false,
        ),
        WeCell(
          title: '客户原话',
          subtitle: description.ifEmpty('暂无内容'),
          icon: Icons.chat_bubble_outline,
          showArrow: false,
        ),
        WeCell(
          title: '已回复',
          subtitle: response.ifEmpty('尚未人工回复'),
          icon: Icons.reply,
          showArrow: false,
          showDivider: false,
        ),
      ],
    );
  }

  String _text(String key) => (item.payload[key]?.toString() ?? '').trim();
}

class _ReplyPanel extends StatelessWidget {
  const _ReplyPanel({
    required this.selectedId,
    required this.controller,
    required this.working,
    required this.title,
    required this.placeholder,
    required this.submitText,
    required this.onChanged,
    required this.onSubmit,
  });

  final int selectedId;
  final TextEditingController controller;
  final bool working;
  final String title;
  final String placeholder;
  final String submitText;
  final VoidCallback onChanged;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      color: colors.surface,
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            WeSectionCaption(
              selectedId > 0 ? '$title #$selectedId' : title,
            ),
            WeCellGroup(
              children: [
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: WeField(
                    controller: controller,
                    placeholder: placeholder,
                    singleLine: false,
                    onChanged: (_) => onChanged(),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            WeBlockButton(
              text: working ? '发送中' : submitText,
              enabled: selectedId > 0 &&
                  controller.text.trim().isNotEmpty &&
                  !working,
              onPressed: onSubmit,
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}
