import 'dart:async';

import 'package:flutter/material.dart';
import 'package:skeletonizer/skeletonizer.dart';

import '../../api/mobile_models.dart';
import '../../api/mobile_session_store.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/pinned_ids.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../approval/native_approval_workspace.dart';
import '../business/native_catalog_screen.dart';
import '../business/native_orders_screen.dart';
import '../business/native_materials_screen.dart';
import '../chat/chat_screen.dart';
import '../circle/ai_circle_screen.dart';
import '../scan/scan_qr_screen.dart';
import '../tasks/task_list_screen.dart';
import '../webview/desktop_tool_webview_screen.dart';
import '../workspace/employee_workspace_screen.dart';
import '../workspace/local_workspace_screen.dart';

// Materials are not the stock ledger. Keep inventory on its authorized web
// route until the native page implements balances, not just movement history.
String? nativeMaterialsModForPath(String path) {
  final uri = Uri.tryParse(path);
  if (uri == null || uri.hasScheme || uri.hasAuthority) return null;
  final match =
      RegExp(r'^/(?:mod/([a-zA-Z0-9_-]+)/)?materials/?$').firstMatch(uri.path);
  return match == null ? null : match[1] ?? '';
}

const _discoverNativeRouteMap = <String, String>{
  'ai-circle': 'circle',
  'employee-workflow': 'employee_workspace',
  'workflow-employee-space': 'employee_workspace',
  'tasks': 'tasks',
  'approval-hub': 'approval',
  'photo-files': 'assistant_attachments',
  'pair-desktop': 'scan',
};
const _discoverHiddenKeys = {'chat', 'im', 'settings', 'admin-entitlements'};
const _groups = {
  'community': 'AI交流',
  'tasks': '待办与任务',
  'business': '业务应用',
  'data': '资料与数据',
};
const _authorizedRouteFallbacks = {
  'employee-workflow': '/workflow-employee-space',
  'business-docking': '/business-docking',
  'ai-ecosystem': '/ai-ecosystem',
};
const _staticItems = [
  _WorkbenchItem('local-workspace', '本地工作台', 'data', Icons.folder_open,
      subtitle: '在本机保存客户、商品和订单草稿'),
  _WorkbenchItem('ai-circle', 'AI交流圈', 'community', Icons.bubble_chart,
      subtitle: '看看员工动态与交流'),
  _WorkbenchItem('tasks', '任务', 'tasks', Icons.task_alt, subtitle: '查看进度与处理结果'),
  _WorkbenchItem('approval-hub', '审批', 'tasks', Icons.fact_check_outlined,
      subtitle: '查看需要你确认的事项'),
  _WorkbenchItem(
    'photo-files',
    '拍照与文件',
    'data',
    Icons.add_photo_alternate_outlined,
    subtitle: '交给小C识别和处理',
  ),
];

@visibleForTesting
Map<String, String> flutterDiscoverNativeRouteMapForTest() =>
    Map.unmodifiable(_discoverNativeRouteMap);
