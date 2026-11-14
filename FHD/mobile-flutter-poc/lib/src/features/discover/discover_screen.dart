import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../approval/approval_screens.dart';
import '../circle/ai_circle_screen.dart';
import '../contacts/contacts_screen.dart';
import '../notifications/notification_list_screen.dart';
import '../scan/scan_qr_screen.dart';
import '../settings/settings_screen.dart';
import '../tools/ocr_screen.dart';
import '../webview/desktop_tool_webview_screen.dart';

const _discoverNativeRouteMap = <String, String>{
  'chat': 'ai_chat',
  'im': 'im',
  'ai-ecosystem': 'ai_employees',
  'employee-workflow': 'work',
  'settings': 'settings',
};

const _discoverHiddenKeys = {'chat', 'im'};

@visibleForTesting
Map<String, String> flutterDiscoverNativeRouteMapForTest() {
  return Map.unmodifiable(_discoverNativeRouteMap);
}

@visibleForTesting
Set<String> flutterDiscoverHiddenKeysForTest() {
  return Set.unmodifiable(_discoverHiddenKeys);
}

class DiscoverScreen extends StatefulWidget {
  const DiscoverScreen({super.key, this.repository, this.onOpenWork});

  final MobileRepository? repository;
  final VoidCallback? onOpenWork;

