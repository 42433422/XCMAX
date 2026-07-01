import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_models.dart';
import '../../api/mobile_session_store.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/android_runtime_policy.dart';
import '../../theme/app_theme.dart';
import '../contacts/contacts_screen.dart';
import '../discover/discover_screen.dart';
import '../groups/ai_group_screens.dart';
import '../messages/message_list_screen.dart';
import '../profile/profile_screen.dart';
import '../scan/scan_qr_screen.dart';

const _bottomNavItems = [
  _NavItem('chat', Icons.forum, Icons.forum, '消息'),
  _NavItem('work', Icons.badge, Icons.badge, 'AI员工'),
  _NavItem('discover', Icons.travel_explore, Icons.travel_explore, '探索'),
  _NavItem('profile', Icons.account_circle, Icons.account_circle, '我'),
];

@visibleForTesting
List<Map<String, String>> flutterHomeShellBottomNavItemsForTest() {
  return List.unmodifiable(
    _bottomNavItems.map(
      (item) => {'route': item.route, 'label': item.label},
    ),
  );
}

class HomeShellController {
  final _tabRequests = StreamController<int>.broadcast();

  Stream<int> get tabRequests => _tabRequests.stream;

  void selectTab(int index) {
    if (!_tabRequests.isClosed) _tabRequests.add(index);
  }

  void dispose() {
    _tabRequests.close();
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.repository, this.controller});

  final MobileRepository? repository;
  final HomeShellController? controller;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late final MobileRepository _repository;
  late Future<_HomeData> _homeFuture;
  _HomeData? _visibleHomeData;
  StreamSubscription<int>? _tabSubscription;
  var _index = 0;
  var _homeLoading = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    final cachedFuture = _loadCachedHomeData();
    _homeFuture = cachedFuture;
    unawaited(
      cachedFuture.then((data) {
        if (!mounted) return;
        if (_visibleHomeData != null) return;
        setState(() {
          _visibleHomeData = data;
        });
      }),
    );
    unawaited(Future<void>.microtask(_refreshHomeData));
    _tabSubscription = widget.controller?.tabRequests.listen(_selectTab);
  }

  @override
  void didUpdateWidget(covariant HomeShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller == widget.controller) return;
    _tabSubscription?.cancel();
    _tabSubscription = widget.controller?.tabRequests.listen(_selectTab);
  }

  @override
  void dispose() {
    _tabSubscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      FutureBuilder<_HomeData>(
        future: _homeFuture,
        builder: (context, snapshot) {
          final home = _visibleHomeData ??
              snapshot.data ??
              _HomeData(
                groups: const [],
                conversations: _repository.fallbackConversations(
                  adminMode: false,
                  enterpriseMode: AndroidProductSkuConfig.showsEnterpriseNav(
                    buildSku: MobileAndroidBuild.productSku,
                  ),
                ),
                account: MobileMeData.adminFallback(
                  avatarUrl: _repository.client.localAvatarSource,
                ),
              );
          return MessageListScreen(
            groups: home.groups,
            items: home.conversations,
            account: home.account,
            repository: _repository,
            loading: _homeLoading ||
                snapshot.connectionState == ConnectionState.waiting,
            onRefresh: _refreshHomeData,
            onOpenScan: _openScan,
            onStartGroupChat: _startGroupChat,
            onOpenGroups: _openGroups,
            onOpenEmployees: () => _selectTab(1),
            onOpenContacts: () => _selectTab(1),
            onOpenDiscover: () => _selectTab(2),
          );
        },
      ),
      AiEmployeesScreen(repository: _repository),
      DiscoverScreen(
        repository: _repository,
        onOpenWork: () => _selectTab(1),
      ),
      ProfileScreen(api: _repository.client),
    ];

    return Scaffold(
      backgroundColor: AppTheme.colors(context).page,
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: WeBottomNavBar(
        currentIndex: _index,
        onSelect: _selectTab,
      ),
    );
  }

  Future<_HomeData> _loadHomeData() async {
    final runtime = await _conversationRuntime();
    final results = await Future.wait<Object>([
      _repository.loadAiGroups().catchError(
            (_) => const <AiGroupConversation>[],
          ),
      _loadConversationsWithCacheFallback(runtime),
      _repository.loadMe().catchError((_) => _repository.cachedMe()),
    ]);
    return _HomeData(
      groups: results[0] as List<AiGroupConversation>,
      conversations: results[1] as List<ConversationItem>,
      account: results[2] as MobileMeData,
    );
  }

  Future<List<ConversationItem>> _loadConversationsWithCacheFallback(
    AndroidConversationRuntime runtime,
  ) async {
    try {
      return await _repository.loadConversations(
        adminMode: runtime.adminMode,
        enterpriseMode: runtime.enterpriseMode,
      );
    } catch (_) {
      try {
        return await _repository.loadCachedConversations(
          adminMode: runtime.adminMode,
          enterpriseMode: runtime.enterpriseMode,
        );
      } catch (_) {
        return _repository.fallbackConversations(
          adminMode: runtime.adminMode,
          enterpriseMode: runtime.enterpriseMode,
        );
      }
    }
  }

  Future<_HomeData> _loadCachedHomeData() async {
    final runtime = await _conversationRuntime();
    final account = await _repository.cachedMe().catchError(
          (_) => MobileMeData.adminFallback(
            avatarUrl: _repository.client.localAvatarSource,
          ),
        );
    return _HomeData(
      groups: const [],
      conversations: await _repository
          .loadCachedConversations(
            adminMode: runtime.adminMode,
            enterpriseMode: runtime.enterpriseMode,
          )
          .catchError(
            (_) => _repository.fallbackConversations(
              adminMode: runtime.adminMode,
              enterpriseMode: runtime.enterpriseMode,
            ),
          ),
      account: account,
    );
  }

  Future<AndroidConversationRuntime> _conversationRuntime() async {
    final session = await _repository.client.loadSession().catchError(
          (_) => MobileSessionData.empty,
        );
    return AndroidConversationRuntimePolicy.resolve(
      accountKind: session.accountKind,
      buildSku: MobileAndroidBuild.productSku,
    );
  }

  Future<void> _refreshHomeData() async {
    final future = _loadHomeData();
    setState(() {
      _homeFuture = future;
      _homeLoading = true;
    });
    try {
      final data = await future;
      if (!mounted) return;
      setState(() {
        _visibleHomeData = data;
        _homeLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _homeLoading = false;
      });
    }
  }

  void _selectTab(int index) {
    setState(() => _index = index);
    if (index == 0) {
      unawaited(_refreshHomeData());
    }
  }

  void _openScan() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ScanQrScreen(repository: _repository),
      ),
    );
  }

  Future<void> _startGroupChat() async {
    await Navigator.of(context).push<AiGroupConversation>(
      MaterialPageRoute(
        builder: (_) => AiGroupCreateScreen(repository: _repository),
      ),
    );
    if (mounted) await _refreshHomeData();
  }

  Future<void> _openGroups() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AiGroupListScreen(
          repository: _repository,
          initialGroups: const [],
        ),
      ),
    );
    if (mounted) await _refreshHomeData();
  }
}

