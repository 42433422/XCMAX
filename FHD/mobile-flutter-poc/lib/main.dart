import 'dart:async';

import 'package:flutter/material.dart';

import 'src/app/mobile_startup_shell.dart';
import 'src/data/mobile_repository.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // Bound decoded images retained by the framework's existing LRU.
  PaintingBinding.instance.imageCache
    ..maximumSize = 256
    ..maximumSizeBytes = 48 * 1024 * 1024;
  runApp(const XcagiFlutterPocApp());
}

class XcagiFlutterPocApp extends StatefulWidget {
  const XcagiFlutterPocApp({super.key});

  @override
  State<XcagiFlutterPocApp> createState() => _XcagiFlutterPocAppState();
}

class _XcagiFlutterPocAppState extends State<XcagiFlutterPocApp> {
  late final MobileRepository _repository = MobileRepository();

  @override
  void dispose() {
    unawaited(_repository.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MobileStartupApp(repository: _repository);
  }
}
