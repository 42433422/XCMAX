import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum AndroidDeepLinkTarget {
  chat,
  work,
  discover,
  profile,
  aiChat,
  conversationChat,
  csChat,
  fixedPartnerProfile,
  market,
  mods,
  modWeb,
  desktopWebView,
  aiEmployees,
  aiCircle,
  aiGroups,
  aiGroupCreate,
  scanQr,
  approvalList,
  approvalDetail,
  aiEmployeeProfile,
  settings,
  about,
  notifications,
  ocr,
  bridge,
  erp,
  erpTab,
  im,
  connect,
  connectPc,
  onboarding,
  register,
  smartAnalysis,
  aiOpen,
  brain,
  modStore,
  longtail,
}

class AndroidDeepLinkDestination {
  const AndroidDeepLinkDestination._(
    this.target, {
    this.approvalId,
    this.modId,
    this.employeeId,
    this.conversationId,
    this.partnerKind,
    this.tabIndex,
    this.path,
    this.title,
  });

  const AndroidDeepLinkDestination.chat() : this._(AndroidDeepLinkTarget.chat);

  const AndroidDeepLinkDestination.work() : this._(AndroidDeepLinkTarget.work);

  const AndroidDeepLinkDestination.discover()
      : this._(AndroidDeepLinkTarget.discover);

  const AndroidDeepLinkDestination.profile()
      : this._(AndroidDeepLinkTarget.profile);

  const AndroidDeepLinkDestination.aiChat()
      : this._(AndroidDeepLinkTarget.aiChat);

  const AndroidDeepLinkDestination.conversationChat(String conversationId)
      : this._(
          AndroidDeepLinkTarget.conversationChat,
          conversationId: conversationId,
        );

  const AndroidDeepLinkDestination.csChat()
      : this._(AndroidDeepLinkTarget.csChat);

  const AndroidDeepLinkDestination.fixedPartnerProfile(String partnerKind)
      : this._(
          AndroidDeepLinkTarget.fixedPartnerProfile,
          partnerKind: partnerKind,
        );

  const AndroidDeepLinkDestination.market()
      : this._(AndroidDeepLinkTarget.market);

  const AndroidDeepLinkDestination.mods() : this._(AndroidDeepLinkTarget.mods);

  const AndroidDeepLinkDestination.modWeb(String modId)
      : this._(AndroidDeepLinkTarget.modWeb, modId: modId);

  const AndroidDeepLinkDestination.desktopWebView({
    required String path,
    required String title,
  }) : this._(
          AndroidDeepLinkTarget.desktopWebView,
          path: path,
          title: title,
        );

  const AndroidDeepLinkDestination.aiEmployees()
      : this._(AndroidDeepLinkTarget.aiEmployees);

  const AndroidDeepLinkDestination.aiCircle()
      : this._(AndroidDeepLinkTarget.aiCircle);

  const AndroidDeepLinkDestination.aiGroups()
      : this._(AndroidDeepLinkTarget.aiGroups);

  const AndroidDeepLinkDestination.aiGroupCreate()
      : this._(AndroidDeepLinkTarget.aiGroupCreate);

  const AndroidDeepLinkDestination.scanQr()
      : this._(AndroidDeepLinkTarget.scanQr);

  const AndroidDeepLinkDestination.approvalList()
      : this._(AndroidDeepLinkTarget.approvalList);

  const AndroidDeepLinkDestination.approvalDetail(int id)
      : this._(AndroidDeepLinkTarget.approvalDetail, approvalId: id);

  const AndroidDeepLinkDestination.aiEmployeeProfile({
    required String modId,
    required String employeeId,
  }) : this._(
          AndroidDeepLinkTarget.aiEmployeeProfile,
          modId: modId,
          employeeId: employeeId,
        );

  const AndroidDeepLinkDestination.settings()
      : this._(AndroidDeepLinkTarget.settings);

  const AndroidDeepLinkDestination.about()
      : this._(AndroidDeepLinkTarget.about);

  const AndroidDeepLinkDestination.notifications()
      : this._(AndroidDeepLinkTarget.notifications);

  const AndroidDeepLinkDestination.ocr() : this._(AndroidDeepLinkTarget.ocr);

  const AndroidDeepLinkDestination.bridge()
      : this._(AndroidDeepLinkTarget.bridge);

  const AndroidDeepLinkDestination.erp() : this._(AndroidDeepLinkTarget.erp);

  const AndroidDeepLinkDestination.erpTab(int tabIndex)
      : this._(AndroidDeepLinkTarget.erpTab, tabIndex: tabIndex);

