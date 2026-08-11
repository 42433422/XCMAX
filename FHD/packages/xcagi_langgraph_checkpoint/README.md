# XCAGI vendored langgraph-checkpoint (LG-W0-03)

原样吸收 LangGraph `libs/checkpoint` 包，锁定远端 tag `1.2.10` @ commit `41341457342327166d72fc11952ab28fb61ec0bf`。

- 源码结构保持上游原样（`langgraph/` 命名空间子包 `checkpoint/` `store/` `cache/` + MIT `LICENSE`），未改动任何业务源码。
- 依赖为 registry（`langchain-core` / `ormsgpack`），无 vendored 兄弟包依赖。
- 本包自带 uv 环境与 `uv.lock`，与 FHD 根依赖锁隔离；**不修改 FHD 根 pyproject/uv.lock**。
- 来源/许可证锁定见 [PROVENANCE.json](PROVENANCE.json) 与 [verify_vendor.py](verify_vendor.py)；文件哈希见 [MANIFEST.sha256](MANIFEST.sha256)。

## 校验

[verify_vendor.py](verify_vendor.py) 完全自包含、可移植：在临时目录内自行拉取上游远端 tag `1.2.10`，
校验其解析 commit 为锁定 SHA，再与本地副本字节级比对（不依赖任何固定本地检出）。

```bash
python verify_vendor.py            # LICENSE + MANIFEST.sha256 + 在线上游 tag 比对
python verify_vendor.py --offline  # 仅本地清单 + LICENSE
python verify_vendor.py --gen      # 修改源码后重新生成 MANIFEST.sha256
```

## 测试（uv，锁定依赖）

```bash
uv sync                 # 依据 pyproject + uv.lock 创建 .venv
uv run --locked pytest  # 以锁定依赖运行（无 sys.path 注入，验证已安装包的公开符号导入）
uv lock --check         # 校验 uv.lock 与 pyproject 一致
```

验收：`uv run --locked pytest` 全绿，且测试从 **uv 安装的包** 导入真实公开符号
`SerializerProtocol` / `JsonPlusSerializer` / `BaseCheckpointSaver` / `InMemorySaver` / `BaseStore`（无路径注入）。
