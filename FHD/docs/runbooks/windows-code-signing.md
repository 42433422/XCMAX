# XCAGI Windows 稳定版签名与发布

这是 XCAGI 企业桌面的唯一 Windows 签名流程。个人版已冻结，不得重新构建或写入稳定通道。

正式发布使用 SSL.com eSigner + CodeSignTool。`Release Desktop` 会先做双平台预检，再并行构建 Windows 和 macOS；只有两边都成功，才会由同一个任务发布完整制品和清单。不要绕过该工作流手工覆盖 `releases/stable`。

## 1. 完成 SSL.com 侧开通

1. 完成账户激活、账单资料、付款和企业身份验证。
2. 等待 Code Signing 证书签发，并确认 eSigner 已启用。
3. 为 CI 启用自动 TOTP，取得 eSigner Credential ID 和 TOTP secret。
4. 记录证书 Subject 中的准确组织名称。它必须与 `XCAGI_WINDOWS_PUBLISHER_NAME` 完全对应；不要按中文公司名猜测。

任何付款、验证码、身份核验或证书批准步骤都必须由账户持有人完成。

## 2. 配置 GitHub

Repository secrets：

```text
ES_USERNAME
ES_PASSWORD
CREDENTIAL_ID
ES_TOTP_SECRET
```

Repository variable：

```text
XCAGI_WINDOWS_PUBLISHER_NAME
```

该 variable 必须是证书 Subject 中实际出现的组织名称。工作流不提供默认值，缺失会在任一平台开始构建前失败。

桌面稳定发布还要求现有的 macOS 公证、更新元数据和服务器上传 secrets：

```text
CSC_LINK
CSC_KEY_PASSWORD
APP_STORE_CONNECT_API_KEY_ID
APP_STORE_CONNECT_API_ISSUER_ID
APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64
APPLE_TEAM_ID 或 IOS_TEAM_ID
XCAGI_UPDATE_ED25519_PRIVATE_KEY
SERVER_SSH_KEY 或 FHD_PUSH_SSH_KEY
```

不要把任何 secret 写入仓库、Issue、PR、CI 命令输出或聊天。

## 3. 签名链

工作流用固定提交版本的 SSL.com CodeSignTool 安装器准备工具，然后由 Electron Builder 的 `desktop/build/windows-sign.cjs` 自定义签名钩子调用 eSigner。签名发生在 NSIS 组装过程中，因此不是只签最外层安装器。

发布闸门会用 Windows 系统 `Get-AuthenticodeSignature` 验证以下三个对象：

```text
win-unpacked/XCAGI.exe
win-unpacked/resources/backend/xcagi-backend.exe
XCAGI-Enterprise-Setup-<version>-x64.exe
```

三者都必须满足：

- `Status=Valid`
- Signer Subject 包含 `XCAGI_WINDOWS_PUBLISHER_NAME`
- 存在受信任时间戳证书

签名校验通过后，Windows 发布任务还会把同一个 NSIS 安装包静默安装到隔离目录，并执行以下门禁：

- 安装后的桌面与后端可执行文件仍保持有效签名和可信时间戳；
- `build-info.json` 的完整 Git SHA、版本号与当前发布任务完全一致；
- 安装后的企业版真实启动，`/api/health`、`/api/desktop/status`、Mod 与核心业务烟测全部通过；
- 静默卸载成功，且用户数据按 `deleteAppDataOnUninstall=false` 保留。

这道 CI 门禁用于阻止“文件签了名但安装后不能运行”的制品发布，不能替代真实 Win10/Win11 设备上的可见界面验收。

## 4. 发布

证书已签发且所有配置齐全后，从主分支运行：

```bash
gh workflow run fhd-release-desktop.yml \
  --repo 42433422/XCMAX \
  -f version=1.0.0.1 \
  -f verify_only=false
```

发布任务必须依次证明：

1. Windows 和 macOS 构建、签名、公证全部成功；
2. 两个平台的更新元数据都带 Ed25519 签名和同一 `buildSha`；
3. official 路径完整写入后，稳定通道才更新；
4. 公网下载返回完整字节，大小和 SHA256 与 manifest 一致；
5. Windows 公网 EXE 在独立 `windows-latest` 任务上再次满足 Authenticode
   `Status=Valid`、证书 Subject 和可信时间戳要求；
6. `latest.yml` 与 `latest-mac.yml` 在 stable/official 两条路径完全一致；
7. 上述公网验证全部通过后，才更新网站下载指针。

公开路径：

```text
https://xiu-ci.com/xcagi-v1.0.0.1/enterprise/
https://xiu-ci.com/releases/stable/enterprise/
```

发布完成后仍需在真实 Win10/Win11 设备完成可见界面的安装、启动、自动升级和回滚验收，才能判定 Windows 稳定上线完成。
