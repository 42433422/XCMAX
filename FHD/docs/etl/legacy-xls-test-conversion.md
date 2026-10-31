# 旧 XLS 的有限用途派生转换

归档入口接收 `.xls` 后，客户端按原件计算 SHA-256，并要求逐文件确认：
**仅供数据/模板测试，打印版式未验证，不得发布到企业模板库。**
API 的 `legacy_test_only=true` 和 `legacy_source_sha256` 必须同时匹配；取消则不提交。
既有分类恢复直接使用持久化派生文件，不重转；显式重新分类需再次确认。

## 支持范围

纯 Python `xlrd` + `openpyxl`，没有 Office/LibreOffice、shell、宏执行或联网读取依赖。
仅普通 BIFF8 工作表，20 MB、32 sheet、20,000 矩形单元格、8 MiB 展开文本、
100,000 BIFF 记录及 20,000 显式行列格式上限。合并区域及联合坐标范围在解析分配前限制。
这是进程内结构预算，不是硬内存/墙钟沙箱；不声称具备跨平台进程隔离。
转换前检查 OLE streams / BIFF records，未知或可执行特性拒绝；公式、外链、宏、
嵌入/绘图对象、批注、验证规则、日期/错误值、混合字体富文本、手工分页、
非空页眉页脚、使用中的 XF 扩展等当前不支持，不会静默改成字符串。

数据类型、位置、sheet 顺序、合并区域、原始 XML 单元格样式、默认及显式行列尺寸/样式、
隐藏/分组状态，以及支持的打印标量设置均独立读回核验。字体以 BIFF FONT weight
400/700 为准，不使用未定义的粗体 bit。字面量 `=...` 文本不转换成公式。

## 不能据此验收的部分

- 自定义纸张（例如代码 256）实际尺寸、驱动定义、Windows 字体及打印结果未验证。
- WPS `ETExtData`、未使用格式扩展等只保留在原件；转换收据显示具体 warning。
- 窗口、冻结窗格、选区、缩放等视图元数据不迁移。
- 合并内部样式原始 XML 保留，但 openpyxl/其他软件可能规范化；收据报告数量。
- 保存 XLSX 成功不等于打印保真，纯 Python 可移植不等于 Windows 客户端实测通过。

## 来源与发布边界

原始 XLS 原样归档，原件下载仍返回 XLS。分类、预览及后续保存读取同一持久化派生
XLSX；两个 hash 分别存储，转换器版本、验证项目、用途及 warning 存入服务端 run
summary。转换产物计入归档配额，读取受租户/所有者与原件版本/hash 校验约束。

受限文件可分类、预览、下载测试候选；正式发布返回具体拒绝原因。
限制从服务端 classification/review lineage 判定，不能通过删除 XLSX custom property
或最新 UI 元数据绕过。原本不受限的普通 XLSX 流程不变。

## 验证与部署

生产后端是 `reviewed_excel_legacy.py`，产品树不包含已替代的 LibreOffice runner。
`pyproject.toml`、服务端和桌面 requirements 均已声明 xlrd/openpyxl；冻结安装包
显式收集 xlrd 与 openpyxl。未在本 Linux 环境声称完成 Windows 安装包构建/运行实测。
合成 BIFF fixtures 在测试目录，不含客户原件。
运行专项：`python -m pytest tests/test_application/test_reviewed_excel_legacy.py`。
发布仍需父 PR 整合、CI、部署与客户端实测；本地通过不代表已上线。

## 切片链自动转换

本地/自动切片入口使用 `convert_xls_to_xlsx_for_slice` / `ensure_slice_workbook`：
在 classify→group→slice 前将 OLE/BIFF8 `.xls` 转为派生 XLSX，再走普通 openpyxl
检视与 2000 格 / 384KB 传输包路径。收据 `purpose=slice_pipeline_auto_convert`。
归档 HTTP 仍要求 `legacy_test_only` + 原件 SHA；上传模板默认 `allow_legacy=False`
继续拒绝未确认的 raw `.xls`。