  const AndroidDeepLinkDestination.im() : this._(AndroidDeepLinkTarget.im);

  const AndroidDeepLinkDestination.connect()
      : this._(AndroidDeepLinkTarget.connect);

  const AndroidDeepLinkDestination.connectPc()
      : this._(AndroidDeepLinkTarget.connectPc);

  const AndroidDeepLinkDestination.onboarding()
      : this._(AndroidDeepLinkTarget.onboarding);

  const AndroidDeepLinkDestination.register()
      : this._(AndroidDeepLinkTarget.register);

  const AndroidDeepLinkDestination.smartAnalysis()
      : this._(AndroidDeepLinkTarget.smartAnalysis);

  const AndroidDeepLinkDestination.aiOpen()
      : this._(AndroidDeepLinkTarget.aiOpen);

  const AndroidDeepLinkDestination.brain()
      : this._(AndroidDeepLinkTarget.brain);

  const AndroidDeepLinkDestination.modStore()
      : this._(AndroidDeepLinkTarget.modStore);

  const AndroidDeepLinkDestination.longtail()
      : this._(AndroidDeepLinkTarget.longtail);

  final AndroidDeepLinkTarget target;
  final int? approvalId;
  final String? modId;
  final String? employeeId;
  final String? conversationId;
  final String? partnerKind;
  final int? tabIndex;
  final String? path;
  final String? title;
}

class AndroidDeepLinkBridge {
  const AndroidDeepLinkBridge({
    MethodChannel channel = const MethodChannel('xcagi/deep_link'),
  }) : _channel = channel;

  final MethodChannel _channel;

  Future<String?> initialRoute() async {
    try {
      final route = await _channel.invokeMethod<String>('getInitialRoute');
      return _blankToNull(route);
    } on MissingPluginException {
      return null;
    }
  }

  Stream<String> get routes {
    final controller = StreamController<String>.broadcast();
    _channel.setMethodCallHandler((call) async {
      if (call.method != 'onRoute') return null;
      final route = _blankToNull(call.arguments?.toString());
      if (route != null && !controller.isClosed) controller.add(route);
      return null;
    });
    controller.onCancel = () {
      _channel.setMethodCallHandler(null);
    };
    return controller.stream;
  }
}

@visibleForTesting
String? resolveAndroidDeepLinkRoute({
  String? extraRoute,
  Uri? uri,
}) {
  final route = _blankToNull(extraRoute);
  if (route != null) return route;
  if (uri == null) return null;

  if (uri.scheme.toLowerCase() == 'xcagi') {
    final host = uri.host;
    final path = uri.path;
    return _blankToNull(path.isNotEmpty ? '$host$path' : host);
  }
  if ((uri.host).toLowerCase().contains('xiu-ci.com')) {
    return _blankToNull(uri.path) ?? 'chat';
  }
  return null;
}

