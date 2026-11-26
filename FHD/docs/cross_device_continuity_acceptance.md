# Desktop ↔ Flutter task continuity: acceptance contract

> Scope: integration PR #3605. Implementations must reuse the original FastAPI Agent Runtime,
> canonical task/run IDs, authorization grants, server-side state, and stored execution receipts.
> No second client task scheduler, no replay of ambiguous business POSTs.

## Source of truth and recovery order

1. Desktop creates a task through the original Agent Runtime. The server owns
   `task_id`, `conversation_id`, `active_run_id`, step approval and execution receipts.
2. Flutter reads the same task through
   `GET /api/mobile/v1/workspace/agent/tasks/{task_id}`, which mounts the
   existing desktop task route with its original principal and Mod checks.
3. Flutter approval reads the **current** server approval/run and the original
   grant before any POST. A lost response means **unknown**, not a new approval.
4. The desktop task center refreshes from the original task list/SSE snapshot.
   It must show the same server status/approval/receipt after mobile action.
5. A broken SSE POST is resumed through the original `turn_id` receipt GET and
   `/api/ai/chat/stream/resume` where supported. An unknown receipt must never
   be converted into another POST. Stream events are deduplicated by explicit SSE
   event ID and messages/IM frames by canonical message ID.
6. WebSocket reconnect uses bounded backoff, authenticates against the current
   session and reconciles missed messages from server history.
7. Draft text is account/backend/conversation scoped, bounded and expires after
   seven days. Attachment names may be restored as **reselect required**, but
   previous upload bytes, upload IDs, tokens and authorization grants are never
   reactivated implicitly. A changed account clears old visible data.

## Automated tests added to PR

| Scenario | Test |
| --- | --- |
| Delayed task GET crossing suspension/resume | `test/task_list_screen_test.dart` |
| Unknown POST response, GET-only resume, outbox never downgraded | `test/offline_store_test.dart` |
| Scoped chat drafts and no retained upload credentials | `test/offline_store_test.dart` |
| Mobile approval: stale decision, lost receipt and disabled repeat | `test/approval_continuity_test.dart` |
| Same-session WebSocket attach does not restart connection | `test/im_realtime_test.dart` |
| Original desktop task ID and conversation survive mobile read/result | `tests/test_routes/test_mobile_native_task_workspace.py` |
| Duplicate SSE event ID, legitimate identical text tokens | `frontend/src/utils/chatSseStream.test.ts` |
| Desktop scoped composer TTL/isolation | `frontend/src/utils/chatComposerDraft.test.ts` |
| Task-center SSE exponential backoff | `frontend/src/stores/agentTaskCenter.test.ts` |

## Verification commands

```bash
cd FHD
python -m pytest tests/test_routes/test_mobile_native_task_workspace.py
cd frontend
npm ci
npx vitest run src/utils/chatSseStream.test.ts src/utils/chatComposerDraft.test.ts src/stores/agentTaskCenter.test.ts
cd ../mobile-flutter-poc
flutter pub get
flutter analyze
flutter test test/task_list_screen_test.dart test/offline_store_test.dart test/im_realtime_test.dart test/approval_continuity_test.dart
```

## Required independent device evidence, not implied by source or mocked tests

These scenarios require Windows/macOS desktop plus a real Android/iOS Flutter
build using the same test account, tenant and original task. Preserve service
logs, timestamps, server task/run IDs and approval receipts, and independent
before/after snapshots. **Until evidence exists, mark each scenario WAITING_DEVICE:**

- Desktop starts task → Android/iOS observes the same task ID → mobile approves
  one original step → desktop displays the original run receipt, without a second
  execution.
- Drop SSE after accepted POST; restart both processes; verify only the original
  turn is queried, never a second business POST.
- Disconnect/reconnect WebSocket under latency and duplicate delivery; verify
  identical message IDs are rendered once and server history reconciles gaps.
- Suspend, force-stop, relaunch and change account/tenant while pending; verify
  no wrong-account content, duplicate approval or stale write buttons.
- Revoke permission after local cache population; verify old content/actions
  disappear and no offline mutation is applied.
- Restart midway through attachment upload; verify reselect/re-upload is
  required and stale upload IDs are not reused.

Passing mocked tests alone is **not** production certification; require green
CI at the final PR head, desktop/native device artifacts, and server-side
reconciliation logs before declaring end-to-end PASS.
