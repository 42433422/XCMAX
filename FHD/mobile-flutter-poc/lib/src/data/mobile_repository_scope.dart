import 'package:flutter/widgets.dart';

import 'mobile_repository.dart';

class MobileRepositoryScope extends InheritedWidget {
  const MobileRepositoryScope({
    super.key,
    required this.repository,
    required super.child,
  });

  final MobileRepository repository;

  static MobileRepository? maybeRead(BuildContext context) {
    final inherited = context
        .getElementForInheritedWidgetOfExactType<MobileRepositoryScope>()
        ?.widget;
    return inherited is MobileRepositoryScope ? inherited.repository : null;
  }

  static MobileRepository? maybeOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<MobileRepositoryScope>()
        ?.repository;
  }

  static MobileRepository resolve(
    BuildContext context, {
    MobileRepository? explicit,
  }) {
    return explicit ?? maybeRead(context) ?? MobileRepository();
  }

  @override
  bool updateShouldNotify(MobileRepositoryScope oldWidget) {
    return oldWidget.repository != repository;
  }
}
