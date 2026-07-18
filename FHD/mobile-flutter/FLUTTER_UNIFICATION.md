# Flutter mobile unification

> **2026-07-18**：`mobile-flutter` 是唯一移动端实现与交付主线。Android 和 iOS
> 共用 `lib/` 业务代码；`android/` 与 `ios/` 只承担 Flutter Runner、签名、平台通道和商店发布。

移动端的长期真相源是 Flutter + OpenAPI + FastAPI +
[`mobile_tri_platform_ssot.md`](../docs/mobile_tri_platform_ssot.md)。禁止恢复独立 Kotlin、SwiftUI
或 HarmonyOS 产品实现；历史实现只可从 Git 历史取证。

## Source anchors

| Domain | Flutter source |
|---|---|
| Fixed conversation IDs | `lib/src/policy/pinned_ids.dart` |
| Conversation types and routing | `lib/src/models/conversation.dart`, `lib/src/policy/avatar_policy.dart` |
| Avatar fallback and crop behavior | `lib/src/widgets/app_avatar.dart`, `lib/src/policy/avatar_policy.dart` |
| Avatar sizes and row spacing | `lib/src/theme/message_avatar_layout.dart` |
| Message list | `lib/src/features/messages/message_list_screen.dart` |
| Chat page | `lib/src/features/chat/chat_screen.dart` |
| AI group list/chat | `lib/src/features/groups/groups_screen.dart` |
| Employee catalog/profile | `lib/src/features/contacts/contacts_screen.dart` |
| API models/endpoints | `lib/src/api/*`, `lib/src/data/mobile_repository.dart` |

## Stage 1: policy parity

- Fixed contacts must keep bundled assets. Do not allow remote URLs or initials to
  override Xiao C, customer service, Codex, Cursor, Claude, or Trae.
- Normal AI employees resolve by employee ID through `employeeAvatarFallback`.
- `employee:<modId>:<employeeId>` must normalize to the last segment.
- Avatar rendering uses `BoxFit.cover`, clipped to the same stable size/radius constants
  as Android.

## Stage 2: live data parity

- Prefer `MobileRepository` over `demo_data.dart`; demo data is only a network/auth
  fallback.
- Use `/api/mobile/v1/admin/home` for admin employee conversations.
- Keep fixed conversation visibility stable: Xiao C always, super
  employees for enterprise/admin, customer service only for non-admin enterprise.
- Generate Dart DTOs from `FHD/contracts/openapi.json` or a narrowed mobile contract.
- Keep mobile endpoints under `/api/mobile/v1` and preserve the published route contract.

## Stage 3: screen parity

Port in this order:

1. Legal consent, auth, pairing, and session persistence.
2. Message list and 1:1 chat with SSE fallback.
3. Employee catalog/profile and AI group flows.
4. AI circle, customer service, approvals, wallet, settings.
5. Device-specific modules: QR, OCR, push, biometric, WebView token injection.

## Non-goals

- Do not make Flutter a new visual redesign.
- Do not add generated initials or random colors for identity fallback.
- Do not call a screen complete until it has a Flutter test or screenshot proving the
  relevant behavior on each shipping platform.
