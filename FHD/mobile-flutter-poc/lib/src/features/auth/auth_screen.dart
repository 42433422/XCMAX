import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_assets.dart';
import '../../theme/app_theme.dart';
import '../legal/legal_consent_screen.dart'
    show mobilePrivacyUrl, mobileTermsUrl;
import '../scan/scan_qr_screen.dart';
import '../workspace/local_workspace_screen.dart';
import '../../policy/mobile_error_policy.dart';

part 'auth_screen_state.part.dart';
part 'auth_screen_login_widgets.part.dart';
part 'auth_screen_agreement_widgets.part.dart';

Future<bool> openMarketRegistration(ExternalUrlLauncher launcher) async {
  final uri = Uri.parse('${XcagiMobileTopology.marketBaseUrl}/register')
      .replace(queryParameters: {'source': 'xcagi-mobile'});
  try {
    return await launcher(uri);
  } catch (_) {
    return false;
  }
}

class AuthScreen extends StatefulWidget {
  const AuthScreen({
    super.key,
    this.repository,
    this.onDone,
    this.openExternalUrl,
    this.legalConsentAlreadyRecorded = false,
  });

  final MobileRepository? repository;
  final VoidCallback? onDone;
  final ExternalUrlLauncher? openExternalUrl;
  final bool legalConsentAlreadyRecorded;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}