@visibleForTesting
Set<String> flutterDiscoverHiddenKeysForTest() =>
    Set.unmodifiable(_discoverHiddenKeys);

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
  late Future<List<MobileDesktopDevice>> _devicesFuture;
  StreamSubscription<MobileSessionData>? _sessionSubscription;
  String? _sessionKey;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _navMenuFuture = _loadScoped(_repository.loadNavMenu);
    _devicesFuture = _loadScoped(_repository.loadDesktopDevices);
    _sessionSubscription = _repository.client.sessionChanges.listen((session) {
      final next =
          '${_repository.client.authGeneration}|${session.serverMode}|${session.fhdHost}|${session.localBaseUrl}';
      final previous = _sessionKey;
      _sessionKey = next;
      if (mounted && previous != null && previous != next) {
        unawaited(_refresh());
      }
    });
  }

  @override
  void dispose() {
    _sessionSubscription?.cancel();
    super.dispose();
  }

  Future<List<T>> _loadScoped<T>(Future<List<T>> Function() load) async {
    final api = _repository.client;
    final generation = api.authGeneration;
    final base = await api.resolveSessionBaseUrl();
    if (generation != api.authGeneration) throw StateError('账号已切换，请刷新');
    final result = await load();
    final currentBase = await api.resolveSessionBaseUrl();
    if (generation != api.authGeneration || base != currentBase) {
      throw StateError('账号或连接已切换，请刷新');
    }
    return result;
  }

  Future<void> _refresh() async {
    final nav = _loadScoped(_repository.loadNavMenu);
    final devices = _loadScoped(_repository.loadDesktopDevices);
    setState(() {
      _navMenuFuture = nav;
      _devicesFuture = devices;
    });
    await Future.wait([
      nav,
      devices,
    ]).then<void>((_) {}, onError: (Object _, StackTrace __) {});
  }

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: AppTheme.colors(context).page,
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              WeTopBar(
                title: '工作台',
                actions: [
                  IconButton(
                    onPressed: _refresh,
                    icon: const Icon(Icons.refresh),
                    tooltip: '刷新工作台',
                  ),
                ],
              ),
              Expanded(
                child: FutureBuilder<List<MobileNavMenuItem>>(
                  future: _navMenuFuture,
                  builder: (context, nav) =>
                      FutureBuilder<List<MobileDesktopDevice>>(
                    future: _devicesFuture,
                    builder: (context, devices) => _content(nav, devices),
                  ),
                ),
              ),
            ],
          ),
        ),
      );

  Widget _content(
    AsyncSnapshot<List<MobileNavMenuItem>> nav,
    AsyncSnapshot<List<MobileDesktopDevice>> devices,
  ) {
    final loading = nav.connectionState != ConnectionState.done;
    final items = {for (final item in _staticItems) item.key: item};
    if (!loading && !nav.hasError) {
      for (final item in nav.data ?? const <MobileNavMenuItem>[]) {
        if (_discoverHiddenKeys.contains(item.key)) continue;
        final group = _groups.containsKey(item.mobileGroup) ||
                item.mobileGroup == 'computer'
            ? item.mobileGroup
            : 'business';
        final existing = items[item.key];
        items[item.key] = _WorkbenchItem(
          item.key,
          item.name,
          existing?.group ?? group,
          existing?.icon ?? _iconFor(item),
          path: item.path.trim().isNotEmpty
              ? _nativeBusinessPath(item.path, nav.data ?? const [])
              : _authorizedRouteFallbacks[item.key] ?? existing?.path ?? '',
          requiresDesktop: item.requiresDesktop,
          subtitle: existing?.subtitle ?? '',
        );
      }
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          if (!loading && nav.hasError)
            _status(
              '应用加载失败',
              '任务与基础入口仍可使用',
              () => setState(() {
                _navMenuFuture = _loadScoped(_repository.loadNavMenu);
              }),
            ),
          for (final group in _groups.entries) ...[
            WeSectionCaption(group.value),
            if (items.values.any((item) => item.group == group.key))
              WeCellGroup(
                children: [
                  for (final item in items.values.where(
                    (item) => item.group == group.key,
                  ))
                    _itemCell(item, devices),
                ],
              )
            else if (loading)
              _loadingSurface(
                  'applications',
                  '正在读取业务应用…',
                  WeCellGroup(children: [
                    for (var index = 0; index < 2; index++)
                      _itemCell(
                          _WorkbenchItem('loading-$index', '应用入口名称', 'business',
                              Icons.apps),
                          devices),
                  ]))
            else
              WeCellGroup(children: [
                _status(
                  nav.hasError ? '业务应用暂时无法读取' : '暂无可用业务应用',
                  '',
                  null,
                )
              ]),
          ],
          const WeSectionCaption('我的电脑'),
          _devicePanel(devices),
          const SizedBox(height: 8),
          WeCellGroup(
            children: [
              WeCell(
                key: const ValueKey('workbench-pair-desktop'),
                title: '扫码绑定电脑',
                subtitle: '连接你的桌面端',
                icon: Icons.qr_code_scanner,
                onTap: _openScan,
                showDivider: false,
              ),
              for (final item in items.values.where(
                (item) => item.group == 'computer',
              ))
                _itemCell(item, devices),
            ],
          ),
        ],
      ),
    );
  }

  Widget _loadingSurface(String id, String label, Widget layout) {
    final colors = AppTheme.colors(context);
    final reduceMotion = MediaQuery.disableAnimationsOf(context) ||
        MediaQuery.accessibleNavigationOf(context);
    return Semantics(
      container: true,
      liveRegion: true,
      label: label,
      child: ExcludeSemantics(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
            child: Text(label,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: colors.textSecondary))),
        Skeletonizer(
          key: ValueKey('workbench-$id-skeleton'),
          effect: reduceMotion
              ? SolidColorEffect(color: colors.surfaceHigh)
              : ShimmerEffect(
                  baseColor: colors.surfaceHigh,
                  highlightColor: colors.surface),
          enableSwitchAnimation: false,
          ignorePointers: true,
          child: ExcludeFocus(child: layout),
        ),
      ])),
    );
  }

  Widget _devicePanel(AsyncSnapshot<List<MobileDesktopDevice>> snapshot) {
    if (snapshot.connectionState != ConnectionState.done) {
      return _loadingSurface(
          'devices', '正在读取电脑状态…', WeCellGroup(children: [_deviceCard(null)]));
    }
    if (snapshot.hasError) {
      return WeCellGroup(children: [
        _status(
            '无法确认电脑状态',
            '请检查连接后重试',
            () => setState(() {
                  _devicesFuture = _loadScoped(_repository.loadDesktopDevices);
                }))
      ]);
    }
    final devices = snapshot.data ?? const <MobileDesktopDevice>[];
    if (devices.isEmpty) {
      return WeCellGroup(children: [_status('尚未绑定电脑', '绑定后可在这里查看电脑状态', null)]);
    }
    return Column(children: [
      for (var index = 0; index < devices.length; index++)
        Padding(
            padding: EdgeInsets.only(top: index == 0 ? 0 : 8),
            child: WeCellGroup(children: [_deviceCard(devices[index])])),
    ]);
  }

  Widget _deviceCard(MobileDesktopDevice? device) {
    final colors = AppTheme.colors(context);
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final online = device?.online ?? false;
    final statusColor =
        online ? scheme.onSecondaryContainer : colors.textSecondary;
    final name = device == null
        ? '电脑名称'
        : device.label.isNotEmpty
            ? device.label
            : device.platform.isNotEmpty
                ? '${device.platform} 电脑'
                : '电脑';
    final platform = device == null ? '设备平台' : device.platform;
    return MergeSemantics(
        child: Padding(
      key: ValueKey('workbench-device-${device?.deviceId ?? 'loading'}'),
      padding: const EdgeInsets.all(16),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
            width: 44,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
                color: online ? colors.brandContainer : colors.surfaceHigh,
                borderRadius: BorderRadius.circular(12)),
            child: Icon(
                platform.toLowerCase().contains('mac')
                    ? Icons.laptop_mac
                    : Icons.computer_outlined,
                color: online ? colors.brand : colors.textSecondary,
                size: 24)),
        const SizedBox(width: 12),
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(name,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: text.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600, color: colors.textPrimary)),
          const SizedBox(height: 8),
          Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                        color: online
                            ? scheme.secondaryContainer
                            : colors.surfaceHigh,
                        borderRadius: BorderRadius.circular(20)),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Container(
                          width: 5,
                          height: 5,
                          decoration: BoxDecoration(
                              color: statusColor, shape: BoxShape.circle)),
                      const SizedBox(width: 5),
                      Text(
                          device == null
                              ? '连接状态'
                              : online
                                  ? '在线'
                                  : '离线',
                          style: text.labelSmall?.copyWith(
                              color: statusColor, fontWeight: FontWeight.w600)),
                    ])),
                if (platform.isNotEmpty)
                  Text(platform,
                      style: text.bodySmall
                          ?.copyWith(color: colors.textSecondary)),
              ]),
          const SizedBox(height: 8),
          Text('最近在线：${device == null ? '正在获取' : _lastSeen(device.lastSeenAt)}',
              style: text.bodySmall?.copyWith(color: colors.textSecondary)),
        ])),
      ]),
    ));
  }

  Widget _status(String title, String subtitle, VoidCallback? retry) =>
      ListTile(
        title: Text(title),
        subtitle: subtitle.isEmpty ? null : Text(subtitle),
        trailing: retry == null
            ? null
            : TextButton(onPressed: retry, child: const Text('重试')),
      );

  Widget _itemCell(
    _WorkbenchItem item,
    AsyncSnapshot<List<MobileDesktopDevice>> devices,
  ) {
    final color = switch (item.group) {
      'tasks' => AppTheme.colors(context).success,
      'data' => Theme.of(context).colorScheme.tertiary,
      'computer' => AppTheme.colors(context).warning,
      _ => AppTheme.colors(context).brand,
    };
    final hint =
        devices.connectionState != ConnectionState.done || devices.hasError
            ? '电脑状态待确认'
            : (devices.data?.any((device) => device.online) ?? false)
                ? '有电脑在线'
                : '暂无在线电脑';
    return WeCell(
      key: ValueKey('workbench-${item.key}'),
      title: item.title,
      subtitle: item.requiresDesktop ? '需要电脑执行 · $hint' : item.subtitle,
      icon: item.icon,
      iconColor: color,
      iconBg: color.withValues(alpha: 0.12),
      onTap: () => _open(item),
      showDivider: false,
    );
  }

  String _nativeBusinessPath(String path, List<MobileNavMenuItem> menu) {
    if (!const ['/products', '/customers', '/orders', '/shipment-records']
        .contains(path)) {
      return path;
    }
    // Desktop core ERP pages use the installed domain facade. Only select it
    // when this account's navigation actually authorizes the same page.
    final facade = '/mod/xcagi-erp-domain-bridge$path';
    return menu.any((entry) => entry.path == facade) ? facade : path;
  }

  void _open(_WorkbenchItem item) {
    if (item.key == 'local-workspace') {
      Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => const LocalWorkspaceScreen(),
      ));
      return;
    }
    final material = nativeMaterialsModForPath(item.path);
    if (material != null) {
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => NativeMaterialsScreen(
              repository: _repository,
              title: item.title,
              activeModId: material)));
      return;
    }
    final approval = RegExp(
            r'^/(?:mod/([a-zA-Z0-9_-]+)/)?approval-hub(?:/(workspace|flow-management))?/?$')
        .firstMatch(Uri.tryParse(item.path)?.path ?? '');
    if (approval != null || item.key == 'approval-hub' && item.path.isEmpty) {
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => NativeApprovalWorkspace(
                repository: _repository,
                apiBase: approval?[1] == null
                    ? 'api/approval'
                    : 'api/mod/${approval![1]}',
                initialTab: approval?[2] == 'flow-management' ? 2 : 0,
              )));
      return;
    }
    final orderRoute =
        RegExp(r'^/(?:mod/([a-zA-Z0-9_-]+)/)?orders/?$').firstMatch(item.path);
    if (orderRoute != null) {
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => NativeOrdersScreen(
              repository: _repository,
              apiBase:
                  orderRoute[1] == null ? 'api' : 'api/mod/${orderRoute[1]}')));
      return;
    }
    final catalog = nativeCatalogRoute(item.path);
    if (catalog != null) {
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => NativeCatalogScreen(
              repository: _repository,
              resource: catalog.resource,
              apiBase: catalog.base,
              title: item.title)));
      return;
    }
    final Widget screen;
    switch (item.key) {
      case 'employee-workflow':
      case 'workflow-employee-space':
        screen = EmployeeWorkspaceScreen(repository: _repository);
      case 'ai-circle':
        screen = AiCircleScreen(repository: _repository);
      case 'tasks':
        screen = TaskListScreen(repository: _repository);
      case 'photo-files':
        screen = ChatScreen(
          repository: _repository,
          initialMessages: const [],
          conversation: const ConversationItem(
            id: PinnedIds.assistant,
            type: ConversationType.pinnedAssistant,
            title: '小C',
            subtitle: '',
            timestampText: '',
          ),
        );
      default:
        if (item.path.trim().isEmpty) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(const SnackBar(content: Text('该应用暂未提供手机入口')));
          return;
        }
        screen = DesktopToolWebViewScreen(
          title: item.title,
          path: item.path,
          api: _repository.client,
        );
    }
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
  }

  Future<void> _openScan() async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ScanQrScreen(repository: _repository)),
    );
    if (mounted) await _refresh();
  }
}

