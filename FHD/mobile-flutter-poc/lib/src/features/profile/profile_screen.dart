import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../api/mobile_api.dart';
import '../../api/mobile_models.dart';
import '../../api/mobile_session_store.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../about/about_screen.dart';
import '../auth/auth_screen.dart';
import '../connect/connect_screen.dart';
import '../settings/settings_screen.dart';

// 按职责拆分为 part 文件：页面 State、编辑/注销弹窗、资料卡组件与钱包卡片。
part 'profile_screen_state.part.dart';
part 'profile_screen_editors.part.dart';
part 'profile_screen_hero.part.dart';
part 'profile_screen_wallet.part.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, this.api});

  final MobileApiClient? api;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}
