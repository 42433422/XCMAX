import 'package:flutter/material.dart';

import 'src/app/android_startup_shell.dart';
import 'src/data/mobile_repository.dart';

void main() {
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
  Widget build(BuildContext context) {
    return AndroidStartupApp(repository: _repository);
  }
}