class _HomeData {
  const _HomeData({
    required this.groups,
    required this.conversations,
    required this.account,
  });

  final List<AiGroupConversation> groups;
  final List<ConversationItem> conversations;
  final MobileMeData account;
}

class WeBottomNavBar extends StatelessWidget {
  const WeBottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onSelect,
  });

  final int currentIndex;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      key: const ValueKey('bottom_nav_surface_host'),
      color: colors.page,
      child: SafeArea(
        top: false,
        minimum: const EdgeInsets.fromLTRB(20, 6, 20, 10),
        child: Material(
          key: const ValueKey('bottom_nav_capsule'),
          color: colors.surface,
          elevation: 8,
          shadowColor: Colors.black.withValues(alpha: 0.18),
          borderRadius: BorderRadius.circular(30),
          child: SizedBox(
            height: 66,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var index = 0; index < _bottomNavItems.length; index++)
                    Expanded(
                      child: _WeBottomNavTile(
                        item: _bottomNavItems[index],
                        selected: index == currentIndex,
                        onTap: () => onSelect(index),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _WeBottomNavTile extends StatelessWidget {
  const _WeBottomNavTile({
    required this.item,
    required this.selected,
    required this.onTap,
  });

  final _NavItem item;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Semantics(
      button: true,
      selected: selected,
      label: item.label,
      child: Material(
        key: ValueKey('bottom_nav_tile_${item.label}'),
        color: selected ? colors.page : Colors.transparent,
        borderRadius: BorderRadius.circular(24),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(24),
          child: SizedBox.expand(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  selected ? item.selectedIcon : item.icon,
                  semanticLabel: item.label,
                  size: 23,
                  color: selected ? colors.brand : colors.textPrimary,
                ),
                const SizedBox(height: 2),
                Text(
                  item.label,
                  maxLines: 1,
                  style: TextStyle(
                    fontSize: 11,
                    height: 1.2,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                    color: selected ? colors.brand : colors.textStrongSecondary,
                    letterSpacing: 0,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

@visibleForTesting
Rect bottomNavHitRectForTest({
  required Size screenSize,
  required EdgeInsets viewPadding,
  required int itemIndex,
  int itemCount = 4,
}) {
  assert(itemIndex >= 0 && itemIndex < itemCount);
  const outerHorizontal = 20.0;
  const outerBottom = 10.0;
  const navHeight = 66.0;
  const innerHorizontal = 6.0;
  const innerVertical = 6.0;

  const barLeft = outerHorizontal + innerHorizontal;
  final barTop =
      screenSize.height - viewPadding.bottom - outerBottom - navHeight;
  final tileTop = barTop + innerVertical;
  const tileHeight = navHeight - innerVertical * 2;
  final tileWidth =
      (screenSize.width - outerHorizontal * 2 - innerHorizontal * 2) /
          itemCount;
  return Rect.fromLTWH(
    barLeft + itemIndex * tileWidth,
    tileTop,
    tileWidth,
    tileHeight,
  );
}

class _NavItem {
  const _NavItem(this.route, this.icon, this.selectedIcon, this.label);

  final String route;
  final IconData icon;
  final IconData selectedIcon;
  final String label;
}
