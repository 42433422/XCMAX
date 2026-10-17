# 软件闭环 1.0.0.6 安装/更新生命周期：节点 12–15 全部证据（2026-10-15）

来源（均为 2026-10-15 生成）：用户 U 盘 `/Volumes/KINGSTON/XCMAX-node12-node15-final-20261015/` 和 `/Volumes/KINGSTON/XCMAX-node12-node13-final-20261015/`，以及 Mac mini 上的 `/private/tmp/xcagi-mac-c5-20261015/evidence/`。
入库文件都是原件的逐字节拷贝，只有访问日志例外：它换成了脱敏版。2026-10-17 重新计算了全部哈希，并与各份清单和报告中的引用逐个核对。

> 范围限定：仅 1.0.0.6 安装/更新生命周期交付（节点 12–15）。**不是**整个软件全功能闭环或工单闭环的通过结论。

## 文件清单

| 文件 | sha256 | 结论字段 |
| --- | --- | --- |
| `node12-node15-evidence-file-manifest.json` | `59d2b351acacce3f09991cadf00680f5ac0a887c2ad9c9972babd65a8d3abefa` | 证据包清单（41 个文件） |
| `node14-node15-server-delivery-final.json` | `459e85bb1093c052a23fbd4a708695cd9fb98c25e2ae1b5ce099feee329236be` | `result: PASS`，节点 12/13/14/15 均 PASS |
| `node14-server-distribution-final.json` | `64c941c13e6b0e24855c8de17b3226f365c28034aff881e6423ecd58abbdb691` | 节点 14 `result: PASS` |
| `node15-user-conditional-acceptance-final.json` | `b01d2bdaedaa8ebc18d12f96083859632b6b5f858bc14a7e176cfed98ba86334` | 节点 15 `result: PASS`（有条件验收，条件已满足） |
| `node15-user-conditional-acceptance-source.json` | `02c6f7fa329a07d73e94012a06a11f43842a9dffba7cdac684f63fbf9e69e1d0` | 节点 15 用户原话来源（证据包内文件） |
| `node14-node15-final-reference-consistency.json` | `089ad572ed6c0beef163fd82019396988f3b41986d40d9e878b294022bae47f4` | `result: PASS` |
| `node12-node15-bundle-verification-final.json` | `2c8b03aaba43c60f05ab28b49800aadc302b654bb3b127e9c9fef07f23d2a58b` | `result: PASS`，42 个条目逐一核验 |

## 目录结构

- 根目录：U 盘 `XCMAX-node12-node15-final-20261015/` 的报告 JSON（逐字节原件）。
- `mac-c5-evidence/evidence/`：Mac mini `/private/tmp/xcagi-mac-c5-20261015/evidence/` 原件中的 JSON、Markdown 和日志，也就是 `node14-node15-server-delivery-final.json` 的 `sourceReports`/`supportingEvidence` 引用的原件（如 `node13-joint-verification-final.json`、`mac-c5-lifecycle-final.json`、`history/`）。全部逐字节原样，只有访问日志例外（见下）。
- `node12-node13-final/evidence-file-manifest.json`：U 盘 `XCMAX-node12-node13-final-20261015/` 的清单。该目录另外 2 个文件 `node13-joint-verification-final.json` 和 `node12-node13-joint-conclusion.md` 与 `mac-c5-evidence/evidence/` 下的同名文件逐字节相同，所以不重复入库。
- `software-loop-ledger.json`：本版本软件闭环（安装/更新生命周期范围）总账。
- `cos-objects.json`：COS 私有桶里全部原件的对象键、大小和 sha256。

## 只登记哈希、原件放在 COS 私有桶的文件

COS 私有桶 `xcagi-evidence-1374207682`（ap-chengdu），前缀 `software-loop/1.0.0.6-nodes12-15/`，共 81 个对象，全部为原件。每个对象上传后都重新下载核对了 sha256，匿名访问返回 403。逐个对象的清单见 `cos-objects.json`。以下文件不进公开仓库：

| 文件 | 原因 |
| --- | --- |
| `node12-node15-final/node12-node15-delivery-evidence.zip`（836465 B，`bc3b5372ab1fd8b5578249efe8428872c2e99c251698cea293d9865692560d26`） | 包内有未脱敏的访问日志和 SUNBIRD 数据目录的逐行哈希快照 |
| `node12-node13-final/node12-node13-mac-c5-evidence.zip`（807614 B，`9abb4eb83a2fb8df12466592175bde2a28325abcb8b27687020a4c9742e2a80d`） | 同上（嵌套的 ota-r3、recovery-r1 快照）；与上面 zip 内 `handoff/` 下的同名文件逐字节相同 |
| `mac-c5/evidence/node14-server-access-originals/xiu-ci.com.access.log`（17990 B，`702b3b14132af5a736baf6d074dec219eaadafe8b73fa09a65a6b27da9fce40a`） | 含第三方访客公网 IP。仓库里只放脱敏版 `xiu-ci.com.access.redacted.log`：5 个访客 IPv4 统一替换成 `REDACTED-IPV4-n`，自家服务器 `119.27.178.147` 和 `127.0.0.1` 保留，其余字节不变 |
| `mac-c5/evidence/c5-preupdate-snapshot.json`（177252 B） | SUNBIRD 实机数据库逐行哈希快照 |
| `mac-c5/evidence/ui-screenshots/*.jpg`（4 张） | 截图按仓库惯例不进公开仓库。哈希见 `mac-c5-evidence/evidence/ui-screenshots/original-image-index.json` |
| `mac-c5/evidence/*.txt`（rsync dry-run 列表 2 个，空文件 3 个）、`*.py`（3 个取证脚本） | 体积大或不是结论证据；脚本不放进仓库的 lint 范围 |