  @override
  State<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends State<DiscoverScreen> {
  late final MobileRepository _repository;
  late Future<List<MobileNavMenuItem>> _navMenuFuture;

  static const _fallbackDesktopTools = <_DiscoverItem>[
    _DiscoverItem(
      key: 'pair-desktop',
      title: '扫码绑定电脑端',
      icon: Icons.qr_code_scanner,
    ),
  ];

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _navMenuFuture = _repository.loadNavMenu();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      color: colors.surface,
      child: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const WeTopBar(title: '探索'),
            Expanded(
              child: FutureBuilder<List<MobileNavMenuItem>>(
                future: _navMenuFuture,
                builder: (context, snapshot) {
                  final desktopTools = _desktopToolsFromNav(
                    snapshot.data ?? const <MobileNavMenuItem>[],
                  );
                  return ListView(
                    padding: EdgeInsets.zero,
                    children: [
                      const WeSectionCaption('AI交流'),
                      WeCellGroup(
                        children: [
                          WeCell(
                            title: 'AI交流圈',
                            icon: Icons.forum,
                            iconColor: colors.brand,
                            iconBg: colors.brandContainer,
                            onTap: _openAiCircle,
                            showDivider: false,
                          ),
                        ],
                      ),
                      const WeSectionCaption('桌面工具'),
                      WeCellGroup(
                        children: [
                          for (var i = 0; i < desktopTools.length; i++)
                            WeCell(
                              title: desktopTools[i].title,
                              icon: desktopTools[i].icon,
                              iconColor: _toneColor(
                                context,
                                desktopTools[i].tone,
                              ),
                              iconBg: _toneColor(
                                context,
                                desktopTools[i].tone,
                              ).withValues(alpha: 0.12),
                              onTap: () => _openDesktopTool(desktopTools[i]),
                              showDivider: i < desktopTools.length - 1,
                            ),
                        ],
                      ),
                      const WeSectionCaption('工具'),
                      WeCellGroup(
                        children: [
                          WeCell(
                            title: '审批',
                            icon: Icons.fact_check,
                            iconColor: colors.success,
                            iconBg: colors.success.withValues(alpha: 0.12),
                            onTap: _openApprovals,
                          ),
                          WeCell(
                            title: '扫码绑定',
                            icon: Icons.qr_code_scanner,
                            iconColor: colors.warning,
                            iconBg: colors.warning.withValues(alpha: 0.12),
                            onTap: _openScan,
                          ),
                          WeCell(
                            title: 'OCR识别',
                            icon: Icons.camera_alt,
                            iconColor: Theme.of(context).colorScheme.tertiary,
                            iconBg: Theme.of(
                              context,
                            ).colorScheme.tertiaryContainer,
                            onTap: _openOcr,
                          ),
                          WeCell(
                            title: '通知与公告',
                            icon: Icons.notifications,
                            iconColor: colors.danger,
                            iconBg: Theme.of(
                              context,
                            ).colorScheme.errorContainer,
                            onTap: _openNotifications,
                            showDivider: false,
                          ),
                        ],
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<_DiscoverItem> _desktopToolsFromNav(List<MobileNavMenuItem> menu) {
    final visible = menu
        .where((item) => !_discoverHiddenKeys.contains(item.key))
        .map(
          (item) => _DiscoverItem(
            key: item.key,
            path: item.path,
            source: item.source,
            modId: item.modId ?? '',
            title: item.name,
            icon: _iconForNav(item),
            tone: _toneForNav(item),
          ),
        )
        .toList(growable: false);
    if (visible.isEmpty) return _fallbackDesktopTools;
    return _spreadAdjacentTones(visible);
  }

  /// 相邻两项同色时顺延色板，避免整列看起来重复。
  List<_DiscoverItem> _spreadAdjacentTones(List<_DiscoverItem> items) {
    final result = <_DiscoverItem>[];
    var previous = -1;
    for (final item in items) {
      var tone = item.tone;
      if (tone == previous) tone = (tone + 1) % 6;
      result.add(
        _DiscoverItem(
          key: item.key,
          path: item.path,
          source: item.source,
          modId: item.modId,
          title: item.title,
          icon: item.icon,
          tone: tone,
        ),
      );
      previous = tone;
    }
    return result;
  }

  IconData _iconForNav(MobileNavMenuItem item) {
    final key = item.key.toLowerCase();
    if (key == 'chat' || item.icon.contains('comment')) return Icons.chat;
    if (key == 'im' || item.icon.contains('envelope')) return Icons.forum;
    if (key == 'ai-ecosystem' || item.icon.contains('sitemap')) {
      return Icons.hub;
    }
    if (key == 'employee-workflow' ||
        key.contains('employee') ||
        item.icon.contains('users')) {
      return Icons.workspaces;
    }
    if (key.contains('organization') || key.contains('org')) {
      return Icons.account_tree;
    }
    if (key.contains('product') || item.icon.contains('cube')) {
      return Icons.inventory_2;
    }
    if (key.contains('customer') || key.contains('contact')) {
      return Icons.groups;
    }
    if (key.contains('order') || key.contains('shipment')) {
      return Icons.receipt_long;
    }
    if (key.contains('record') || key.contains('history')) {
      return Icons.history;
    }
    if (key.contains('resource') || key.contains('asset')) {
      return Icons.folder_copy;
    }
    if (key.contains('data') || item.icon.contains('database')) {
      return Icons.dataset;
    }
    if (key.contains('finance') || key.contains('wallet')) {
      return Icons.account_balance_wallet;
    }
    if (key.contains('print') || item.icon.contains('print')) {
      return Icons.print;
    }
    if (key.contains('setting') || item.icon.contains('cog')) {
      return Icons.settings;
    }
    if (item.source == 'mod') return Icons.extension;
    return Icons.widgets;
  }

  int _toneForNav(MobileNavMenuItem item) {
    final key = item.key.toLowerCase();
    final text = '${item.key} ${item.name}'.toLowerCase();
    if (text.contains('智能') ||
        text.contains('生态') ||
        key.contains('ai-') ||
        key == 'ai') {
      return 0;
    }
    if (text.contains('员工') ||
        text.contains('组织') ||
        text.contains('工作台') ||
        text.contains('employee') ||
        text.contains('org')) {
      return 1;
    }
    if (text.contains('对象') ||
        text.contains('客户') ||
        text.contains('商品') ||
        text.contains('产品') ||
        text.contains('product')) {
      return 2;
    }
    if (text.contains('资源') || text.contains('数据') || text.contains('data')) {
      return 3;
    }
    if (text.contains('单据') ||
        text.contains('订单') ||
        text.contains('记录') ||
        text.contains('打印') ||
        text.contains('模板') ||
        text.contains('order') ||
        text.contains('print')) {
      return 4;
    }
    if (text.contains('系统') ||
        text.contains('设置') ||
        text.contains('setting')) {
      return 5;
    }
    return item.key.hashCode.abs() % 6;
  }

  void _openDesktopTool(_DiscoverItem item) {
    switch (item.key) {
      case 'pair-desktop':
        _openScan();
        return;
      case 'ai-ecosystem':
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (routeContext) => AiEmployeesScreen(
              repository: _repository,
              onBack: () => Navigator.of(routeContext).pop(),
            ),
          ),
        );
        return;
      case 'employee-workflow':
        final callback = widget.onOpenWork;
        if (callback != null) {
          callback();
          return;
        }
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (routeContext) => AiEmployeesScreen(
              repository: _repository,
              onBack: () => Navigator.of(routeContext).pop(),
            ),
          ),
        );
        return;
      case 'settings':
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => SettingsScreen(api: _repository.client),
          ),
        );
        return;
      default:
        _openDesktopWebView(title: item.title, path: item.path);
    }
  }

  void _openDesktopWebView({required String title, required String path}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DesktopToolWebViewScreen(title: title, path: path),
      ),
    );
  }

  void _openAiCircle() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AiCircleScreen(repository: _repository),
      ),
    );
  }

  void _openApprovals() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ApprovalListScreen(repository: _repository),
      ),
    );
  }

  void _openNotifications() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => NotificationListScreen(repository: _repository),
      ),
    );
  }

  void _openScan() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ScanQrScreen(repository: _repository)),
    );
  }

  void _openOcr() {
    Navigator.of(
      context,
    ).push(MaterialPageRoute(builder: (_) => const OcrScreen()));
  }
}

class _DiscoverItem {
  const _DiscoverItem({
    this.key = '',
    this.path = '',
    this.source = '',
    this.modId = '',
    required this.title,
    required this.icon,
    this.tone = 0,
  });

  final String key;
  final String path;
  final String source;
  final String modId;
  final String title;
  final IconData icon;
  final int tone;
}

Color _toneColor(BuildContext context, int tone) {
  final colors = AppTheme.colors(context);
  return switch (tone) {
    0 => colors.brand,
    1 => colors.success,
    2 => colors.warning,
    3 => Theme.of(context).colorScheme.tertiary,
    4 => const Color(0xFF0EA5A4),
    _ => Theme.of(context).colorScheme.secondary,
  };
}
