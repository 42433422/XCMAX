# 管理端 Mod 运行目录（mods-admin-runtime）

与企业端空目录 `FHD/mods/` 分离。预置 GENERIC 9 bridge，供 `:5011` 管理端与后端扫描。

同步：

  bash FHD/scripts/dev/sync-admin-mod-runtime.sh

源：`../mods-export-2026-06-07/`（勿手改 export，改 Mod 后重新 sync）
