import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';

const mobileTermsUrl = 'https://xiu-ci.com/legal/terms';
const mobilePrivacyUrl = 'https://xiu-ci.com/legal/privacy';

typedef MobileLegalReader = Future<bool> Function(
  BuildContext context,
  String title,
  Uri url,
);

class LegalConsentScreen extends StatefulWidget {
  const LegalConsentScreen({
    super.key,
    required this.onAccepted,
    this.openDocument = openMobileLegalDocument,
  });

  final Future<void> Function() onAccepted;
  final MobileLegalReader openDocument;

  @override
  State<LegalConsentScreen> createState() => _LegalConsentScreenState();
}

class _LegalConsentScreenState extends State<LegalConsentScreen> {
  final _opened = <String>{};
  bool _busy = false, _declined = false;

  Future<void> _read(String title, String url) async {
    setState(() => _busy = true);
    final opened = await widget.openDocument(context, title, Uri.parse(url))
        .catchError((_) => false);
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (opened) _opened.add(url);
    });
  }

  Future<void> _accept() async {
    setState(() => _busy = true);
    try {
      await widget.onAccepted();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未能保存同意记录，请重试。')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final foreground = colors.chatUserBubbleText;
    return Scaffold(
      backgroundColor: colors.brand,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Image.asset(appLauncherIconAsset, width: 64, height: 64),
                Text('XCAGI', style: TextStyle(color: foreground, fontSize: 34)),
                Text('AI 工作平台', style: TextStyle(color: foreground)),
                const SizedBox(height: 24),
                Text(
                  _declined
                      ? '你已拒绝。应用不会启动登录及后台服务。'
                      : '请先阅读用户协议和隐私政策，再选择是否同意。',
                  style: TextStyle(color: foreground),
                  textAlign: TextAlign.center,
                ),
                if (_declined)
                  FilledButton(
                    onPressed: () => setState(() => _declined = false),
                    child: const Text('返回查看协议'),
                  )
                else ...[
                  for (final (title, url) in [
                    ('《用户协议》', mobileTermsUrl),
                    ('《隐私政策》', mobilePrivacyUrl),
                  ])
                    TextButton(
                      style: TextButton.styleFrom(foregroundColor: foreground),
                      onPressed: _busy ? null : () => _read(title, url),
                      child: Text(title),
                    ),
                  if (_opened.length != 2)
                    Text('两份文件均可阅读后才能同意。',
                        style: TextStyle(color: foreground)),
                  FilledButton(
                    onPressed: _busy || _opened.length != 2 ? null : _accept,
                    child: const Text('同意并继续'),
                  ),
                  TextButton(
                    style: TextButton.styleFrom(foregroundColor: foreground),
                    onPressed: _busy
                        ? null
                        : () => setState(() {
                              _opened.clear();
                              _declined = true;
                            }),
                    child: const Text('不同意'),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// User-initiated and isolated from the app's authenticated API session.
Future<bool> openMobileLegalDocument(
  BuildContext context,
  String title,
  Uri url,
) async =>
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _LegalDocument(title, url)),
    ) ??
    false;

class _LegalDocument extends StatefulWidget {
  const _LegalDocument(this.title, this.url);
  final String title;
  final Uri url;

  @override
  State<_LegalDocument> createState() => _LegalDocumentState();
}

class _LegalDocumentState extends State<_LegalDocument> {
  WebViewController? _controller;
  bool _readable = false, _failed = false;
  Timer? _deadline;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  bool _allowed(Uri? parsed) => parsed != null &&
        parsed.scheme == 'https' &&
        (parsed.host == widget.url.host || parsed.host == 'www.xiu-ci.com') &&
        parsed.port == 443 &&
        parsed.userInfo.isEmpty &&
        parsed.path == widget.url.path &&
        !parsed.hasQuery;

  Future<void> _load() async {
    _deadline = Timer(const Duration(seconds: 15), _fail);
    try {
      final controller = WebViewController();
      await controller.setJavaScriptMode(JavaScriptMode.disabled);
      await controller.setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (request) => _allowed(Uri.tryParse(request.url))
            ? NavigationDecision.navigate
            : NavigationDecision.prevent,
        onHttpError: (error) {
          final uri = error.request?.uri;
          if (uri == null || _allowed(uri)) _fail();
        },
        onWebResourceError: (error) {
          if (error.isForMainFrame != false) _fail();
        },
        onPageFinished: (url) {
          if (!mounted || _failed || !_allowed(Uri.tryParse(url))) return;
          _deadline?.cancel();
          setState(() => _readable = true);
        },
      ));
      if (!mounted || _failed) return;
      setState(() => _controller = controller);
      await controller.loadRequest(widget.url);
    } catch (_) {
      _fail();
    }
  }

  void _fail() {
    if (!mounted) return;
    _deadline?.cancel();
    setState(() => _failed = true);
  }

  @override
  void dispose() {
    _deadline?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: _failed
            ? const Center(child: Text('暂时无法打开文件。请返回后重试。'))
            : _controller == null
                ? const Center(child: CircularProgressIndicator())
                : WebViewWidget(controller: _controller!),
        bottomNavigationBar: SafeArea(
          child: TextButton(
            onPressed: _readable && !_failed
                ? () => Navigator.of(context).pop(true)
                : null,
            child: const Text('返回选择'),
          ),
        ),
      );
}
