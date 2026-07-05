import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
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
  const DiscoverScreen({
    super.key,
    this.repository,
    this.onOpenWork,
  });

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
      subtitle: '绑定后，电脑端侧栏的工具会同步到这里',
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
                            subtitle: '查看企业 AI 员工动态、主页和能力介绍',
                            icon: Icons.forum,
                            iconColor: colors.brand,
                            iconBg: colors.brandContainer,
                            onTap: _openAiCircle,
                            showDivider: false,
                          ),
                        ],
                      ),
                      const WeSectionCaption('桌面工具（与电脑端侧栏对齐）'),
                      WeCellGroup(
                        children: [
                          for (var i = 0; i < desktopTools.length; i++)
                            WeCell(
                              title: desktopTools[i].title,
                              subtitle: desktopTools[i].subtitle,
                              icon: desktopTools[i].icon,
                              iconColor: colors.brand,
                              iconBg: colors.brandContainer,
                              onTap: () => _openDesktopTool(desktopTools[i]),
                              showDivider: i < desktopTools.length - 1,
                            ),
                        ],
                      ),
                      const WeSectionCaption('工具'),
                      WeCellGroup(
                        children: [
                          WeCell(
                            title: '扫码绑定',
                            subtitle: '绑定企业端、管理端或电脑端登录',
                            icon: Icons.qr_code_scanner,
                            iconColor: colors.brand,
                            iconBg: colors.brandContainer,
                            onTap: _openScan,
                          ),
                          WeCell(
                            title: 'OCR识别',
                            subtitle: '拍照识别文字与文档',
                            icon: Icons.camera_alt,
                            iconColor: Theme.of(context).colorScheme.tertiary,
                            iconBg:
                                Theme.of(context).colorScheme.tertiaryContainer,
                            onTap: _openOcr,
                          ),
                          WeCell(
                            title: '通知与公告',
                            subtitle: '企业公告与系统通知',
                            icon: Icons.notifications,
                            iconColor: colors.danger,
                            iconBg:
                                Theme.of(context).colorScheme.errorContainer,
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
            subtitle: item.source == 'mod'
                ? 'Mod: ${(item.modId ?? item.key).trim()}'
                : '点击打开',
            icon: _iconForNav(item),
          ),
        )
        .toList(growable: false);
    return visible.isEmpty ? _fallbackDesktopTools : visible;
  }

  IconData _iconForNav(MobileNavMenuItem item) {
    if (item.key == 'chat' || item.icon.contains('comment')) {
      return Icons.chat;
    }
    if (item.key == 'im' || item.icon.contains('envelope')) {
      return Icons.forum;
    }
    if (item.key == 'ai-ecosystem' || item.icon.contains('sitemap')) {
      return Icons.account_tree;
    }
    if (item.key == 'employee-workflow' || item.icon.contains('users')) {
      return Icons.group;
    }
    if (item.key == 'products' || item.icon.contains('cube')) {
      return Icons.apps;
    }
    if (item.key == 'orders' || item.icon.contains('file')) {
      return Icons.description;
    }
    if (item.key == 'print' || item.icon.contains('print')) {
      return Icons.print;
    }
    if (item.key == 'data-sources' || item.icon.contains('database')) {
      return Icons.storage;
    }
    if (item.key == 'settings' || item.icon.contains('cog')) {
      return Icons.settings;
    }
    if (item.source == 'mod') {
      return Icons.apps;
    }
    return Icons.build;
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
              builder: (_) => SettingsScreen(api: _repository.client)),
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
          builder: (_) => AiCircleScreen(repository: _repository)),
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
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const OcrScreen()),
    );
  }
}

class _DiscoverItem {
  const _DiscoverItem({
    this.key = '',
    this.path = '',
    this.source = '',
    this.modId = '',
    required this.title,
    required this.subtitle,
    required this.icon,
  });

  final String key;
  final String path;
  final String source;
  final String modId;
  final String title;
  final String subtitle;
  final IconData icon;
}
