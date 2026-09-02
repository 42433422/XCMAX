import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/mobile_runtime_policy.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';
import '../scan/scan_qr_screen.dart';
import 'register_screen.dart';

part 'auth_screen_state.part.dart';
part 'auth_screen_login_widgets.part.dart';
part 'auth_screen_agreement_widgets.part.dart';

enum AuthLoginMode { password, phone }

class AuthScreen extends StatefulWidget {
  const AuthScreen({
    super.key,
    this.repository,
    this.onDone,
    this.openExternalUrl,
  });

  final MobileRepository? repository;
  final VoidCallback? onDone;
  final ExternalUrlLauncher? openExternalUrl;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}
