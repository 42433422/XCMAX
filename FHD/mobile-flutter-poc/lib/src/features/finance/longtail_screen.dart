import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class LongTailScreen extends StatefulWidget {
  const LongTailScreen({
    super.key,
    this.repository,
    this.initialDetail = '',
  });

  final MobileRepository? repository;
  final String initialDetail;

  @override
  State<LongTailScreen> createState() => _LongTailScreenState();
}

class _LongTailScreenState extends State<LongTailScreen> {
  late final MobileRepository _repository;
  late Future<String> _future;

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
            const WeTopBar(title: '财务摘要'),
            Expanded(
              child: FutureBuilder<String>(
                future: _future,
                builder: (context, snapshot) {
                  final detail = snapshot.data ?? widget.initialDetail;
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.only(bottom: 96),
                      children: [
                        const WeSectionCaption('概览'),
                        WeCellGroup(
                          children: [
                            WeCell(
                              title:
                                  detail.trim().isEmpty ? '暂无财务数据' : '财务看板已同步',
                              subtitle: _financePreview(detail),
                              icon: Icons.analytics,
                              iconColor: colors.brand,
                              iconBg: colors.brandContainer,
                              showArrow: false,
                              showDivider: false,
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        const WeSectionCaption('操作'),
                        WeCellGroup(
                          children: [
                            WeCell(
                              title: '凭证与收支',
                              subtitle: '查看应收、应付与交易记录',
                              icon: Icons.receipt_long,
                              iconColor: colors.success,
                              iconBg: Theme.of(context)
                                  .colorScheme
                                  .secondaryContainer,
                              onTap: () => _showMessage('请在电脑端打开完整财务看板'),
                            ),
                            WeCell(
                              title: '标签打印',
                              subtitle: '打印商品标签和条码模板',
                              icon: Icons.local_printshop,
                              iconColor: colors.warning,
                              iconBg: colors.warning.withValues(alpha: 0.12),
                              onTap: () => _showMessage('请在电脑端完成标签打印'),
                              showDivider: false,
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

  Future<String> _load() async {
    if (widget.initialDetail.trim().isNotEmpty) return widget.initialDetail;
    try {
      return await _repository.loadFinanceSummary();
    } catch (_) {
      return '';
    }
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }
}

String _financePreview(String raw) {
  if (raw.trim().isEmpty) {
    return '连接企业后端后显示收入、成本、毛利与应付摘要';
  }
  return raw
      .replaceAll('{', '')
      .replaceAll('}', '')
      .replaceAll('success=true,', '')
      .replaceAll('data=', '')
      .split(',')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .take(3)
      .join(' · ')
      .characters
      .take(120)
      .toString();
}