AndroidDeepLinkDestination resolveAndroidDeepLinkDestination(String route) {
  final normalized = _normalizeAndroidRoute(route);
  final uri = Uri.tryParse(normalized);
  final routePath =
      (uri?.path.isNotEmpty ?? false) ? uri!.path : normalized.split('?').first;
  final segments = routePath
      .split('/')
      .map((part) => part.trim())
      .where((part) => part.isNotEmpty)
      .toList(growable: false);
  final first = segments.isEmpty ? '' : segments.first;

  if (routePath.startsWith('payment/complete')) {
    return const AndroidDeepLinkDestination.market();
  }
  if (first == 'web_view') {
    final query = uri?.queryParameters ?? const <String, String>{};
    return AndroidDeepLinkDestination.desktopWebView(
      path:
          query['url']?.trim().isNotEmpty == true ? query['url']!.trim() : '/',
      title: query['title']?.trim().isNotEmpty == true
          ? query['title']!.trim()
          : '桌面工具',
    );
  }
  if (first == 'work') {
    return const AndroidDeepLinkDestination.work();
  }
  if (first == 'discover') {
    return const AndroidDeepLinkDestination.discover();
  }
  if (first == 'profile') {
    return const AndroidDeepLinkDestination.profile();
  }
  if (first == 'ai_employees') {
    return const AndroidDeepLinkDestination.aiEmployees();
  }
  if (first == 'ai_circle') {
    return const AndroidDeepLinkDestination.aiCircle();
  }
  if (first == 'ai_groups' || first == 'ai_group_chat') {
    return const AndroidDeepLinkDestination.aiGroups();
  }
  if (first == 'ai_group_create') {
    return const AndroidDeepLinkDestination.aiGroupCreate();
  }
  if (first == 'ai_employee') {
    if (segments.length >= 3 &&
        segments[1].trim().isNotEmpty &&
        segments[2].trim().isNotEmpty) {
      return AndroidDeepLinkDestination.aiEmployeeProfile(
        modId: segments[1].trim(),
        employeeId: segments[2].trim(),
      );
    }
    return const AndroidDeepLinkDestination.aiEmployees();
  }
  if (first == 'ai_chat') {
    return const AndroidDeepLinkDestination.aiChat();
  }
  if (first == 'conversation_chat') {
    final conversationId = segments.length >= 2 ? segments[1] : '';
    return conversationId.isEmpty
        ? const AndroidDeepLinkDestination.chat()
        : AndroidDeepLinkDestination.conversationChat(conversationId);
  }
  if (first == 'cs_chat') {
    return const AndroidDeepLinkDestination.csChat();
  }
  if (first == 'fixed_partner') {
    final partnerKind = segments.length >= 2 ? segments[1] : '';
    return partnerKind.isEmpty
        ? const AndroidDeepLinkDestination.aiChat()
        : AndroidDeepLinkDestination.fixedPartnerProfile(partnerKind);
  }
  if (first == 'scan_qr') {
    return const AndroidDeepLinkDestination.scanQr();
  }
  if (first == 'approval') {
    final match = RegExp(r'approval/(\d+)').firstMatch(routePath);
    final id = int.tryParse(match?.group(1) ?? '');
    if (id != null) return AndroidDeepLinkDestination.approvalDetail(id);
    return const AndroidDeepLinkDestination.approvalList();
  }
  if (first == 'erp' || first == 'erp_overview') {
    return const AndroidDeepLinkDestination.erp();
  }
  if (first == 'erp_tab') {
    final tabIndex = int.tryParse(segments.length >= 2 ? segments[1] : '') ?? 0;
    return AndroidDeepLinkDestination.erpTab(tabIndex);
  }
  if (first == 'ocr') {
    return const AndroidDeepLinkDestination.ocr();
  }
  if (first == 'bridge') {
    return const AndroidDeepLinkDestination.bridge();
  }
  if (first == 'market') {
    return const AndroidDeepLinkDestination.market();
  }
  if (first == 'mods') {
    return const AndroidDeepLinkDestination.mods();
  }
  if (first == 'mod') {
    final modId = segments.length >= 2 ? segments[1] : '';
    return modId.isEmpty
        ? const AndroidDeepLinkDestination.mods()
        : AndroidDeepLinkDestination.modWeb(modId);
  }
  if (first == 'longtail') {
    return const AndroidDeepLinkDestination.longtail();
  }
  if (first == 'settings') {
    return const AndroidDeepLinkDestination.settings();
  }
  if (first == 'about') {
    return const AndroidDeepLinkDestination.about();
  }
  if (first == 'notifications') {
    return const AndroidDeepLinkDestination.notifications();
  }
  if (first == 'im') {
    return const AndroidDeepLinkDestination.im();
  }
  if (first == 'connect') {
    return const AndroidDeepLinkDestination.connect();
  }
  if (first == 'connect_pc') {
    return const AndroidDeepLinkDestination.connectPc();
  }
  if (first == 'onboarding') {
    return const AndroidDeepLinkDestination.onboarding();
  }
  if (first == 'register') {
    return const AndroidDeepLinkDestination.register();
  }
  if (first == 'smart_analysis') {
    return const AndroidDeepLinkDestination.smartAnalysis();
  }
  if (first == 'ai_open') {
    return const AndroidDeepLinkDestination.aiOpen();
  }
  if (first == 'brain') {
    return const AndroidDeepLinkDestination.brain();
  }
  if (first == 'mod_store') {
    return const AndroidDeepLinkDestination.modStore();
  }
  if (first == 'chat' ||
      first == 'home' ||
      first == 'home_hub' ||
      routePath.contains('chat')) {
    return const AndroidDeepLinkDestination.chat();
  }
  return const AndroidDeepLinkDestination.chat();
}

String _normalizeAndroidRoute(String route) {
  var normalized = route.trim().replaceFirst(RegExp(r'^/+'), '');
  if (normalized.startsWith('app/')) {
    normalized = normalized.substring('app/'.length);
  }
  return normalized;
}

String? _blankToNull(String? value) {
  final normalized = value?.trim() ?? '';
  return normalized.isEmpty ? null : normalized;
}
