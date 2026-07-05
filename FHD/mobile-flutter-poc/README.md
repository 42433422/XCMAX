# XCAGI Flutter POC

Android-first Flutter proof of concept for the XCAGI mobile core flows.

The operating rule is documented in [`ANDROID_FIRST_UNIFICATION.md`](ANDROID_FIRST_UNIFICATION.md):
Android `mobile-android` is the source of truth for behavior, route naming,
avatar identity, layout constants, and API contracts. Flutter should converge the
mobile product line; it should not become a separate redesign.

The POC deliberately copies Android mobile SSOT concepts instead of inventing new iOS/Flutter-only rules:

- `PinnedIds`
- `ConversationType`
- `AppAvatarFallback`
- `MessageAvatarLayout`
- `chatAvatarFallback`
- `aiGroupAvatarFallback`
- super employee tool routing for Codex / Cursor / Claude / Trae

## Covered Flow

- Message list with Android-aligned fixed conversation avatars.
- Chat page with Android-aligned bubble avatar sizing and fallback policy.
- Contacts and group list using the same AI group member avatar resolver.
- Profile fallback avatar using the same `AppAvatar` crop/clip component.
- Unit tests for fixed IDs, fallback mapping, group member mapping and super employee paths.
- Android-synced employee avatar assets and `employeeAvatarFallback` mapping for
  normal AI employees.
- Android-aligned mobile API client and repository layer for admin home, normal chat,
  and Codex / Cursor / Claude / Trae super employee messages.

The avatar rule is intentionally strict: fixed contacts always use bundled fixed assets; employee URLs are only used for non-fixed AI employees; every avatar is clipped and rendered with `BoxFit.cover`.

## Local Tooling

This machine currently has no `flutter` or `dart` command in `PATH`. After installing Flutter:

```bash
cd FHD/mobile-flutter-poc
flutter create --project-name xcagi_flutter_poc --platforms=android,ios .
flutter pub get
flutter test
flutter run
```

Keep this POC Android-first: when behavior differs, copy Android `mobile-android` logic before styling by taste.
