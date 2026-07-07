# Android-first Flutter unification

`mobile-android` is the behavior reference baseline (frozen). This Flutter POC exists to converge
Android, iOS, and Harmony toward one implementation surface, not to invent a fourth
mobile product line. **Status: converged — Flutter is now the unified mobile
implementation (the single mobile SSOT surface); native Android/iOS/Harmony are frozen
release fallbacks** (see `FHD/docs/mobile_tri_platform_ssot.md` §1.2).

## Source anchors

| Domain | Android source (reference) | Flutter target (main line) |
|---|---|---|
| Fixed conversation IDs | `model/ConversationItem.kt`, `model/PinnedIds.kt` | `lib/src/policy/pinned_ids.dart` |
| Conversation types and routing | `model/ConversationItem.kt`, `navigation/ChatScreen.kt` | `lib/src/models/conversation.dart`, `lib/src/policy/avatar_policy.dart` |
| Avatar fallback and crop behavior | `ui/components/mobile/AppAvatar.kt`, `EmployeeAvatarFallbacks.kt` | `lib/src/widgets/app_avatar.dart`, `lib/src/policy/avatar_policy.dart` |
| Avatar sizes and row spacing | `ui/components/mobile/MessageAvatarLayout.kt` | `lib/src/theme/message_avatar_layout.dart` |
| Message list | `navigation/ConversationListScreen.kt` | `lib/src/features/messages/message_list_screen.dart` |
| Chat page | `navigation/ChatScreen.kt` | `lib/src/features/chat/chat_screen.dart` |
| AI group list/chat | `navigation/AiGroupScreens.kt` | `lib/src/features/groups/ai_group_screens.dart` |
| Employee catalog/profile | `navigation/AiCircleScreens.kt`, `AiGroupMemberCatalog.kt` | `lib/src/features/contacts/contacts_screen.dart` |
| Employee pending questions (Phase-D) | `navigation/EmployeeQuestionsScreen.kt` | `lib/src/features/contacts/employee_questions_screen.dart` |
| API models/endpoints | `core/model/ApiModels.kt`, `core/network/FhdApi.kt`, `core/network/ApiEndpoints.kt` | `lib/src/api/*`, `lib/src/data/mobile_repository.dart` |
| Dual-SKU build matrix | `app/build.gradle.kts` productFlavors | `android/app/build.gradle.kts` productFlavors + `XCAGI_PRODUCT_SKU` dart-define |

## Stage 1: policy parity — DONE

- Fixed contacts must keep bundled assets. Do not allow remote URLs or initials to
  override Xiao C, customer service, Codex, Cursor, Claude, or Trae.
- Normal AI employees resolve by employee ID through `employeeAvatarFallback`.
- `employee:<modId>:<employeeId>` must normalize to the last segment, matching Android.
- Avatar rendering uses `BoxFit.cover`, clipped to the same stable size/radius constants
  as Android.

## Stage 2: live data parity — DONE

- Prefer `MobileRepository` over `demo_data.dart`; demo data is only a network/auth
  fallback.
- Mirror Android's `/api/mobile/v1/admin/home` flow for admin employee conversations.
- Keep fixed conversation visibility aligned with Android: Xiao C always, super
  employees for enterprise/admin, customer service only for non-admin enterprise.
- Generate Dart DTOs from `FHD/contracts/openapi.json` or a narrowed mobile contract.
- Keep mobile endpoints under `/api/mobile/v1` and preserve Android route names before
  adapting Flutter UI. IM endpoints live under `/api/mobile/v1/im/*` (same as Android
  `FhdApi.kt`), enforced by `test/mobile_api_parity_test.dart`.

## Stage 3: screen parity — DONE

Ported in this order:

1. Legal consent, auth, pairing, and session persistence.
2. Message list and 1:1 chat with SSE fallback.
3. Employee catalog/profile and AI group flows.
4. AI circle, customer service, approvals, wallet, settings, employee pending
   questions (Phase-D 员工任务中心).
5. Device-specific modules: QR, OCR, push, biometric, WebView token injection.

## Stage 4: unified replacement (current operating mode)

- Flutter builds both SKUs with the same applicationIds as native Android
  (`com.xiuci.xcagi.mobile.personal` / `.enterprise`), so the Flutter APK replaces the
  native APK in-place (session migration handled by `MainActivity` legacy DataStore
  import, keyed by `BuildConfig.PRODUCT_SKU`).
- iOS ships from the same Dart tree with bundle id
  `com.xiuci.xcagi.mobile.enterprise`; `X-XCAGI-Client` reports `ios` on iOS.
- New mobile features land in Flutter only. Native repos accept security/compliance
  fixes only (freeze policy in `mobile_tri_platform_ssot.md` §1.2).
- Android remains the behavior reference: parity tests read `../mobile-android`
  sources directly and must stay green.

## Non-goals

- Do not make Flutter a new visual redesign.
- Do not bypass Android behavior to match iOS or Harmony first.
- Do not add generated initials or random colors for identity fallback.
- Do not call a screen complete until it has an Android source anchor and a test or
  screenshot proving the relevant behavior.