上传前已排除：两个 `.app` 安装副本，以及 `prep-userdata-from-kingston-side-copy-not-used`（用户数据）。完整二进制在 `/Volumes/KINGSTON/XCMAX-mac-aligned-c5-20261015.sparsebundle`。2026-10-17 上传时另有一份 zip 副本存放在 `delivery-evidence/1.0.0.6/node12-node15-20261015/`，内容相同。

## Windows 7102b713 验收证据（COS）

前缀 `windows-acceptance/1.0.0.6-7102b713/`，由另一个任务从佳诺 `C:\XCAGI-QA\candidate-longpath\evidence\` 等目录上传。2026-10-17 12:28（UTC+8）核对时共有 132 个对象：
- 上传清单 `objects` 列出 124 个对象，含 `SHA256SUMS` 和 12:28 补传的两份后端日志
- 另有 `server-verify-20261017/` 下的 7 个复核回执
- 以及清单文件本身

本目录 `windows-7102b713-cos/` 收录了以下文件：

| 文件 | sha256 |
| --- | --- |
| `cos-win1006-upload-manifest.json`（updated_at 2026-10-17T12:28:16+08:00，与 COS 上的同名对象逐字节相同） | `e347920b56b78c12f9c1aea63fed592e780f55aa0fdd7605eb2e85decb4cd3bd` |
| `SHA256SUMS`（列出首批 121 个文件；两份后端日志的哈希见上传清单） | `c8fe31eab5b56905510a6e7b9eb28ff9c186d3d53cf788cec77806f6305a4686` |
| `XCAGI-Enterprise-Setup-1.0.0.6-x64.exe.verify-20261017.json`（服务器回执，服务器路径 `/var/www/xcagi-v1.0.0.6/enterprise/`，COS 对象 `server-verify-20261017/`） | `db58136a5d0b2c5e584534fdfb8fb435a3cba9ac4f711de671d50ae7f0a96003` |

服务器回执结论原文：`status: SERVER_VERIFIED_PUBLIC_DOWNLOAD_VERIFIED`。服务器上的文件 `ALREADY_PRESENT_AND_IDENTICAL`（331819335 B，sha256 `9D7025E9…F40100`，2026-10-15 22:00 上传，没有重传），公网完整下载的 sha256 也一致。`authenticode: NotSigned`。

2026-10-17 核对：
- 上传清单里的 124 个对象都在 COS 上，对象元数据记录的 sha256 与清单一致。
- `SHA256SUMS` 列出的 121 个文件都在，哈希一致。

仍然排除的 6 个文件见清单的 `excluded`：一张含配对二维码的截图，以及 5 个脚本或 curl 配置。是否补传由用户决定。

## 2026-10-17 核对结果

- U 盘 node12–15 目录的 7 个文件：重新计算的 sha256 与清单一致。
- 所有报告中有路径的 sha256 引用共 131 条（sourceReports、supportingEvidence、originalReceipt、finalReport 等）：120 条与原件一致；11 条指向未收入的文件（安装包、更新器缓存、SQLite 备份、服务器 /var/www 文件），这些文件本来就不在证据包内，其中三个安装包另有公开下载的哈希核验。没有任何一条不一致。
- node12–13 清单列出 79 个文件，与嵌套 zip 和 mac-c5 原件核对后全部一致；两个 node12-node13 zip 逐字节相同。
- mac-c5 原件与 node12–15 zip 内 `evidence/` 下的同名文件逐字节相同。
- 解压 zip：42 个条目，清单列出的 41 个文件全部存在，大小和 sha256 全部一致（第 42 个条目是清单本身，与 U 盘上的清单文件逐字节相同）。
- 4 个顶层报告 JSON 与 zip 内 `evidence/` 下同名文件逐字节相同。
- 敏感信息扫描：未发现密钥、令牌、密码或客户个人数据；快照中的 `password`、`totp_secret` 等只是表结构列名，记录只有行哈希。截图只有合成测试数据（`mac-c5-lifecycle-attachment.xlsx`）。

## 结论原文摘要（不作拔高）

- 节点 12、13：PASS。Mac 与 Windows 的完整源码 SHA **不同**（Mac `c5e066acff7f50edf5f1e506abcca33372cc6033`，Windows `7102b713df1136ae83848eed5814a60ede66a355`）。按用户采纳的“同代码树”口径判定通过（共同 tree `60aef1efa8c18fb01cea7c7234716c2e5b758671`，`sameFullCommitSha: false`）。Windows 部分复用原执行方回执（PR #2340），本轮没有在 Windows 实机重跑（`newDeviceAcceptanceRun: false`）。
- 节点 14：PASS。范围是 `https://xiu-ci.com/xcagi-v1.0.0.6/` 上按版本独立手动下载。3 个安装包匿名完整下载，大小和 sha256 均与批准值一致。Windows 安装包未签名（`NotSigned, accepted under explicit user policy`）。**不包括** stable OTA 自动更新和官网默认版本指针切换。
- 节点 15：PASS，属于有条件验收。用户原话：“如果能正常下的话就说明可以了,然后我这边就通过了。如果没法正常下载,你再看核查什么问题就行”。条件：`All three actual published package files download normally and match approved complete sizes and SHA256`。2026-10-15 22:49:47（UTC+8）判定条件满足。验收依据是代理执行的公开下载核验：`userPersonallyDownloadedOrInstalledClaimed: false`，`independentExternalCustomerSignatureOrOperationClaimed: false`。
- 声明的限制：只验收了 Mac M4 arm64，Intel Mac 不在本轮范围；普通业务功能不在本轮范围；未推送 stable OTA，也未切换官网默认版本；不包括生产应用部署；没有外部客户本人安装或签收。
