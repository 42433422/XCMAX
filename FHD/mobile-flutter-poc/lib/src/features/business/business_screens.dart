import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

enum BusinessListKind {
  customers('客户', Icons.people),
  shipments('发货', Icons.local_shipping),
  inventory('库存', Icons.inventory_2);

  const BusinessListKind(this.title, this.icon);

  final String title;
  final IconData icon;
}

class ErpScreen extends StatefulWidget {
  const ErpScreen({
    super.key,
    this.repository,
    this.initialItemsByKind = const {},
  });

  final MobileRepository? repository;
  final Map<BusinessListKind, List<BusinessListItem>> initialItemsByKind;

  @override
  State<ErpScreen> createState() => _ErpScreenState();
}

class _ErpScreenState extends State<ErpScreen> {
  late final MobileRepository _repository;
  var _selected = BusinessListKind.customers;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
  }

  @override
  Widget build(BuildContext context) {
    return BusinessListScaffold(
      key: ValueKey(_selected),
      title: '业务',
      repository: _repository,
      kind: _selected,
      initialItems: widget.initialItemsByKind[_selected],
      header: _BusinessModeCapsule(
        selected: _selected,
        onSelect: (kind) => setState(() => _selected = kind),
      ),
      sectionTitle: '${_selected.title}记录',
    );
  }
}

class BusinessListScreen extends StatelessWidget {
  const BusinessListScreen({
    super.key,
    required this.kind,
    this.repository,
    this.initialItems,
  });

  final BusinessListKind kind;
  final MobileRepository? repository;
  final List<BusinessListItem>? initialItems;

  @override
  Widget build(BuildContext context) {
    return BusinessListScaffold(
      title: kind.title,
      kind: kind,
      repository: repository,
      initialItems: initialItems,
      sectionTitle: kind.title,
    );
  }
}

class BusinessListScaffold extends StatefulWidget {
  const BusinessListScaffold({
    super.key,
    required this.title,
    required this.kind,
    required this.sectionTitle,
    this.repository,
    this.initialItems,
    this.header,
  });

  final String title;
  final BusinessListKind kind;
  final String sectionTitle;
  final MobileRepository? repository;
  final List<BusinessListItem>? initialItems;
  final Widget? header;

  @override
  State<BusinessListScaffold> createState() => _BusinessListScaffoldState();
}

class _BusinessListScaffoldState extends State<BusinessListScaffold> {
  late final MobileRepository _repository;
  late Future<_BusinessListResult> _future;

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
  void didUpdateWidget(covariant BusinessListScaffold oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.kind != widget.kind ||
        oldWidget.initialItems != widget.initialItems) {
      _future = _load();
    }
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
              title: widget.title,
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
              child: FutureBuilder<_BusinessListResult>(
                future: _future,
                builder: (context, snapshot) {
                  final result = snapshot.data;
                  final items =
                      result?.items ?? widget.initialItems ?? const [];
                  final isInitialLoading =
                      snapshot.connectionState == ConnectionState.waiting &&
                          items.isEmpty;
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: Stack(
                      children: [
                        ListView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          padding: const EdgeInsets.only(bottom: 96),
                          children: [
                            if (widget.header != null) widget.header!,
                            if (isInitialLoading)
                              const _BusinessListSkeleton()
                            else if (result?.error != null && items.isEmpty)
                              _ErrorState(
                                message: result!.error!,
                                onRetry: _refresh,
                              )
                            else ...[
                              WeSectionCaption(widget.sectionTitle),
                              if (items.isEmpty)
                                _EmptyState(
                                  title: widget.kind.title,
                                  onRetry: _refresh,
                                )
                              else
                                WeCellGroup(
                                  children: [
                                    for (var i = 0; i < items.length; i++)
                                      WeCell(
                                        title: items[i].title,
                                        subtitle: items[i].subtitle,
                                        showArrow: false,
                                        showDivider: i < items.length - 1,
                                      ),
                                  ],
                                ),
                            ],
                          ],
                        ),
                        if (snapshot.connectionState ==
                                ConnectionState.waiting &&
                            items.isNotEmpty)
                          Align(
                            alignment: Alignment.topCenter,
                            child: Padding(
                              padding: const EdgeInsets.all(8),
                              child: SizedBox(
                                width: 24,
                                height: 24,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2.5,
                                  color: colors.brand,
                                ),
                              ),
                            ),
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

  Future<_BusinessListResult> _load() async {
    if (widget.initialItems != null) {
      return _BusinessListResult(items: widget.initialItems!);
    }
    try {
      final items = switch (widget.kind) {
        BusinessListKind.customers => await _repository.loadCustomers(),
        BusinessListKind.shipments => await _repository.loadShipments(),
        BusinessListKind.inventory => await _repository.loadInventory(),
      };
      return _BusinessListResult(items: items);
    } catch (error) {
      return _BusinessListResult(
        items: const [],
        error: error.toString().replaceFirst('Exception: ', ''),
      );
    }
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }
}

class _BusinessListResult {
  const _BusinessListResult({required this.items, this.error});

  final List<BusinessListItem> items;
  final String? error;
}

class _BusinessModeCapsule extends StatelessWidget {
  const _BusinessModeCapsule({
    required this.selected,
    required this.onSelect,
  });

  final BusinessListKind selected;
  final ValueChanged<BusinessListKind> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.page,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Container(
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          color: colors.surfaceHigh,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            for (final kind in BusinessListKind.values)
              Expanded(
                child: InkWell(
                  onTap: () => onSelect(kind),
                  borderRadius: BorderRadius.circular(8),
                  child: Container(
                    height: 34,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: selected == kind
                          ? colors.surface
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      kind.title,
                      style: TextStyle(
                        color: selected == kind
                            ? colors.textPrimary
                            : colors.textSecondary,
                        fontSize: 14,
                        height: 1.29,
                        fontWeight: selected == kind
                            ? FontWeight.w600
                            : FontWeight.w400,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.title, required this.onRetry});

  final String title;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 96),
      child: Column(
        children: [
          Text(
            '暂无$title数据',
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 16,
              height: 1.38,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '下拉刷新或连接电脑后重试。',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 15,
              height: 1.4,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(onPressed: onRetry, child: const Text('刷新')),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 96),
      child: Column(
        children: [
          Text(
            '加载失败',
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 16,
              height: 1.38,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            message,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 15,
              height: 1.4,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton(onPressed: onRetry, child: const Text('重试')),
        ],
      ),
    );
  }
}

class _BusinessListSkeleton extends StatelessWidget {
  const _BusinessListSkeleton();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          for (var i = 0; i < 6; i++) ...[
            Container(
              key: ValueKey('business_list_skeleton_$i'),
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: colors.surfaceHigh.withValues(alpha: 0.45),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  FractionallySizedBox(
                    widthFactor: 0.55,
                    child: Container(
                      height: 14,
                      decoration: BoxDecoration(
                        color: colors.divider.withValues(alpha: 0.7),
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  FractionallySizedBox(
                    widthFactor: 0.35,
                    child: Container(
                      height: 12,
                      decoration: BoxDecoration(
                        color: colors.divider.withValues(alpha: 0.55),
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            if (i < 5) const SizedBox(height: 12),
          ],
        ],
      ),
    );
  }
}
