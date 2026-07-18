import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum MobileDeepLinkTarget {
  chat,
  work,
  discover,
  profile,
  aiChat,
  conversationChat,
  csChat,
  adminCsConsole,
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
  employeeQuestions,
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

class MobileDeepLinkDestination {
  const MobileDeepLinkDestination._(
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

  const MobileDeepLinkDestination.chat() : this._(MobileDeepLinkTarget.chat);

  const MobileDeepLinkDestination.work() : this._(MobileDeepLinkTarget.work);

  const MobileDeepLinkDestination.discover()
      : this._(MobileDeepLinkTarget.discover);

  const MobileDeepLinkDestination.profile()
      : this._(MobileDeepLinkTarget.profile);

  const MobileDeepLinkDestination.aiChat()
      : this._(MobileDeepLinkTarget.aiChat);

  const MobileDeepLinkDestination.conversationChat(String conversationId)
      : this._(
          MobileDeepLinkTarget.conversationChat,
          conversationId: conversationId,
        );

  const MobileDeepLinkDestination.csChat()
      : this._(MobileDeepLinkTarget.csChat);

  const MobileDeepLinkDestination.adminCsConsole()
      : this._(MobileDeepLinkTarget.adminCsConsole);

  const MobileDeepLinkDestination.fixedPartnerProfile(String partnerKind)
      : this._(
          MobileDeepLinkTarget.fixedPartnerProfile,
          partnerKind: partnerKind,
        );

  const MobileDeepLinkDestination.market()
      : this._(MobileDeepLinkTarget.market);

  const MobileDeepLinkDestination.mods() : this._(MobileDeepLinkTarget.mods);

  const MobileDeepLinkDestination.modWeb(String modId)
      : this._(MobileDeepLinkTarget.modWeb, modId: modId);

  const MobileDeepLinkDestination.desktopWebView({
    required String path,
    required String title,
  }) : this._(MobileDeepLinkTarget.desktopWebView, path: path, title: title);

  const MobileDeepLinkDestination.aiEmployees()
      : this._(MobileDeepLinkTarget.aiEmployees);

  const MobileDeepLinkDestination.aiCircle()
      : this._(MobileDeepLinkTarget.aiCircle);

  const MobileDeepLinkDestination.aiGroups()
      : this._(MobileDeepLinkTarget.aiGroups);

  const MobileDeepLinkDestination.aiGroupCreate()
      : this._(MobileDeepLinkTarget.aiGroupCreate);

  const MobileDeepLinkDestination.scanQr()
      : this._(MobileDeepLinkTarget.scanQr);

  const MobileDeepLinkDestination.approvalList()
      : this._(MobileDeepLinkTarget.approvalList);

  const MobileDeepLinkDestination.approvalDetail(int id)
      : this._(MobileDeepLinkTarget.approvalDetail, approvalId: id);

  const MobileDeepLinkDestination.aiEmployeeProfile({
    required String modId,
    required String employeeId,
  }) : this._(
          MobileDeepLinkTarget.aiEmployeeProfile,
          modId: modId,
          employeeId: employeeId,
        );

  const MobileDeepLinkDestination.employeeQuestions(String? employeeId)
      : this._(MobileDeepLinkTarget.employeeQuestions, employeeId: employeeId);

  const MobileDeepLinkDestination.settings()
      : this._(MobileDeepLinkTarget.settings);

  const MobileDeepLinkDestination.about() : this._(MobileDeepLinkTarget.about);

  const MobileDeepLinkDestination.notifications()
      : this._(MobileDeepLinkTarget.notifications);

  const MobileDeepLinkDestination.ocr() : this._(MobileDeepLinkTarget.ocr);

  const MobileDeepLinkDestination.bridge()
      : this._(MobileDeepLinkTarget.bridge);

  const MobileDeepLinkDestination.erp() : this._(MobileDeepLinkTarget.erp);

  const MobileDeepLinkDestination.erpTab(int tabIndex)
      : this._(MobileDeepLinkTarget.erpTab, tabIndex: tabIndex);

  const MobileDeepLinkDestination.im() : this._(MobileDeepLinkTarget.im);

  const MobileDeepLinkDestination.connect()
      : this._(MobileDeepLinkTarget.connect);

  const MobileDeepLinkDestination.connectPc()
      : this._(MobileDeepLinkTarget.connectPc);

  const MobileDeepLinkDestination.onboarding()
      : this._(MobileDeepLinkTarget.onboarding);

  const MobileDeepLinkDestination.register()
      : this._(MobileDeepLinkTarget.register);

  const MobileDeepLinkDestination.smartAnalysis()
      : this._(MobileDeepLinkTarget.smartAnalysis);

  const MobileDeepLinkDestination.aiOpen()
      : this._(MobileDeepLinkTarget.aiOpen);

  const MobileDeepLinkDestination.brain() : this._(MobileDeepLinkTarget.brain);

  const MobileDeepLinkDestination.modStore()
      : this._(MobileDeepLinkTarget.modStore);

  const MobileDeepLinkDestination.longtail()
      : this._(MobileDeepLinkTarget.longtail);

  final MobileDeepLinkTarget target;
  final int? approvalId;
  final String? modId;
  final String? employeeId;
  final String? conversationId;
  final String? partnerKind;
  final int? tabIndex;
  final String? path;
  final String? title;
}

class MobileDeepLinkBridge {
  const MobileDeepLinkBridge({
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
String? resolveMobileDeepLinkRoute({String? extraRoute, Uri? uri}) {
  final route = _blankToNull(extraRoute);
  if (route != null) return route;
  if (uri == null) return null;

  if (uri.scheme.toLowerCase() == 'xcagi') {
    final host = uri.host;
    final path = uri.path;
    final base = path.isNotEmpty ? '$host$path' : host;
    final query = uri.query.trim();
    if (base.isEmpty) return null;
    return query.isEmpty ? base : '$base?$query';
  }
  if ((uri.host).toLowerCase().contains('xiu-ci.com')) {
    return _blankToNull(uri.path) ?? 'chat';
  }
  return null;
}

String? pairingPayloadFromDeepLinkRoute(String route) {
  final trimmed = route.trim();
  if (trimmed.isEmpty) return null;
  if (RegExp(r'^\d{6}$').hasMatch(trimmed)) return trimmed;
  final head = trimmed.split('?').first.replaceFirst(RegExp(r'^/+'), '');
  if (head != 'pairing') return null;
  final queryStart = trimmed.indexOf('?');
  if (queryStart < 0) return null;
  final params = Uri.splitQueryString(trimmed.substring(queryStart + 1));
  final code =
      (params['code'] ?? params['shortCode'] ?? params['t'] ?? '').trim();
  if (RegExp(r'^\d{6}$').hasMatch(code)) return code;
  final host = (params['host'] ?? '').trim();
  final port = int.tryParse(params['port'] ?? '') ?? 0;
  if (code.isNotEmpty && host.isNotEmpty && port > 0) {
    return 'xcagi://pairing?${Uri(queryParameters: params).query}';
  }
  return null;
}

MobileDeepLinkDestination resolveMobileDeepLinkDestination(String route) {
  final normalized = _normalizeMobileRoute(route);
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
    return const MobileDeepLinkDestination.market();
  }
  if (first == 'web_view') {
    final query = uri?.queryParameters ?? const <String, String>{};
    return MobileDeepLinkDestination.desktopWebView(
      path:
          query['url']?.trim().isNotEmpty == true ? query['url']!.trim() : '/',
      title: query['title']?.trim().isNotEmpty == true
          ? query['title']!.trim()
          : '桌面工具',
    );
  }
  if (first == 'work') {
    return const MobileDeepLinkDestination.work();
  }
  if (first == 'discover') {
    return const MobileDeepLinkDestination.discover();
  }
  if (first == 'profile') {
    return const MobileDeepLinkDestination.profile();
  }
  if (first == 'ai_employees') {
    return const MobileDeepLinkDestination.aiEmployees();
  }
  if (first == 'ai_circle') {
    return const MobileDeepLinkDestination.aiCircle();
  }
  if (first == 'ai_groups' || first == 'ai_group_chat') {
    return const MobileDeepLinkDestination.aiGroups();
  }
  if (first == 'ai_group_create') {
    return const MobileDeepLinkDestination.aiGroupCreate();
  }
  if (first == 'ai_employee') {
    if (segments.length >= 3 &&
        segments[1].trim().isNotEmpty &&
        segments[2].trim().isNotEmpty) {
      return MobileDeepLinkDestination.aiEmployeeProfile(
        modId: segments[1].trim(),
        employeeId: segments[2].trim(),
      );
    }
    return const MobileDeepLinkDestination.aiEmployees();
  }
  if (first == 'employee_questions') {
    final employeeId = segments.length >= 2 ? segments[1].trim() : '';
    return MobileDeepLinkDestination.employeeQuestions(
      employeeId.isEmpty ? null : employeeId,
    );
  }
  if (first == 'employee_questions_all') {
    return const MobileDeepLinkDestination.employeeQuestions(null);
  }
  if (first == 'ai_chat') {
    return const MobileDeepLinkDestination.aiChat();
  }
  if (first == 'conversation_chat') {
    final conversationId = segments.length >= 2 ? segments[1] : '';
    return conversationId.isEmpty
        ? const MobileDeepLinkDestination.chat()
        : MobileDeepLinkDestination.conversationChat(conversationId);
  }
  if (first == 'cs_chat') {
    return const MobileDeepLinkDestination.csChat();
  }
  if (first == 'admin_cs_console') {
    return const MobileDeepLinkDestination.adminCsConsole();
  }
  if (first == 'fixed_partner') {
    final partnerKind = segments.length >= 2 ? segments[1] : '';
    return partnerKind.isEmpty
        ? const MobileDeepLinkDestination.aiChat()
        : MobileDeepLinkDestination.fixedPartnerProfile(partnerKind);
  }
  if (first == 'scan_qr') {
    return const MobileDeepLinkDestination.scanQr();
  }
  if (first == 'approval') {
    final match = RegExp(r'approval/(\d+)').firstMatch(routePath);
    final id = int.tryParse(match?.group(1) ?? '');
    if (id != null) return MobileDeepLinkDestination.approvalDetail(id);
    return const MobileDeepLinkDestination.approvalList();
  }
  if (first == 'erp' || first == 'erp_overview') {
    return const MobileDeepLinkDestination.erp();
  }
  if (first == 'erp_tab') {
    final tabIndex = int.tryParse(segments.length >= 2 ? segments[1] : '') ?? 0;
    return MobileDeepLinkDestination.erpTab(tabIndex);
  }
  if (first == 'ocr') {
    return const MobileDeepLinkDestination.ocr();
  }
  if (first == 'bridge') {
    return const MobileDeepLinkDestination.bridge();
  }
  if (first == 'market') {
    return const MobileDeepLinkDestination.market();
  }
  if (first == 'mods') {
    return const MobileDeepLinkDestination.mods();
  }
  if (first == 'mod') {
    final modId = segments.length >= 2 ? segments[1] : '';
    return modId.isEmpty
        ? const MobileDeepLinkDestination.mods()
        : MobileDeepLinkDestination.modWeb(modId);
  }
  if (first == 'longtail') {
    return const MobileDeepLinkDestination.longtail();
  }
  if (first == 'settings') {
    return const MobileDeepLinkDestination.settings();
  }
  if (first == 'about') {
    return const MobileDeepLinkDestination.about();
  }
  if (first == 'notifications') {
    return const MobileDeepLinkDestination.notifications();
  }
  if (first == 'im') {
    return const MobileDeepLinkDestination.im();
  }
  if (first == 'connect') {
    return const MobileDeepLinkDestination.connect();
  }
  if (first == 'connect_pc') {
    return const MobileDeepLinkDestination.connectPc();
  }
  if (first == 'onboarding') {
    return const MobileDeepLinkDestination.onboarding();
  }
  if (first == 'register') {
    return const MobileDeepLinkDestination.register();
  }
  if (first == 'smart_analysis') {
    return const MobileDeepLinkDestination.smartAnalysis();
  }
  if (first == 'ai_open') {
    return const MobileDeepLinkDestination.aiOpen();
  }
  if (first == 'brain') {
    return const MobileDeepLinkDestination.brain();
  }
  if (first == 'mod_store') {
    return const MobileDeepLinkDestination.modStore();
  }
  if (first == 'chat' ||
      first == 'home' ||
      first == 'home_hub' ||
      routePath.contains('chat')) {
    return const MobileDeepLinkDestination.chat();
  }
  return const MobileDeepLinkDestination.chat();
}

String _normalizeMobileRoute(String route) {
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
