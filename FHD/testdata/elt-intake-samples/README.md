# ELT / MIMO 入库回归样例包

合成、无真实客户 PII 的小型样例，用于数据对接（丢文件 → 选模板 → 自动入库）与知识库问答回归。

> 与 `/workspace/batch1019/` 证据树分离：本目录**进仓库**，可在 CI / 本机 / Windows 包旁复用。

## 文件

| 文件 | 标签 | 用途 |
|------|------|------|
| `demo-delivery-note-xingguang.xlsx` | `delivery` / `A4模板` | 送货单风格表头 + 两行明细（合成「星光/七彩」） |
| `demo-purchase-order-qicai.xlsx` | `purchase` | 采购订单风格表头 + 两行物料 |
| `demo-shipment-lines.csv` | `shipment-csv` | 极简出货行，便于 CSV 路径冒烟 |
| `MANIFEST.json` | — | 机器可读标签与期望关键字 |

所有公司名、联系人、单号均带 `示例` / `DEMO-` 前缀，禁止换成真实客户数据后回传到本目录。

## 怎么用

### 1) 桌面 / 本机丢文件冒烟

1. 打开 XCAGI → 智能对话底栏或数据对接入口  
2. 拖入本目录任一 `.xlsx`  
3. 「开始处理」→ A4 选模板（或产品当前默认模板）  
4. 确认自动进入知识库 + 业务库（审批中心可见）  
5. 知识库提问示例：`DEMO-PO-20261010-001 是谁的订单？`（期望命中星光/七彩示例文案）

### 2) DatasetRag API / 脚本（无 GUI）

```bash
# 在 FHD 根目录，PYTHONPATH=.
python - <<'PY'
from pathlib import Path
from app.application.dataset_rag_app_service import DatasetRagApplicationService
root = Path("testdata/elt-intake-samples")
svc = DatasetRagApplicationService(
    storage_path=Path("/tmp/elt-intake-demo-store.json"),
    allowed_roots=[root.resolve()],
    rebuild_workers_enabled=False,
)
path = root / "demo-delivery-note-xingguang.xlsx"
r = svc.ingest_document(
    dataset_id="office-docking",
    source=path.name,
    file_path=str(path),
    document_id="demo-delivery",
    tenant_id="elt-intake-samples",
    idempotency_key="demo:delivery",
)
print("ingest", r.get("success"), r.get("chunk_count"))
ans = svc.answer(dataset_id="office-docking", query="订单编号是什么？", tenant_id="elt-intake-samples", top_k=3)
print(ans.get("answer", "")[:240])
PY
```

期望回答前缀为中文产品口径：`根据知识库资料，关于「…」：`（见 P1-4），且正文含 `DEMO-PO-20261010-001`。

### 3) 与完整度闸门的关系

`batch1019/func-completeness-*/` 可继续用历史切片；**新开回归优先本目录**，避免依赖 box-only 大文件。缺口表见同次实测 `GAP_LIST.md` 的 P2-4。

## 维护

- 保持单文件 < 50KB；禁止提交客户原件或含手机号/税号的表格。  
- 改样例后同步更新 `MANIFEST.json` 的 `expect_substrings`。  
