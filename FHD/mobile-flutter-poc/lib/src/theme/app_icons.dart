import 'package:material_symbols_icons/symbols.dart';

/// 语义化图标表：统一使用 Material Symbols（Apache-2.0）Rounded 变体。
///
/// 业务代码只引用这里的名字，替换图标风格时不需要全仓搜索 `Icons.*`。
class AppIcons {
  const AppIcons._();

  // 主导航
  static const chat = Symbols.forum_rounded;
  static const chatOutline = Symbols.forum;
  static const employees = Symbols.badge_rounded;
  static const employeesOutline = Symbols.badge;
  static const discover = Symbols.explore_rounded;
  static const discoverOutline = Symbols.explore;
  static const profile = Symbols.person_rounded;
  static const profileOutline = Symbols.person;

  // 通用操作
  static const back = Symbols.arrow_back_rounded;
  static const more = Symbols.more_horiz_rounded;
  static const video = Symbols.videocam_rounded;
  static const mic = Symbols.mic_rounded;
  static const add = Symbols.add_rounded;
  static const send = Symbols.send_rounded;
  static const visible = Symbols.visibility_rounded;
  static const hidden = Symbols.visibility_off_rounded;
}