class _WorkbenchItem {
  const _WorkbenchItem(
    this.key,
    this.title,
    this.group,
    this.icon, {
    this.path = '',
    this.subtitle = '',
    this.requiresDesktop = false,
  });
  final String key, title, group, path, subtitle;
  final IconData icon;
  final bool requiresDesktop;
}

IconData _iconFor(MobileNavMenuItem item) {
  if (item.key == 'ai-ecosystem') return Icons.hub_outlined;
  if (item.icon.contains('print')) return Icons.print_outlined;
  if (item.icon.contains('database')) return Icons.dataset_outlined;
  if (item.key.contains('customer')) return Icons.groups_outlined;
  if (item.key.contains('order') || item.key.contains('shipment')) {
    return Icons.receipt_long_outlined;
  }
  if (item.key.contains('product') || item.key.contains('inventory')) {
    return Icons.inventory_2_outlined;
  }
  return item.mobileGroup == 'data' ? Icons.folder_open : Icons.apps;
}

String _lastSeen(String raw) {
  if (raw.trim().isEmpty) return '暂无记录';
  final parsed = DateTime.tryParse(raw)?.toLocal();
  if (parsed == null) return raw;
  String two(int value) => value.toString().padLeft(2, '0');
  return '${parsed.year}-${two(parsed.month)}-${two(parsed.day)} ${two(parsed.hour)}:${two(parsed.minute)}';
}
