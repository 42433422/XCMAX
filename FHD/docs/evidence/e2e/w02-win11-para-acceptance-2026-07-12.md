# W-02 Win11 真机验收（DevFleet / Para · 2026-07-12）

> **通道**：DevFleet `devfleet_run_remote_command` + ToDesk 人工已连接  
> **设备**：`5fdd29c4-9140-48fa-a28b-ab5db375201f` · Win11 **家庭中文版** 26200 · ROG  
> **证据根**：`FHD/docs/evidence/e2e/w02-win11-para-20260712/`  
> **录屏**：`rec/w02-acceptance.gif` — **内容复核 FAIL（不可当 UI 走查签字）**  
> **截图**：`shots/` 仅作定格参考

## 命令冒烟

安装 / health / API 登录 / ERP API：**PASS**（与录屏脱钩）。

## 录屏逐帧复核（2026-07-12 · 人工看图）

像素门禁曾报 PASS（unique=26 · motion=16/99），但**肉眼逐帧不合格**：

| 帧段 | 画面实际内容 | 判定 |
|------|--------------|------|
| ~1–5 | 桌面杂乱 + ToDesk「弱密码」弹窗 + 终端 | 非产品走查 |
| ~22–50 | Edge 反复停在 **`/login` 企业账号登录页**（redirect 到 /erp|/materials 仍回登录） | **未完成 UI 登录** |
| ~49 | 登录页上叠 XCAGI 小窗，仍是登录 | 无 ERP 列表 |
| ~53–100（约 64 帧同哈希） | 「智能对话 / 运维对话」ADMIN 欢迎气泡，**几乎定格到片尾** | 后半无效 |

结论：有画面变化 ≠ 验收走查。v4 GIF **不能签字**。  
Windows App/RDP 因 Home 版不可用；下一步须在 ToDesk 里**人工登录并点进 ERP/订单/物料**再录，或 Playwright 填表登录后再抓屏。

## 录屏版本史

| 版本 | 结论 |
|------|------|
| v1–v2 | FAIL 定格 |
| v3 | 运动门禁 PASS（MoveWindow，非走查） |
| v4 | 运动门禁数字 PASS；**内容复核 FAIL**（本条） |
